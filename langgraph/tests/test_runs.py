import copy
import threading
import os
import subprocess
import sys
from pathlib import Path
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from aes_agent.run_progress import report_progress
from aes_agent.runs import RunWorker, RunStoreUnavailable, public_run, request_fingerprint


class MemoryRunRepository:
    """Thread-safe fake for browser/worker recovery scenarios."""
    def __init__(self):
        self.lock = threading.Lock()
        self.row = {
            "id": "b758c346-77b0-46d2-902b-ddbd947cbd19",
            "user_id": "engineer", "conversation_id": "chat-1",
            "status": "queued", "progress": [], "response": None,
            "request": {"backend_model": "qwen3:8b", "geometry_spec": {"dimension": 2}},
            "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
        }
        self.finished = threading.Event()

    def get(self, run_id, user_id):
        with self.lock:
            return copy.deepcopy(self.row) if self.row["id"] == run_id and self.row["user_id"] == user_id else None

    def claim(self, worker_id):
        with self.lock:
            if self.row["status"] != "queued": return None
            self.row.update(status="running", worker_id=worker_id)
            return copy.deepcopy(self.row)

    def heartbeat(self, run_id, worker_id):
        return self.row.get("worker_id") == worker_id and self.row["status"] == "running"

    def expire_abandoned(self):
        pass

    def progress(self, run_id, worker_id, node, phase):
        self.row["progress"].append({"node": node, "phase": phase})

    def finish(self, run_id, worker_id, status, response, error):
        with self.lock:
            self.row.update(status=status, response=response, error=error)
        self.finished.set()
        return True


