from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
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
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                session_id = response.headers.get("Mcp-Session-Id")
                if session_id:
                    self.session_id = session_id
                content_type = response.headers.get("Content-Type", "")
                text = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"MCP HTTP error {exc.code} from {self.url}: {preview(text)}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"MCP endpoint is not reachable: {self.url}") from exc

        return parse_response(text, content_type=content_type)


def preview(text: str, max_chars: int = 500) -> str:
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    return f"{stripped[:max_chars]}..."


def parse_response(text: str, content_type: str = "") -> dict:
    stripped = text.strip()
    if not stripped:
        return {}

    content_type = content_type.lower()
    if "text/event-stream" in content_type or any(
        line.strip().startswith("data:") for line in stripped.splitlines()
    ):
        return parse_sse_response(stripped)

    try:
        message = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "MCP server returned a non-JSON response. "
            f"Content-Type: {content_type or '<missing>'}. "
            f"Body preview: {preview(stripped)}"
        ) from exc

    if not isinstance(message, dict):
        raise RuntimeError("MCP server returned a non-object JSON response.")
    return message


def parse_sse_response(text: str) -> dict:
    messages = []
    for line in text.splitlines():
        stripped_line = line.strip()
        if stripped_line.startswith("data:"):
            messages.append(stripped_line.removeprefix("data:").strip())
    messages = [message for message in messages if message and message != "[DONE]"]
    if not messages:
        return {}

    try:
        message = json.loads(messages[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"MCP SSE response contained invalid JSON. Body preview: {preview(text)}"
        ) from exc

    if not isinstance(message, dict):
        raise RuntimeError("MCP SSE response contained a non-object payload.")
    return message


def main() -> int:
    url = os.getenv("DOLFINX_MCP_URL", "http://127.0.0.1:8003/mcp")
    client = MCPHTTPClient(url)
    try:
        initialize = client.request(
            1,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "aes-fenics-smoke-test", "version": "0.1.0"},
            },
        )
    except RuntimeError as exc:
        print(f"Smoke test failed during initialize: {exc}")
        return 1
    if "error" in initialize:
        print(json.dumps(initialize, indent=2))
        return 1

    try:
        client.notify("notifications/initialized")
        tools_response = client.request(2, "tools/list")
    except RuntimeError as exc:
        print(f"Smoke test failed during tools/list: {exc}")
        return 1
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
