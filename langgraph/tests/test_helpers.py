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


if __name__ == "__main__":
    unittest.main()
