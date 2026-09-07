"""Real FastAPI + LangGraph smoke check, isolated from legacy module stubs."""
import threading
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from langgraph.graph import StateGraph, END

from aes_agent import main
from aes_agent.auth import AuthUser
from aes_agent.graph import _logged_node
from aes_agent.state import AgentState
from test_runs import MemoryRunRepository


class Repository(MemoryRunRepository):
    def __init__(self):
        super().__init__()
        self.row["status"] = "unsubmitted"
        self.row["user_id"] = "809119d9-37c7-4834-8e9f-8d65a4f2b7ed"
        self.created = 0

    def get(self, run_id, user_id):
        if self.row["status"] == "unsubmitted": return None
        return super().get(run_id, user_id)

    def create(self, run_id, user_id, conversation_id, fingerprint, request):
        self.created += 1
        self.row.update(id=run_id, user_id=user_id, conversation_id=conversation_id,
                        request_fingerprint=fingerprint, request=request, status="queued")
        return self.get(run_id, user_id)


repository = Repository()
started = threading.Event()
release = threading.Event()
calls = []


def step(state):
    calls.append(state)
    started.set()
    assert release.wait(5), "test did not release graph"
    return {"generated_artifact": "Solved on L shape", "agent_status": "ok", "next_action": "review_tool_results"}


builder = StateGraph(AgentState)
builder.add_node("interpret_typed_specs", _logged_node("interpret_typed_specs", step))
builder.set_entry_point("interpret_typed_specs")
builder.add_edge("interpret_typed_specs", END)
user = AuthUser(repository.row["user_id"], "engineer", "Engineer", "active", datetime.now(timezone.utc))
payload = {
    "run_id": repository.row["id"], "conversation_id": "chat-1", "model": "aes-agent",
    "backend_model": "qwen3:8b", "messages": [{"role": "user", "content": "Solve Laplace on L shape"}],
    "geometry_spec": {"metadata": {"name": "L shape"}},
}

with patch.object(main, "auth_enabled", return_value=True), patch.object(
    main, "require_authenticated_user", return_value=user,
), patch.object(main, "get_run_repository", return_value=repository), patch.object(
    main, "_resolve_backend_model", return_value="qwen3:8b",
), patch.object(main, "graph", builder.compile()):
    main._RESULT_CACHE.clear()
    with TestClient(main.app) as browser:
        accepted = browser.post("/api/runs", json=payload)
        assert accepted.status_code == 202, accepted.text
        assert started.wait(3)
        duplicate = browser.post("/api/runs", json=payload)
        assert duplicate.status_code == 202
        assert repository.created == 1
        # A separate browser client reconnects to the already executing job.
        refreshed = TestClient(main.app)
        running = refreshed.get(f"/api/runs/{payload['run_id']}")
        assert running.status_code == 200
        assert running.json()["status"] == "running"
        assert running.json()["progress"][0]["node"] == "interpret_typed_specs"
        release.set()
        assert repository.finished.wait(3)
        result = refreshed.get(f"/api/runs/{payload['run_id']}")
        assert result.json()["status"] == "completed", result.text
        assert "Solved on L shape" in result.json()["response"]["choices"][0]["message"]["content"]
        assert len(calls) == 1
        assert calls[0]["requested_geometry_spec"] == payload["geometry_spec"]
        assert result.headers["cache-control"] == "no-store"
        refreshed.close()

print("Real HTTP acceptance, duplicate protection, background execution, LangGraph progress context, and refresh recovery passed.")
