import sys
import types
import unittest
from datetime import datetime, timezone
from unittest.mock import patch


class _FastAPIStub:
    def __init__(self, *args, **kwargs):
        pass

    def add_middleware(self, *args, **kwargs):
        return None

    def get(self, *args, **kwargs):
        return lambda func: func

    def post(self, *args, **kwargs):
        return lambda func: func


class _BaseModelStub:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _HTTPExceptionStub(Exception):
    def __init__(self, *, status_code, detail, headers=None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.headers = headers or {}


fastapi_stub = types.ModuleType("fastapi")
fastapi_stub.FastAPI = _FastAPIStub
fastapi_stub.HTTPException = _HTTPExceptionStub
fastapi_stub.Request = object
fastapi_stub.Response = object
fastapi_middleware_stub = types.ModuleType("fastapi.middleware")
fastapi_cors_stub = types.ModuleType("fastapi.middleware.cors")
fastapi_cors_stub.CORSMiddleware = object
fastapi_responses_stub = types.ModuleType("fastapi.responses")
fastapi_responses_stub.FileResponse = object
fastapi_responses_stub.StreamingResponse = object
pydantic_stub = types.ModuleType("pydantic")
pydantic_stub.BaseModel = _BaseModelStub
graph_stub = types.ModuleType("aes_agent.graph")
graph_stub.graph = object()

sys.modules.setdefault("fastapi", fastapi_stub)
sys.modules.setdefault("fastapi.middleware", fastapi_middleware_stub)
sys.modules.setdefault("fastapi.middleware.cors", fastapi_cors_stub)
sys.modules.setdefault("fastapi.responses", fastapi_responses_stub)
sys.modules.setdefault("pydantic", pydantic_stub)
sys.modules.setdefault("requests", types.ModuleType("requests"))
sys.modules.setdefault("aes_agent.graph", graph_stub)

from aes_agent import main
from aes_agent.auth import AuthUser, CookieSettings, LoginResult
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


class _FakeRequest:
    def __init__(self, *, cookies=None):
        self.cookies = cookies or {}
        self.headers = {}
        self.client = types.SimpleNamespace(host="127.0.0.1")


class _FakeResponse:
    def __init__(self):
        self.headers = {}
        self.cookie = None
        self.deleted_cookie = None

    def set_cookie(self, **kwargs):
        self.cookie = kwargs

    def delete_cookie(self, **kwargs):
        self.deleted_cookie = kwargs


class _FakeAuthService:
    def __init__(self):
        self.user = AuthUser(
            id="user-1",
            username="engineer",
            display_name="AES Engineer",
            status="active",
            created_at=datetime.now(timezone.utc),
        )
        self.logged_out_token = ""

    def login(self, **_kwargs):
        return LoginResult(
            user=self.user,
            session_token="raw-session-token",
            expires_at=datetime.now(timezone.utc),
        )

    def authenticate_session(self, token):
        return self.user if token == "raw-session-token" else None

    def logout(self, token):
        self.logged_out_token = token


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

    def test_duplicate_request_cache_is_isolated_by_user(self):
        fake_graph = _FakeGraph()
        main._RESULT_CACHE.clear()
        try:
            old_graph = main.graph
            main.graph = fake_graph

            first = main.run_aes_agent(
                "Solve Poisson on the unit square.",
                cache_scope="user-1",
            )
            second = main.run_aes_agent(
                "Solve Poisson on the unit square.",
                cache_scope="user-2",
            )

            self.assertEqual(fake_graph.calls, 2)
            self.assertNotEqual(first, second)
        finally:
            main.graph = old_graph
            main._RESULT_CACHE.clear()


class AuthenticationApiTests(unittest.TestCase):
    def setUp(self):
        self.service = _FakeAuthService()
        self.settings = CookieSettings(
            name="aes_session",
            secure=False,
            same_site="lax",
            ttl_seconds=3600,
        )

    def test_login_sets_http_only_cookie(self):
        response = _FakeResponse()
        with patch.object(main, "get_auth_service", return_value=self.service), patch.object(
            main,
            "cookie_settings",
            return_value=self.settings,
        ):
            result = main.login(
                main.LoginRequest(username="engineer", password="secret-value"),
                _FakeRequest(),
                response,
            )

        self.assertEqual(result["user"]["id"], "user-1")
        self.assertEqual(response.cookie["value"], "raw-session-token")
        self.assertTrue(response.cookie["httponly"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_me_rejects_missing_session(self):
        with patch.object(main, "auth_enabled", return_value=True), patch.object(
            main,
            "cookie_settings",
            return_value=self.settings,
        ):
            with self.assertRaises(_HTTPExceptionStub) as raised:
                main.current_user(_FakeRequest(), _FakeResponse())

        self.assertEqual(raised.exception.status_code, 401)

    def test_logout_revokes_session_and_deletes_cookie(self):
        response = _FakeResponse()
        with patch.object(main, "get_auth_service", return_value=self.service), patch.object(
            main,
            "cookie_settings",
            return_value=self.settings,
        ):
            result = main.logout(
                _FakeRequest(cookies={"aes_session": "raw-session-token"}),
                response,
            )

        self.assertEqual(result["status"], "logged_out")
        self.assertEqual(self.service.logged_out_token, "raw-session-token")
        self.assertEqual(response.deleted_cookie["key"], "aes_session")


if __name__ == "__main__":
    unittest.main()
