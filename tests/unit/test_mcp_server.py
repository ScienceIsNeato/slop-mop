"""Tests for MCP server and CLI wiring."""

import argparse
import io
from pathlib import Path
from unittest.mock import patch

from slopmop.cli.mcp import cmd_mcp
from slopmop.mcp.server import (
    SwabMcpServer,
    _read_message,
    _write_message,
)


def test_initialize_returns_server_capabilities(tmp_path):
    server = SwabMcpServer(project_root=tmp_path)
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
    )
    assert response is not None
    assert response["result"]["serverInfo"]["name"] == "slop-mop"
    assert response["result"]["capabilities"] == {"tools": {}}


def test_tools_list_exposes_single_swab_tool(tmp_path):
    server = SwabMcpServer(project_root=tmp_path)
    response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert response is not None
    tools = response["result"]["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "swab"


def test_tools_call_runs_swab_and_returns_structured_content(tmp_path):
    server = SwabMcpServer(project_root=tmp_path)
    payload = {
        "summary": {
            "passed": 3,
            "failed": 0,
            "warned": 0,
            "errored": 0,
            "all_passed": True,
        }
    }
    with patch("slopmop.mcp.server._run_swab", return_value=(True, payload)):
        response = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "swab", "arguments": {}},
            }
        )
    assert response is not None
    result = response["result"]
    assert "content" in result
    assert result["structuredContent"] == payload
    assert result["content"][0]["type"] == "text"


def test_tools_call_unknown_tool_returns_rpc_error(tmp_path):
    server = SwabMcpServer(project_root=tmp_path)
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "bogus", "arguments": {}},
        }
    )
    assert response is not None
    assert response["error"]["code"] == -32602


def test_read_and_write_message_round_trip():
    payload = {"jsonrpc": "2.0", "id": 5, "result": {"ok": True}}
    out = io.BytesIO()
    _write_message(out, payload)
    out.seek(0)
    parsed = _read_message(out)
    assert parsed == payload


def test_cmd_mcp_requires_serve_action(capsys, tmp_path):
    args = argparse.Namespace(mcp_action=None, project_root=str(tmp_path))
    result = cmd_mcp(args)
    captured = capsys.readouterr()
    assert result == 2
    assert "Usage: sm mcp serve" in captured.out


def test_cmd_mcp_serve_invokes_server(tmp_path):
    args = argparse.Namespace(
        mcp_action="serve",
        project_root=str(tmp_path),
        allow_no_cache=False,
    )
    with patch("slopmop.cli.mcp.run_stdio_server", return_value=0) as run_server:
        result = cmd_mcp(args)
    assert result == 0
    run_server.assert_called_once_with(
        project_root=Path(tmp_path).resolve(),
        allow_no_cache=False,
    )
