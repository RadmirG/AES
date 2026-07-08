import unittest

from aes_agent.mcp_client import parse_mcp_http_response


class MCPClientParsingTests(unittest.TestCase):
    def test_parses_json_rpc_response(self):
        message = parse_mcp_http_response(
            "application/json",
            '{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}',
        )

        self.assertEqual(message["result"], {"tools": []})

    def test_parses_sse_json_rpc_response(self):
        message = parse_mcp_http_response(
            "text/event-stream",
            'event: message\n'
            'data: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n',
        )

        self.assertEqual(message["result"], {"ok": True})


if __name__ == "__main__":
    unittest.main()
