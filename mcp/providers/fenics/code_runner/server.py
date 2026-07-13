from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


SERVER_NAME = "aes-fenics-code-runner"
SERVER_VERSION = "0.1.0"
TOOL_NAME = "run_python_script"
DEFAULT_WORKSPACE = "/workspace"
DEFAULT_FILENAME = "solve.py"


class RpcError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class FenicsCodeRunnerHandler(BaseHTTPRequestHandler):
    server_version = f"{SERVER_NAME}/{SERVER_VERSION}"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "server": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
            )
            return

        self._send_json(
            404,
            {
                "error": "not_found",
                "message": "Use POST /mcp for JSON-RPC MCP requests.",
            },
        )

    def do_POST(self) -> None:
        if self.path != "/mcp":
            self._send_json(404, {"error": "not_found"})
            return

        try:
            payload = self._read_json()
            request_id = payload.get("id")
            method = str(payload.get("method", ""))
            params = payload.get("params") or {}
            if not isinstance(params, dict):
                raise RpcError(-32602, "JSON-RPC params must be an object.")

            if request_id is None:
                self._handle_notification(method)
                self.send_response(202)
                self.end_headers()
                return

            result = _handle_request(method, params)
            self._send_json(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result,
                },
            )
        except RpcError as exc:
            request_id = None
            if "payload" in locals() and isinstance(payload, dict):
                request_id = payload.get("id")
            self._send_json(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": exc.code,
                        "message": exc.message,
                    },
                },
            )
        except Exception as exc:
            self._send_json(
                500,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32603,
                        "message": f"Internal runner error: {exc}",
                    },
                },
            )

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(
            "%s [%s] %s\n"
            % (
                datetime.now(timezone.utc).isoformat(),
                self.address_string(),
                fmt % args,
            )
        )

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RpcError(-32700, f"Invalid JSON body: {exc}") from exc
        if not isinstance(payload, dict):
            raise RpcError(-32600, "JSON-RPC payload must be an object.")
        return payload

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_notification(self, method: str) -> None:
        if method == "notifications/initialized":
            return
        if not method:
            raise RpcError(-32600, "Notification method is required.")


