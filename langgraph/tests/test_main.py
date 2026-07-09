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

from aes_agent.main import ChatMessage, build_user_text_from_messages


class ChatHistoryInputTests(unittest.TestCase):
    def test_single_user_message_is_preserved(self):
        text = build_user_text_from_messages(
            [ChatMessage(role="user", content="Solve Poisson.")]
        )

        self.assertEqual(text, "Solve Poisson.")

    def test_multiple_user_messages_are_combined(self):
        text = build_user_text_from_messages(
            [
                ChatMessage(role="user", content="Solve a steady heat equation."),
                ChatMessage(role="assistant", content="Clarification needed."),
                ChatMessage(role="user", content="Use the weak formulation."),
            ]
        )

        self.assertIn("User message 1:", text)
        self.assertIn("Solve a steady heat equation.", text)
        self.assertIn("User message 2:", text)
        self.assertIn("Use the weak formulation.", text)
        self.assertNotIn("Clarification needed.", text)


if __name__ == "__main__":
    unittest.main()
