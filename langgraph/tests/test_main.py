import sys
import types
import unittest


class _FastAPIStub:
    def __init__(self, *args, **kwargs):
        pass

    def get(self, *args, **kwargs):
        return lambda func: func

    def post(self, *args, **kwargs):
        return lambda func: func


class _BaseModelStub:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


fastapi_stub = types.ModuleType("fastapi")
fastapi_stub.FastAPI = _FastAPIStub
fastapi_stub.HTTPException = Exception
fastapi_responses_stub = types.ModuleType("fastapi.responses")
fastapi_responses_stub.FileResponse = object
fastapi_responses_stub.StreamingResponse = object
pydantic_stub = types.ModuleType("pydantic")
pydantic_stub.BaseModel = _BaseModelStub
graph_stub = types.ModuleType("aes_agent.graph")
graph_stub.graph = object()

sys.modules.setdefault("fastapi", fastapi_stub)
sys.modules.setdefault("fastapi.responses", fastapi_responses_stub)
sys.modules.setdefault("pydantic", pydantic_stub)
sys.modules.setdefault("requests", types.ModuleType("requests"))
sys.modules.setdefault("aes_agent.graph", graph_stub)

from aes_agent import main
from aes_agent.main import ChatMessage, build_user_text_from_messages


class _FakeGraph:
    def __init__(self):
        self.calls = 0

    def invoke(self, _state):
        self.calls += 1
        return {
            "generated_artifact": f"result {self.calls}",
            "agent_status": "ok",
            "next_action": "done",
        }


class ChatHistoryInputTests(unittest.TestCase):
    def test_single_user_message_is_preserved(self):
        text = build_user_text_from_messages(
            [ChatMessage(role="user", content="Solve Poisson.")]
        )

        self.assertEqual(text, "Solve Poisson.")

    def test_multiple_user_messages_use_latest_user_turn(self):
        text = build_user_text_from_messages(
            [
                ChatMessage(role="user", content="Solve a steady heat equation."),
                ChatMessage(role="assistant", content="Clarification needed."),
                ChatMessage(
                    role="user",
                    content=(
                        "docker compose -f deploy/compose.prod.yaml "
                        "--profile models up -d --build"
                    ),
                ),
            ]
        )

        self.assertEqual(
            text,
            "docker compose -f deploy/compose.prod.yaml --profile models up -d --build",
        )
        self.assertNotIn("Solve a steady heat equation.", text)

    def test_requested_output_reply_resumes_previous_pde_context(self):
        text = build_user_text_from_messages(
            [
                ChatMessage(
                    role="user",
                    content=(
                        "Consider the stationary heat equation -div(a grad u)=f "
                        "on a 2D rectangle with Dirichlet boundary conditions."
                    ),
                ),
                ChatMessage(
                    role="assistant",
                    content=(
                        "What output do you want from AES: a formulation summary, "
                        "a generated DOLFINx/FEniCS Python file, or execution with "
                        "stored result artifacts?"
                    ),
                ),
                ChatMessage(
                    role="user",
                    content="execution with stored result artifacts",
                ),
            ]
        )

        self.assertIn("stationary heat equation", text)
        self.assertIn("Requested AES output", text)
        self.assertIn("execute the generated", text)

    def test_duplicate_request_reuses_cached_result(self):
        fake_graph = _FakeGraph()
        main._RESULT_CACHE.clear()
        try:
            old_graph = main.graph
            main.graph = fake_graph

            first = main.run_aes_agent("Solve Poisson on the unit square.")
            second = main.run_aes_agent("Solve Poisson on the unit square.")

            self.assertEqual(fake_graph.calls, 1)
            self.assertEqual(first, second)
        finally:
            main.graph = old_graph
            main._RESULT_CACHE.clear()


if __name__ == "__main__":
    unittest.main()
