import sys
import types
import unittest
from unittest.mock import Mock, patch

requests_stub = sys.modules.setdefault("requests", types.ModuleType("requests"))


class RequestException(Exception):
    pass


class Timeout(RequestException):
    pass


class HTTPError(RequestException):
    def __init__(self, *args, response=None):
        super().__init__(*args)
        self.response = response


requests_stub.exceptions = types.SimpleNamespace(
    RequestException=RequestException,
    Timeout=Timeout,
    HTTPError=HTTPError,
)
requests_stub.post = getattr(requests_stub, "post", Mock())

from aes_agent import helpers, model_client


class OllamaHelperTests(unittest.TestCase):
    @patch.object(helpers.requests, "post")
    def test_ollama_http_error_returns_empty_json(self, post):
        response = Mock()
        response.status_code = 404
        response.text = '{"error":"model not found"}'
        response.raise_for_status.side_effect = helpers.requests.exceptions.HTTPError(
            response=response
        )
        post.return_value = response

        result = helpers.ollama_json("Return JSON.")

        self.assertEqual(result, {})
        post.assert_called_once()

    @patch.object(helpers.requests, "post")
    def test_ollama_timeout_returns_empty_json(self, post):
        post.side_effect = helpers.requests.exceptions.Timeout("slow model")

        result = helpers.ollama_json("Return JSON.")

        self.assertEqual(result, {})
        post.assert_called_once()

    @patch.object(helpers.requests, "post")
    def test_ollama_json_passes_supplied_schema_as_format(self, post):
        response = Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {"response": '{"status":"ok"}'}
        post.return_value = response
        schema = {
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
        }

        with patch.object(model_client, "LLM_PROVIDER", "ollama"):
            result = helpers.ollama_json("Return JSON.", schema=schema)

        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(post.call_args.kwargs["json"]["format"], schema)

    @patch.object(helpers.requests, "post")
    def test_ollama_text_returns_raw_response_without_json_format(self, post):
        response = Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "response": "from dolfinx import fem\nprint('ok')\n",
            "done_reason": "stop",
        }
        post.return_value = response

        result = helpers.ollama_text("Return raw Python.")

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["text"].startswith("from dolfinx"))
        payload = post.call_args.kwargs["json"]
        self.assertNotIn("format", payload)

    @patch.object(helpers.requests, "post")
    def test_ollama_text_classifies_timeout(self, post):
        post.side_effect = helpers.requests.exceptions.Timeout("slow model")

        result = helpers.ollama_text("Return raw Python.")

        self.assertEqual(result["status"], "transport_timeout")
        self.assertEqual(result["text"], "")


class VllmModelClientTests(unittest.TestCase):
    @patch.object(model_client.requests, "post")
    def test_vllm_json_uses_openai_chat_completions(self, post):
        response = Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [
                {
                    "message": {"content": '{"problem_class":"forward_problem"}'},
                    "finish_reason": "stop",
                }
            ]
        }
        post.return_value = response

        with patch.multiple(
            model_client,
            LLM_PROVIDER="vllm",
            LLM_BASE_URL="http://127.0.0.1:8000/v1",
            LLM_MODEL="aes-engineering-model",
            LLM_API_KEY="test-api-key",
        ):
            result = model_client.llm_json("Return JSON.")

        self.assertEqual(result["problem_class"], "forward_problem")
        self.assertEqual(
            post.call_args.args[0],
            "http://127.0.0.1:8000/v1/chat/completions",
        )
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "aes-engineering-model")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer test-api-key",
        )

    @patch.object(model_client.requests, "post")
    def test_vllm_json_uses_supplied_json_schema(self, post):
        response = Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [
                {
                    "message": {"content": '{"status":"ok"}'},
                    "finish_reason": "stop",
                }
            ]
        }
        post.return_value = response
        schema = {
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
        }

        with patch.multiple(
            model_client,
            LLM_PROVIDER="vllm",
            LLM_BASE_URL="http://127.0.0.1:8000/v1",
            LLM_MODEL="aes-engineering-model",
        ):
            result = model_client.llm_json("Return JSON.", schema=schema)

        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(
            post.call_args.kwargs["json"]["response_format"],
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "aes_structured_response",
                    "strict": True,
                    "schema": schema,
                },
            },
        )

    @patch.object(model_client.requests, "post")
    def test_vllm_text_returns_transport_metadata(self, post):
        response = Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [
                {
                    "message": {"content": "print('ready')\n"},
                    "finish_reason": "stop",
                }
            ]
        }
        post.return_value = response

        with patch.multiple(
            model_client,
            LLM_PROVIDER="vllm",
            LLM_BASE_URL="http://aes-vllm:8000",
            LLM_MODEL="aes-engineering-model",
            LLM_API_KEY="",
        ):
            result = model_client.llm_text("Return raw Python.")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["provider"], "vllm")
        self.assertEqual(result["text"], "print('ready')\n")
        self.assertEqual(
            post.call_args.args[0],
            "http://aes-vllm:8000/v1/chat/completions",
        )
        self.assertNotIn("response_format", post.call_args.kwargs["json"])


if __name__ == "__main__":
    unittest.main()
