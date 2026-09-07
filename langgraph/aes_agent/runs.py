"""Durable Workbench jobs. A browser connection never owns graph execution."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from functools import lru_cache
from typing import Callable

from aes_agent.auth import database_settings
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
            import psycopg
            from psycopg.rows import dict_row
            settings = database_settings()
            return psycopg.connect(
                host=settings.host, port=settings.port, dbname=settings.database,
                user=settings.user, password=settings.password,
                connect_timeout=settings.connect_timeout_seconds,
                options="-c statement_timeout=10000", row_factory=dict_row,
            )
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
            logger.exception("Run database operation failed.")
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
            """UPDATE workflow.aes_run SET updated_at = now(),
                   progress = CASE WHEN %s = 'started' THEN progress || %s::jsonb
                       ELSE COALESCE((SELECT jsonb_agg(
                           CASE WHEN item->>'id' = %s THEN %s::jsonb ELSE item END
                           ORDER BY ordinal)
                           FROM jsonb_array_elements(progress) WITH ORDINALITY AS p(item, ordinal)), '[]'::jsonb) END
               WHERE id = %s AND worker_id = %s AND status = 'running'""",
            (phase, json.dumps([step]), node, json.dumps(step), run_id, worker_id),
        )

    def finish(self, run_id: str, worker_id: str, status: str,
               response: dict | None, error: str | None) -> None:
        self._query(
            """UPDATE workflow.aes_run SET status = %s, response = %s::jsonb,
                   error = %s, finished_at = now(), updated_at = now()
               WHERE id = %s AND worker_id = %s AND status = 'running'""",
            (status, json.dumps(response), error, run_id, worker_id),
        )


class RunWorker:
    """One graph job at a time per API process, backed by a PostgreSQL queue."""
    def __init__(self, repository: PostgresRunRepository,
                 execute: Callable[[dict], dict], *, poll_seconds: float = 1):
        self.repository = repository
        self.execute = execute
        self.poll_seconds = poll_seconds
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

        def heartbeat():
            while not finished.wait(5) and not self.stop_event.is_set():
                try:
                    if not self.repository.heartbeat(run_id, self.worker_id):
                        return
                except Exception:
                    logger.exception("Could not renew run heartbeat: run_id=%s", run_id)

        keeper = threading.Thread(target=heartbeat, daemon=True, name="aes-run-heartbeat")
        keeper.start()
        logger.info("Durable run started: run_id=%s user_id=%s", run_id, row["user_id"])
        response = None
        error = None
        try:
            with use_run_progress(lambda node, phase: self.repository.progress(
                run_id, self.worker_id, node, phase,
            )):
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
                    self.repository.finish(run_id, self.worker_id, status, response, error)
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