class RunRecoveryTests(unittest.TestCase):
    def test_real_http_and_langgraph_recovery(self):
        root = Path(__file__).resolve().parents[1]
        environment = {**os.environ, "PYTHONPATH": str(root), "AES_LOG_CONTENT": "false"}
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("run_api_smoke.py"))],
            cwd=root, env=environment, text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_refresh_and_second_worker_do_not_repeat_execution(self):
        repository = MemoryRunRepository()
        started = threading.Event()
        release = threading.Event()
        response = {"choices": [{"message": {"content": "solved"}}], "aes_result": {"agent_status": "ok"}}

        def execute(row):
            started.set()
            report_progress("interpret_typed_specs", "started")
            if not release.wait(3): raise RuntimeError("test release timed out")
            report_progress("interpret_typed_specs", "finished")
            return response

        execute = Mock(side_effect=execute)
        workers = [RunWorker(repository, execute, poll_seconds=0.01) for _ in range(2)]
        for worker in workers: worker.start()
        try:
            self.assertTrue(started.wait(2))
            first_browser = repository.get(repository.row["id"], "engineer")
            refreshed_browser = repository.get(repository.row["id"], "engineer")
            self.assertEqual(first_browser["status"], "running")
            self.assertEqual(refreshed_browser["id"], first_browser["id"])
            self.assertIsNone(repository.get(repository.row["id"], "another-user"))
            release.set()
            self.assertTrue(repository.finished.wait(2))
            # The response remains retrievable long after the old 10s cache.
            repository.row["created_at"] -= timedelta(hours=12)
            self.assertEqual(public_run(repository.get(repository.row["id"], "engineer"))["response"], response)
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(repository.row["progress"][-1]["phase"], "finished")
        finally:
            release.set()
            for worker in workers: worker.stop()

    def test_execution_exception_is_saved_as_failure(self):
        repository = MemoryRunRepository()
        worker = RunWorker(repository, Mock(side_effect=ValueError("internal secret detail")))
        worker.execute_claimed(repository.claim(worker.worker_id))
        self.assertEqual(repository.row["status"], "failed")
        self.assertNotIn("secret", repository.row["error"])

    def test_tool_error_keeps_final_response_and_artifact_links(self):
        repository = MemoryRunRepository()
        response = {"aes_result": {"agent_status": "tool_error", "tool_results": [{"tool_name": "artifact_store"}]}}
        worker = RunWorker(repository, lambda row: response)
        worker.execute_claimed(repository.claim(worker.worker_id))
        self.assertEqual(repository.row["status"], "failed")
        self.assertEqual(repository.row["response"], response)

    def test_result_write_retry_does_not_repeat_graph(self):
        repository = MemoryRunRepository()
        finish = repository.finish
        calls = []

        def temporary_outage(*args):
            calls.append(args)
            if len(calls) == 1: raise RunStoreUnavailable("temporary outage")
            return finish(*args)

        repository.finish = temporary_outage
        execute = Mock(return_value={"aes_result": {"agent_status": "ok"}})
        worker = RunWorker(repository, execute)
        worker.execute_claimed(repository.claim(worker.worker_id))
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(repository.row["status"], "completed")
        self.assertEqual(len(calls), 2)

    def test_request_fingerprint_includes_model_geometry_and_conversation(self):
        request = {"conversation_id": "chat-1", "backend_model": "qwen3:8b", "geometry_spec": {"dimension": 2}}
        original = request_fingerprint(request)
        self.assertEqual(original, request_fingerprint(dict(reversed(list(request.items())))))
        for key, value in [("conversation_id", "chat-2"), ("backend_model", "gemma4:31b"), ("geometry_spec", {"dimension": 3})]:
            self.assertNotEqual(original, request_fingerprint({**request, key: value}))

    def test_heartbeat_recovers_without_reexecuting_graph(self):
        repository = MemoryRunRepository()
        renewed = threading.Event()
        attempts = []

        def heartbeat(*args):
            attempts.append(args)
            if len(attempts) <= 2:
                raise RunStoreUnavailable("temporary connection timeout")
            renewed.set()
            return True

        def execute(row):
            self.assertTrue(renewed.wait(2), "heartbeat did not recover")
            return {"aes_result": {"agent_status": "ok"}}

        repository.heartbeat = heartbeat
        execute = Mock(side_effect=execute)
        worker = RunWorker(repository, execute, heartbeat_seconds=0.01)
        with self.assertLogs("aes_agent.runs", level="INFO") as logs:
            worker.execute_claimed(repository.claim(worker.worker_id))
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(repository.row["status"], "completed")
        self.assertTrue(any("heartbeat delayed" in entry for entry in logs.output))
        self.assertTrue(any("heartbeat recovered" in entry for entry in logs.output))
        self.assertFalse(any("ERROR" in entry for entry in logs.output))

    def test_progress_failure_is_buffered_and_does_not_fail_execution(self):
        repository = MemoryRunRepository()
        persist_progress = repository.progress
        attempts = []

        def progress(*args):
            attempts.append(args)
            if len(attempts) == 1:
                raise RunStoreUnavailable("temporary connection timeout")
            persist_progress(*args)

        def execute(row):
            report_progress("execute_tools", "started")
            report_progress("execute_tools", "finished")
            return {"aes_result": {"agent_status": "ok"}}

        repository.progress = progress
        execute = Mock(side_effect=execute)
        worker = RunWorker(repository, execute)
        worker.execute_claimed(repository.claim(worker.worker_id))
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(repository.row["status"], "completed")
        self.assertEqual(repository.row["progress"], [{"node": "execute_tools", "phase": "finished"}])

    def test_worker_does_not_report_saved_result_after_lease_loss(self):
        repository = MemoryRunRepository()
        repository.finish = Mock(return_value=False)
        worker = RunWorker(repository, lambda row: {"aes_result": {"agent_status": "ok"}})
        with self.assertLogs("aes_agent.runs", level="INFO") as logs:
            worker.execute_claimed(repository.claim(worker.worker_id))
        repository.finish.assert_called_once()
        self.assertTrue(any("Run result was not saved" in entry for entry in logs.output))
        self.assertFalse(any("Durable run finished" in entry for entry in logs.output))
