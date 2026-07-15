from __future__ import annotations

import json
import logging
import time
from itertools import count
from typing import Any, Dict, List

from aes_agent.logging_config import log_content_preview


logger = logging.getLogger("aes_agent.mcp_client")


class MCPClientError(RuntimeError):
    """Raised when an MCP request fails or returns a protocol error."""


class StreamableHTTPMCPClient:
    """
    Minimal MCP client for streamable HTTP servers.

    The client intentionally implements only the methods AES needs for a first
    tool-provider layer: initialization, tool discovery, tool calls, and
    resource reads. It accepts both plain JSON-RPC responses and SSE-style
    responses containing JSON-RPC payloads in `data:` lines.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        timeout: int = 60,
        protocol_version: str = "2025-06-18",
    ) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self.protocol_version = protocol_version
        self._ids = count(1)
        self._initialized = False
        self._session_id = ""

    def initialize(self) -> Dict[str, Any]:
        logger.info(
            "MCP initialize requested: endpoint=%s protocol=%s",
            self.endpoint,
            self.protocol_version,
        )
        result = self._request(
            "initialize",
            {
                "protocolVersion": self.protocol_version,
                "capabilities": {},
                "clientInfo": {
                    "name": "aes-langgraph",
                    "version": "0.1.0",
                },
            },
        )
        self._initialized = True
        self._notify("notifications/initialized", {})
        logger.info(
            "MCP initialize completed: endpoint=%s session_id=%s",
            self.endpoint,
            self._session_id or "none",
        )
        return result

    def list_tools(self) -> List[Dict[str, Any]]:
        self._ensure_initialized()
        result = self._request("tools/list", {})
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            raise MCPClientError("MCP tools/list returned a non-list `tools` value.")
        logger.info(
            "MCP tools listed: endpoint=%s count=%s names=%s",
            self.endpoint,
            len(tools),
            [tool.get("name", "") for tool in tools if isinstance(tool, dict)],
        )
        return tools

    def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        self._ensure_initialized()
        logger.info(
            "MCP tool call requested: endpoint=%s tool=%s argument_keys=%s",
            self.endpoint,
            name,
            sorted((arguments or {}).keys()),
        )
        log_content_preview(
            logger,
            f"MCP tool call arguments: tool={name}",
            arguments or {},
        )
        return self._request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments or {},
            },
        )

    def read_resource(self, uri: str) -> Dict[str, Any]:
        self._ensure_initialized()
        return self._request("resources/read", {"uri": uri})

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            self.initialize()

    def _request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        started_at = time.perf_counter()
        payload = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": method,
            "params": params,
        }
        logger.info(
            "MCP JSON-RPC request started: endpoint=%s method=%s id=%s",
            self.endpoint,
            method,
            payload["id"],
        )
        log_content_preview(logger, f"MCP JSON-RPC payload: method={method}", payload)
        message = self._post(payload)

        if "error" in message:
            logger.warning(
                "MCP JSON-RPC request returned error: endpoint=%s method=%s error=%s",
                self.endpoint,
                method,
                message["error"],
            )
            raise MCPClientError(f"MCP error from {method}: {message['error']}")

        result = message.get("result", {})
        if not isinstance(result, dict):
            raise MCPClientError(f"MCP method {method} returned a non-object result.")
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.info(
            "MCP JSON-RPC request completed: endpoint=%s method=%s result_keys=%s elapsed_ms=%.1f",
            self.endpoint,
            method,
            sorted(result.keys()),
            elapsed_ms,
        )
        log_content_preview(logger, f"MCP JSON-RPC result: method={method}", result)
        return result

    def _notify(self, method: str, params: Dict[str, Any]) -> None:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        self._post(payload)

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import requests
        except Exception as exc:
            raise MCPClientError(
                "The `requests` package is required for MCP HTTP transport."
            ) from exc

        try:
            headers = {
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            }
            if self._session_id:
                headers["Mcp-Session-Id"] = self._session_id

            response = requests.post(
                self.endpoint,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning(
                "MCP HTTP request failed: endpoint=%s method=%s error=%s",
                self.endpoint,
                payload.get("method", ""),
                exc,
            )
            raise MCPClientError(f"MCP HTTP request failed: {exc}") from exc

        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id
        logger.info(
            "MCP HTTP response received: endpoint=%s method=%s status=%s content_type=%s chars=%s",
            self.endpoint,
            payload.get("method", ""),
            response.status_code,
            response.headers.get("content-type", ""),
            len(response.text),
        )

        return parse_mcp_http_response(
            content_type=response.headers.get("content-type", ""),
            text=response.text,
        )


def parse_mcp_http_response(content_type: str, text: str) -> Dict[str, Any]:
    content_type = content_type.lower()
    body = text.strip()
    if not body:
        return {}

    if "text/event-stream" in content_type:
        return _parse_sse_json_rpc(body)

    try:
        message = json.loads(body)
    except json.JSONDecodeError as exc:
        raise MCPClientError("MCP server returned invalid JSON.") from exc

    if not isinstance(message, dict):
        raise MCPClientError("MCP server returned a non-object JSON response.")
    return message


def _parse_sse_json_rpc(body: str) -> Dict[str, Any]:
    data_messages: List[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("data:"):
            continue
        data = stripped.removeprefix("data:").strip()
        if data and data != "[DONE]":
            data_messages.append(data)

    if not data_messages:
        return {}

    try:
        message = json.loads(data_messages[-1])
    except json.JSONDecodeError as exc:
        raise MCPClientError("MCP SSE response contained invalid JSON.") from exc

    if not isinstance(message, dict):
        raise MCPClientError("MCP SSE response contained a non-object payload.")
    return message
