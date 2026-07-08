from __future__ import annotations

import json
import os
import sys
import urllib.request


REQUIRED_TOOLS = {
    "reset_session",
    "create_unit_square",
    "create_function_space",
    "set_material_properties",
    "define_variational_form",
    "apply_boundary_condition",
    "solve",
    "solve_time_dependent",
    "export_solution",
    "plot_solution",
    "generate_report",
}


class MCPHTTPClient:
    def __init__(self, url: str) -> None:
        self.url = url
        self.session_id = ""

    def request(
        self,
        request_id: int,
        method: str,
        params: dict | None = None,
    ) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        return self._post(payload)

    def notify(self, method: str, params: dict | None = None) -> None:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        self._post(payload)

    def _post(self, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        request = urllib.request.Request(
            self.url,
            data=data,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            session_id = response.headers.get("Mcp-Session-Id")
            if session_id:
                self.session_id = session_id
            text = response.read().decode("utf-8")
        return parse_response(text)


def parse_response(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("data:"):
        messages = [
            line.removeprefix("data:").strip()
            for line in stripped.splitlines()
            if line.strip().startswith("data:")
        ]
        messages = [message for message in messages if message and message != "[DONE]"]
        return json.loads(messages[-1]) if messages else {}
    return json.loads(stripped) if stripped else {}


def main() -> int:
    url = os.getenv("DOLFINX_MCP_URL", "http://127.0.0.1:8003/mcp")
    client = MCPHTTPClient(url)
    initialize = client.request(
        1,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "aes-fenics-smoke-test", "version": "0.1.0"},
        },
    )
    if "error" in initialize:
        print(json.dumps(initialize, indent=2))
        return 1

    client.notify("notifications/initialized")
    tools_response = client.request(2, "tools/list")
    if "error" in tools_response:
        print(json.dumps(tools_response, indent=2))
        return 1

    tools = tools_response.get("result", {}).get("tools", [])
    available = {tool.get("name") for tool in tools if isinstance(tool, dict)}
    missing = sorted(REQUIRED_TOOLS - available)
    if missing:
        print("Missing required tools:")
        print("\n".join(missing))
        return 1

    print(f"OK: {len(available)} MCP tools discovered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
