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

from aes_agent import helpers


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


if __name__ == "__main__":
    unittest.main()
