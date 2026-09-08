"""Durable Workbench jobs. A browser connection never owns graph execution."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from functools import lru_cache
from typing import Callable

from aes_agent.auth import database_settings
from aes_agent.db_pool import get_database_pool
from aes_agent.run_progress import use_run_progress

logger = logging.getLogger("aes_agent.runs")
LEASE_SECONDS = 120


class RunConflictError(Exception):
    pass


class RunStoreUnavailable(Exception):
    pass


def request_fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def public_run(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "conversation_id": row["conversation_id"],
        "status": row["status"],
        "progress": row["progress"],
        "response": row.get("response"),
        "error": row.get("error"),
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


class PostgresRunRepository:
    def _connect(self):
        try:
            return get_database_pool(database_settings()).connection()
        except Exception as exc:
            raise RunStoreUnavailable("AES run database is unavailable.") from exc

    def _query(self, sql: str, parameters: tuple = ()):
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql, parameters)
                    if cursor.description:
                        return cursor.fetchone()
                    return None
        except RunStoreUnavailable:
            raise
        except Exception as exc:
            logger.warning("Run database operation failed: cause=%s", _failure_kind(exc))
            raise RunStoreUnavailable(
                "AES run storage is unavailable. Check database migrations and connectivity."
            ) from exc

    def get(self, run_id: str, user_id: str) -> dict | None:
        return self._query(
            """SELECT id, user_id, conversation_id, request_fingerprint, status,
                      progress, response, error, created_at, updated_at
               FROM workflow.aes_run WHERE id = %s AND user_id = %s""",
            (run_id, user_id),
        )

    def create(self, run_id: str, user_id: str, conversation_id: str,
               fingerprint: str, request: dict) -> dict:
        # The primary key is the browser's persisted idempotency key. Repeated
        # submissions cannot enqueue another solve, including concurrent retries.
        self._query(
            """INSERT INTO workflow.aes_run
                   (id, user_id, conversation_id, request_fingerprint, request)
               VALUES (%s, %s, %s, %s, %s::jsonb)
               ON CONFLICT (id) DO NOTHING""",
            (run_id, user_id, conversation_id, fingerprint, json.dumps(request)),
        )
        row = self.get(run_id, user_id)
        if row is None or row["request_fingerprint"] != fingerprint:
            raise RunConflictError("This request ID is already in use for another request.")
        return row

    def claim(self, worker_id: str) -> dict | None:
        return self._query(
            """WITH candidate AS (
                   SELECT id FROM workflow.aes_run WHERE status = 'queued'
                   ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED
               )
               UPDATE workflow.aes_run AS r
               SET status = 'running', worker_id = %s, heartbeat_at = now(),
                   started_at = now(), updated_at = now()
               FROM candidate WHERE r.id = candidate.id RETURNING r.*""",
            (worker_id,),
        )

    def heartbeat(self, run_id: str, worker_id: str) -> bool:
        return self._query(
            """UPDATE workflow.aes_run SET heartbeat_at = now()
               WHERE id = %s AND worker_id = %s AND status = 'running' RETURNING id""",
            (run_id, worker_id),
        ) is not None

    def expire_abandoned(self) -> None:
        self._query(
            """UPDATE workflow.aes_run
               SET status = 'interrupted', finished_at = now(), updated_at = now(),
                   error = 'The execution worker stopped responding. This run was not replayed. Submit a new request to retry.'
               WHERE status = 'running'
                 AND heartbeat_at < now() - (%s * interval '1 second')""",
            (LEASE_SECONDS,),
        )

    def progress(self, run_id: str, worker_id: str, node: str, phase: str) -> None:
        step = {"id": node, "label": node.replace("_", " ").capitalize(),
                "detail": "Running" if phase == "started" else "Completed",
                "status": "active" if phase == "started" else "done"}
        self._query(
            """UPDATE workflow.aes_run SET updated_at = now(), heartbeat_at = now(),
                   progress = CASE WHEN progress @> %s::jsonb
                       THEN (SELECT jsonb_agg(
                           CASE WHEN item->>'id' = %s THEN %s::jsonb ELSE item END
                           ORDER BY ordinal)
                           FROM jsonb_array_elements(progress) WITH ORDINALITY AS p(item, ordinal))
                       ELSE progress || %s::jsonb END
               WHERE id = %s AND worker_id = %s AND status = 'running'""",
            (json.dumps([{"id": node}]), node, json.dumps(step), json.dumps([step]), run_id, worker_id),
        )

    def finish(self, run_id: str, worker_id: str, status: str,
               response: dict | None, error: str | None) -> bool:
        return self._query(
            """UPDATE workflow.aes_run SET status = %s, response = %s::jsonb,
                   error = %s, finished_at = COALESCE(finished_at, now()), updated_at = now()
               WHERE id = %s AND worker_id = %s AND status IN ('running', %s)
               RETURNING id""",
            (status, json.dumps(response), error, run_id, worker_id, status),
        ) is not None


def _failure_kind(exc: Exception) -> str:
    while exc.__cause__ is not None:
        exc = exc.__cause__
    return type(exc).__name__


class RunWorker:
    """One graph job at a time per API process, backed by a PostgreSQL queue."""
    def __init__(self, repository: PostgresRunRepository,
                 execute: Callable[[dict], dict], *, poll_seconds: float = 1,
                 heartbeat_seconds: float = 5):
        self.repository = repository
        self.execute = execute
        self.poll_seconds = poll_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.worker_id = str(uuid.uuid4())
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, daemon=True, name="aes-run-worker")
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.repository.expire_abandoned()
                row = self.repository.claim(self.worker_id)
                if row:
                    self.execute_claimed(row)
                    continue
            except Exception:
                logger.exception("Run worker could not poll its durable queue.")
            self.stop_event.wait(self.poll_seconds)

    def execute_claimed(self, row: dict) -> None:
        run_id = str(row["id"])
        finished = threading.Event()
        pending_progress: dict[str, str] = {}
        progress_lock = threading.Lock()
        progress_deferred = False

        def flush_progress() -> bool:
            nonlocal progress_deferred
            with progress_lock:
                try:
                    for node, phase in list(pending_progress.items()):
                        self.repository.progress(run_id, self.worker_id, node, phase)
                        del pending_progress[node]
                except RunStoreUnavailable as exc:
                    if not progress_deferred:
                        logger.warning(
                            "Run progress buffered until database recovers: run_id=%s cause=%s",
                            run_id, _failure_kind(exc),
                        )
                    progress_deferred = True
                    return False
                if progress_deferred:
                    logger.info("Buffered run progress saved: run_id=%s", run_id)
                    progress_deferred = False
                return True

        def progress(node: str, phase: str) -> None:
            with progress_lock:
                pending_progress[node] = phase
            flush_progress()

        def heartbeat():
            delay = self.heartbeat_seconds
            failures = 0
            last_success = time.monotonic()
            while not finished.wait(delay) and not self.stop_event.is_set():
                try:
                    if not self.repository.heartbeat(run_id, self.worker_id):
                        if not finished.is_set():
                            logger.warning("Run heartbeat stopped: run_id=%s lease_no_longer_active=true", run_id)
                        return
                except RunStoreUnavailable as exc:
                    failures += 1
                    delay = min(self.heartbeat_seconds, 2 ** min(failures - 1, 3))
                    age = time.monotonic() - last_success
                    logger.log(
                        logging.ERROR if age >= LEASE_SECONDS else logging.WARNING,
                        "Run heartbeat delayed: run_id=%s failures=%s last_success_age_seconds=%.1f "
                        "retry_seconds=%s cause=%s",
                        run_id, failures, age, delay, _failure_kind(exc),
                    )
                    continue
                except Exception:
                    logger.exception("Unexpected run heartbeat error: run_id=%s", run_id)
                    continue
                if failures:
                    logger.info("Run heartbeat recovered: run_id=%s failures=%s", run_id, failures)
                failures = 0
                last_success = time.monotonic()
                delay = self.heartbeat_seconds
                flush_progress()

        keeper = threading.Thread(target=heartbeat, daemon=True, name="aes-run-heartbeat")
        keeper.start()
        logger.info("Durable run started: run_id=%s user_id=%s", run_id, row["user_id"])
        response = None
        error = None
        try:
            with use_run_progress(progress):
                response = self.execute(row)
            status = "failed" if response.get("aes_result", {}).get("agent_status") == "tool_error" else "completed"
        except Exception:
            logger.exception("Durable run failed: run_id=%s", run_id)
            status = "failed"
            error = "AES execution failed. The backend logs contain details for this run ID."
        try:
            # If persistence briefly fails after expensive computation, retry the
            # write with the same response; never rerun the graph to recover it.
            while not self.stop_event.is_set():
                try:
                    if not flush_progress():
                        self.stop_event.wait(2)
                        continue
                    if not self.repository.finish(run_id, self.worker_id, status, response, error):
                        logger.error(
                            "Run result was not saved: run_id=%s worker lease lost or run interrupted",
                            run_id,
                        )
                        break
                    logger.info("Durable run finished: run_id=%s status=%s", run_id, status)
                    break
                except RunStoreUnavailable:
                    logger.exception("Retrying result persistence: run_id=%s", run_id)
                    self.stop_event.wait(2)
        finally:
            finished.set()
            keeper.join(timeout=1)


@lru_cache(maxsize=1)
def get_run_repository() -> PostgresRunRepository:
    return PostgresRunRepository()
