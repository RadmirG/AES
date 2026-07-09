from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SMOKE_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "providers"
    / "fenics"
    / "smoke_tests"
    / "smoke_tools_list.py"
)

spec = importlib.util.spec_from_file_location("smoke_tools_list", SMOKE_SCRIPT)
smoke_tools_list = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(smoke_tools_list)


class FenicsSmokeParserTests(unittest.TestCase):
    def test_parses_plain_json_rpc_response(self):
        message = smoke_tools_list.parse_response(
            '{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}',
            content_type="application/json",
        )

        self.assertEqual(message["result"], {"tools": []})

    def test_parses_sse_response_with_event_before_data(self):
        message = smoke_tools_list.parse_response(
            'event: message\n'
            'data: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n',
            content_type="text/event-stream",
        )

        self.assertEqual(message["result"], {"ok": True})

    def test_reports_non_json_response(self):
        with self.assertRaisesRegex(RuntimeError, "non-JSON response"):
            smoke_tools_list.parse_response(
                "Not Found",
                content_type="text/plain",
            )


if __name__ == "__main__":
    unittest.main()