def _handle_request(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "initialize":
        requested_protocol = str(params.get("protocolVersion", "2025-06-18"))
        return {
            "protocolVersion": requested_protocol,
            "capabilities": {
                "tools": {},
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
        }

    if method == "tools/list":
        return {
            "tools": [
                {
                    "name": TOOL_NAME,
                    "description": (
                        "Run a checked DOLFINx/FEniCS Python script in an "
                        "isolated provider workspace directory."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "required": ["code"],
                        "properties": {
                            "filename": {
                                "type": "string",
                                "default": DEFAULT_FILENAME,
                            },
                            "code": {
                                "type": "string",
                            },
                            "timeout_seconds": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": _max_timeout_seconds(),
                                "default": _default_timeout_seconds(),
                            },
                        },
                    },
                }
            ]
        }

    if method == "tools/call":
        name = str(params.get("name", ""))
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise RpcError(-32602, "Tool arguments must be an object.")
        if name != TOOL_NAME:
            raise RpcError(-32601, f"Unknown tool: {name}")
        return _run_python_script(arguments)

    raise RpcError(-32601, f"Unknown method: {method}")


def _run_python_script(arguments: dict[str, Any]) -> dict[str, Any]:
    code = str(arguments.get("code", ""))
    if not code.strip():
        return _failed_result(
            run_id="",
            run_dir="",
            message="Python code is empty.",
            errors=["Python code is empty."],
        )

    filename = _safe_filename(str(arguments.get("filename") or DEFAULT_FILENAME))
    timeout_seconds = _bounded_timeout(arguments.get("timeout_seconds"))
    workspace = _workspace_root()
    run_id = _build_run_id()
    run_dir = workspace / "code-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    script_path = run_dir / filename
    script_path.write_text(code, encoding="utf-8")

    env = os.environ.copy()
    env.setdefault("MPLBACKEND", "Agg")
    env.setdefault("PYTHONUNBUFFERED", "1")

    try:
        completed = subprocess.run(
            [sys.executable, filename],
            cwd=str(run_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        stdout = _truncate(completed.stdout)
        stderr = _truncate(completed.stderr)
        artifacts = _collect_artifacts(run_dir, run_id)
        diagnostics = {
            "return_code": completed.returncode,
            "timeout_seconds": timeout_seconds,
            "timed_out": False,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "artifact_count": len(artifacts),
        }
        if completed.returncode == 0:
            return {
                "schema_version": "1.0",
                "status": "completed",
                "message": "Python script executed successfully.",
                "run_id": run_id,
                "run_dir": str(run_dir),
                "stdout": stdout,
                "stderr": stderr,
                "diagnostics": diagnostics,
                "artifacts": artifacts,
                "errors": [],
                "warnings": [],
            }

        return {
            "schema_version": "1.0",
            "status": "failed",
            "message": f"Python script exited with code {completed.returncode}.",
            "run_id": run_id,
            "run_dir": str(run_dir),
            "stdout": stdout,
            "stderr": stderr,
            "diagnostics": diagnostics,
            "artifacts": artifacts,
            "errors": [
                stderr
                or f"Python script exited with code {completed.returncode}."
            ],
            "warnings": [],
        }
    except subprocess.TimeoutExpired as exc:
        stdout = _truncate(exc.stdout or "")
        stderr = _truncate(exc.stderr or "")
        artifacts = _collect_artifacts(run_dir, run_id)
        return {
            "schema_version": "1.0",
            "status": "failed",
            "message": f"Python script timed out after {timeout_seconds} seconds.",
            "run_id": run_id,
            "run_dir": str(run_dir),
            "stdout": stdout,
            "stderr": stderr,
            "diagnostics": {
                "return_code": None,
                "timeout_seconds": timeout_seconds,
                "timed_out": True,
                "run_id": run_id,
                "run_dir": str(run_dir),
                "artifact_count": len(artifacts),
            },
            "artifacts": artifacts,
            "errors": [f"Python script timed out after {timeout_seconds} seconds."],
            "warnings": [],
        }


def _failed_result(
    *,
    run_id: str,
    run_dir: str,
    message: str,
    errors: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "failed",
        "message": message,
        "run_id": run_id,
        "run_dir": run_dir,
        "stdout": "",
        "stderr": "",
        "diagnostics": {},
        "artifacts": [],
        "errors": errors,
        "warnings": [],
    }


def _workspace_root() -> Path:
    root = Path(os.getenv("FENICS_RUNNER_WORKSPACE", DEFAULT_WORKSPACE)).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_filename(value: str) -> str:
    name = Path(value).name.strip() or DEFAULT_FILENAME
    if not name.endswith(".py"):
        raise RpcError(-32602, "Script filename must end with .py.")
    return name


def _bounded_timeout(value: Any) -> int:
    try:
        requested = int(value)
    except (TypeError, ValueError):
        requested = _default_timeout_seconds()
    return max(1, min(requested, _max_timeout_seconds()))


def _default_timeout_seconds() -> int:
    return int(os.getenv("FENICS_RUNNER_DEFAULT_TIMEOUT", "300"))


def _max_timeout_seconds() -> int:
    return int(os.getenv("FENICS_RUNNER_MAX_TIMEOUT", "900"))


def _build_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:12]}"


def _collect_artifacts(run_dir: Path, run_id: str) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    max_files = int(os.getenv("FENICS_RUNNER_MAX_ARTIFACTS", "80"))
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(run_dir).as_posix()
        artifacts.append(
            {
                "name": rel,
                "kind": _artifact_kind(path.name),
                "status": "available",
                "uri": f"mcp://fenics-code-runner/workspace/code-runs/{run_id}/{rel}",
                "storage": "provider_workspace",
                "media_type": _media_type(path.name),
                "producer": {
                    "provider": "mcp:fenics-code-runner",
                    "tool_name": TOOL_NAME,
                },
                "metadata": {
                    "size_bytes": path.stat().st_size,
                },
            }
        )
        if len(artifacts) >= max_files:
            break
    return artifacts


def _artifact_kind(name: str) -> str:
    lowered = name.lower()
    if lowered.endswith(".py"):
        return "source_code"
    if lowered.endswith(".json"):
        return "diagnostics"
    if lowered.endswith(".png"):
        return "plot"
    if lowered.endswith(".xdmf") or lowered.endswith(".h5"):
        return "solution"
    return "artifact"


def _media_type(name: str) -> str:
    lowered = name.lower()
    if lowered.endswith(".py"):
        return "text/x-python"
    if lowered.endswith(".json"):
        return "application/json"
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".xdmf"):
        return "application/x-xdmf"
    if lowered.endswith(".h5"):
        return "application/x-hdf5"
    return "application/octet-stream"


def _truncate(value: str, limit: int | None = None) -> str:
    limit = limit or int(os.getenv("FENICS_RUNNER_CAPTURE_LIMIT", "20000"))
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def main() -> int:
    parser = argparse.ArgumentParser(description="AES FEniCS code runner MCP server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), FenicsCodeRunnerHandler)
    print(f"{SERVER_NAME} listening on http://{args.host}:{args.port}/mcp", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
