"""Minimal stdio MCP server exposing a single ``swab`` tool.

Design goals:
- Keep agent interface trivial: one tool, one action.
- Reuse the existing CLI execution path (``sm swab --json``).
- Avoid extra runtime dependencies so pipx installs remain frictionless.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, BinaryIO, Dict, Optional, cast

_JSONRPC_VERSION = "2.0"
_PROTOCOL_VERSION = "2024-11-05"
_SERVER_NAME = "slop-mop"
_TOOL_NAME = "swab"
try:
    _SERVER_VERSION = version("slopmop")
except PackageNotFoundError:
    _SERVER_VERSION = "0.0.0-dev"


def _rpc_result(request_id: object, result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "jsonrpc": _JSONRPC_VERSION,
        "id": request_id,
        "result": result,
    }


def _rpc_error(request_id: object, code: int, message: str) -> Dict[str, Any]:
    return {
        "jsonrpc": _JSONRPC_VERSION,
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _read_message(stdin: BinaryIO) -> Optional[Dict[str, Any]]:
    """Read one framed JSON-RPC message from stdio."""
    headers: Dict[str, str] = {}
    while True:
        line = stdin.readline()
        if line == b"":
            return None
        stripped = line.decode("utf-8", errors="replace").strip()
        if not stripped:
            break
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        headers[key.lower().strip()] = value.strip()

    length_raw = headers.get("content-length")
    if not length_raw:
        return None

    try:
        length = int(length_raw)
    except ValueError:
        return None
    if length <= 0:
        return None

    payload = stdin.read(length)
    if len(payload) != length:
        return None

    try:
        data = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError:
        return None

    if isinstance(data, dict):
        return cast(Dict[str, Any], data)
    return None


def _write_message(stdout: BinaryIO, payload: Dict[str, Any]) -> None:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii")
    stdout.write(header)
    stdout.write(raw)
    stdout.flush()


def _load_json_payload(raw_stdout: str) -> Optional[Dict[str, Any]]:
    """Parse CLI JSON output robustly.

    In normal operation the payload is a single JSON object line.
    As a fallback, parse line-by-line from the end in case wrapper noise
    appears in stdout.
    """
    text = raw_stdout.strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return cast(Dict[str, Any], parsed)
    except json.JSONDecodeError:
        pass

    lines = text.splitlines()
    for line in reversed(lines):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                return cast(Dict[str, Any], parsed)
        except json.JSONDecodeError:
            continue
    return None


def _run_swab(
    project_root: Path, no_cache: bool = False
) -> tuple[bool, Dict[str, Any]]:
    """Execute ``sm swab`` and return (ok, payload)."""
    cmd = [
        sys.executable,
        "-m",
        "slopmop",
        "swab",
        "--project-root",
        str(project_root),
        "--json",
        "--no-auto-fix",
    ]
    if no_cache:
        cmd.append("--no-cache")

    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return False, {"error": f"Failed to start swab: {exc}"}

    payload = _load_json_payload(proc.stdout)
    if payload is None:
        stderr = proc.stderr.strip()
        stdout = proc.stdout.strip()
        return (
            False,
            {
                "error": "sm swab did not produce valid JSON output",
                "returncode": proc.returncode,
                "stdout": stdout[-2000:],
                "stderr": stderr[-2000:],
            },
        )

    # swab returns 1 when gates fail, which is still a successful tool call.
    if proc.returncode in (0, 1):
        return True, payload

    return (
        False,
        {
            "error": "sm swab exited with an unexpected status",
            "returncode": proc.returncode,
            "payload": payload,
            "stderr": proc.stderr.strip()[-2000:],
        },
    )


@dataclass
class SwabMcpServer:
    """JSON-RPC request dispatcher for the slop-mop MCP server."""

    project_root: Path
    allow_no_cache: bool = False
    shutdown_requested: bool = False
    should_exit: bool = False

    def _tool_schema(self) -> Dict[str, Any]:
        properties: Dict[str, Any] = {}
        if self.allow_no_cache:
            properties["no_cache"] = {
                "type": "boolean",
                "default": False,
                "description": "Force a full cold swab run without cache.",
            }
        return {
            "name": _TOOL_NAME,
            "description": (
                "Run `sm swab` for this repository and return the standard "
                "slop-mop JSON payload."
            ),
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": properties,
            },
        }

    def _call_swab_tool(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        no_cache = False
        if self.allow_no_cache:
            no_cache = bool(arguments.get("no_cache", False))

        ok, payload = _run_swab(self.project_root, no_cache=no_cache)
        if not ok:
            return {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": payload.get("error", "Unknown swab execution error"),
                    }
                ],
                "structuredContent": payload,
            }

        summary_raw = payload.get("summary")
        summary: Dict[str, Any] = (
            cast(Dict[str, Any], summary_raw) if isinstance(summary_raw, dict) else {}
        )
        passed = int(summary.get("passed", 0) or 0)
        failed = int(summary.get("failed", 0) or 0)
        errored = int(summary.get("errored", 0) or 0)
        warned = int(summary.get("warned", 0) or 0)
        all_passed = bool(summary.get("all_passed", False))
        headline = (
            f"swab {'passed' if all_passed else 'found issues'} "
            f"(passed={passed}, failed={failed}, errored={errored}, warned={warned})"
        )

        return {
            "content": [{"type": "text", "text": headline}],
            "structuredContent": payload,
        }

    def handle(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method = request.get("method")
        request_id = request.get("id")
        has_id = "id" in request
        params_raw = request.get("params", {})

        if not isinstance(method, str):
            if has_id:
                return _rpc_error(request_id, -32600, "Invalid Request: missing method")
            return None

        if method == "initialize":
            client_version: Optional[str] = None
            if isinstance(params_raw, dict):
                protocol_raw = cast(Dict[str, Any], params_raw).get("protocolVersion")
                if isinstance(protocol_raw, str):
                    client_version = protocol_raw
            protocol_version = (
                client_version if isinstance(client_version, str) else _PROTOCOL_VERSION
            )
            return _rpc_result(
                request_id,
                {
                    "protocolVersion": protocol_version,
                    "serverInfo": {"name": _SERVER_NAME, "version": _SERVER_VERSION},
                    "capabilities": {"tools": {}},
                },
            )

        if method in {"notifications/initialized", "initialized"}:
            return None

        if method == "ping":
            if has_id:
                return _rpc_result(request_id, {})
            return None

        if method == "tools/list":
            if has_id:
                return _rpc_result(request_id, {"tools": [self._tool_schema()]})
            return None

        if method == "tools/call":
            if not has_id:
                return None
            if not isinstance(params_raw, dict):
                return _rpc_error(request_id, -32602, "Invalid params")
            params = cast(Dict[str, Any], params_raw)

            tool_name_raw = params.get("name")
            arguments_raw = params.get("arguments", {})
            tool_name: Optional[str] = (
                tool_name_raw if isinstance(tool_name_raw, str) else None
            )
            arguments: Optional[Dict[str, Any]] = (
                cast(Dict[str, Any], arguments_raw)
                if isinstance(arguments_raw, dict)
                else None
            )
            if not isinstance(tool_name, str):
                return _rpc_error(
                    request_id, -32602, "Invalid params: missing tool name"
                )
            if arguments is None:
                return _rpc_error(
                    request_id, -32602, "Invalid params: arguments must be an object"
                )
            if tool_name != _TOOL_NAME:
                return _rpc_error(request_id, -32602, f"Unknown tool: {tool_name}")

            result = self._call_swab_tool(arguments)
            return _rpc_result(request_id, result)

        if method == "shutdown":
            self.shutdown_requested = True
            if has_id:
                return _rpc_result(request_id, {})
            return None

        if method == "exit":
            self.should_exit = True
            return None

        if has_id:
            return _rpc_error(request_id, -32601, f"Method not found: {method}")
        return None


def run_stdio_server(project_root: Path, allow_no_cache: bool = False) -> int:
    """Run the MCP stdio loop until EOF or exit notification."""
    server = SwabMcpServer(project_root=project_root, allow_no_cache=allow_no_cache)
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    while True:
        message = _read_message(stdin)
        if message is None:
            break
        response = server.handle(message)
        if response is not None:
            _write_message(stdout, response)
        if server.should_exit:
            break

    return 0
