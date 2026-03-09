"""Tests for MCP server and CLI wiring."""

import argparse
import io
import subprocess
from pathlib import Path
from unittest.mock import patch

from slopmop.cli.mcp import cmd_mcp
from slopmop.mcp.server import (
    SwabMcpServer,
    _load_json_payload,
    _read_message,
    _run_swab,
    _write_message,
    run_stdio_server,
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


def test_tools_list_includes_no_cache_when_enabled(tmp_path):
    server = SwabMcpServer(project_root=tmp_path, allow_no_cache=True)
    response = server.handle({"jsonrpc": "2.0", "id": 20, "method": "tools/list"})
    assert response is not None
    tool = response["result"]["tools"][0]
    props = tool["inputSchema"]["properties"]
    assert "no_cache" in props


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


def test_tools_call_returns_is_error_when_swab_execution_fails(tmp_path):
    server = SwabMcpServer(project_root=tmp_path)
    with patch(
        "slopmop.mcp.server._run_swab",
        return_value=(False, {"error": "boom", "returncode": 2}),
    ):
        response = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 30,
                "method": "tools/call",
                "params": {"name": "swab", "arguments": {}},
            }
        )
    assert response is not None
    assert response["result"]["isError"] is True
    assert response["result"]["structuredContent"]["error"] == "boom"


def test_tools_call_forwards_no_cache_when_enabled(tmp_path):
    server = SwabMcpServer(project_root=tmp_path, allow_no_cache=True)
    with patch(
        "slopmop.mcp.server._run_swab",
        return_value=(True, {"summary": {"all_passed": True}}),
    ) as run_swab:
        response = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 31,
                "method": "tools/call",
                "params": {"name": "swab", "arguments": {"no_cache": True}},
            }
        )
    assert response is not None
    run_swab.assert_called_once_with(tmp_path, no_cache=True)


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


def test_tools_call_invalid_params_returns_rpc_error(tmp_path):
    server = SwabMcpServer(project_root=tmp_path)
    response = server.handle(
        {"jsonrpc": "2.0", "id": 40, "method": "tools/call", "params": "bad"}
    )
    assert response is not None
    assert response["error"]["code"] == -32602


def test_tools_call_requires_id_for_response(tmp_path):
    server = SwabMcpServer(project_root=tmp_path)
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "swab", "arguments": {}},
        }
    )
    assert response is None


def test_tools_call_requires_object_arguments(tmp_path):
    server = SwabMcpServer(project_root=tmp_path)
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 41,
            "method": "tools/call",
            "params": {"name": "swab", "arguments": []},
        }
    )
    assert response is not None
    assert response["error"]["code"] == -32602


def test_tools_call_rejects_unknown_arguments(tmp_path):
    server = SwabMcpServer(project_root=tmp_path, allow_no_cache=False)
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 42,
            "method": "tools/call",
            "params": {"name": "swab", "arguments": {"no_cache": True}},
        }
    )
    assert response is not None
    assert response["error"]["code"] == -32602
    assert "Unsupported tool argument" in response["error"]["message"]


def test_read_and_write_message_round_trip():
    payload = {"jsonrpc": "2.0", "id": 5, "result": {"ok": True}}
    out = io.BytesIO()
    _write_message(out, payload)
    out.seek(0)
    parsed = _read_message(out)
    assert parsed == payload


def test_read_message_returns_none_for_bad_headers():
    stream = io.BytesIO(b"Not-A-Header\r\n\r\n")
    assert _read_message(stream) is None


def test_read_message_returns_none_for_invalid_json():
    stream = io.BytesIO(b"{not-json\n")
    assert _read_message(stream) is None


def test_read_message_skips_invalid_lines_then_reads_valid_json():
    stream = io.BytesIO(
        b"not-json\n" b"\n" b'{"jsonrpc":"2.0","id":7,"method":"ping"}\n'
    )
    parsed = _read_message(stream)
    assert parsed is not None
    assert parsed["method"] == "ping"


def test_load_json_payload_fallback_line_parsing():
    noisy = 'log line\n{"summary":{"all_passed":true}}\n'
    parsed = _load_json_payload(noisy)
    assert parsed is not None
    assert parsed["summary"]["all_passed"] is True


def test_load_json_payload_returns_none_for_empty():
    assert _load_json_payload("  \n  ") is None


def test_run_swab_success_parses_json(tmp_path):
    mock_proc = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout='{"summary":{"all_passed":true}}',
        stderr="",
    )
    with patch("subprocess.run", return_value=mock_proc) as run_mock:
        ok, payload = _run_swab(tmp_path, no_cache=True)
    assert ok is True
    assert payload["summary"]["all_passed"] is True
    cmd = run_mock.call_args.args[0]
    assert "--no-cache" in cmd


def test_run_swab_returns_error_on_bad_json_output(tmp_path):
    mock_proc = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="not-json",
        stderr="oops",
    )
    with patch("subprocess.run", return_value=mock_proc):
        ok, payload = _run_swab(tmp_path)
    assert ok is False
    assert payload["error"] == "sm swab did not produce valid JSON output"


def test_run_swab_handles_oserror(tmp_path):
    with patch("subprocess.run", side_effect=OSError("nope")):
        ok, payload = _run_swab(tmp_path)
    assert ok is False
    assert "Failed to start swab" in payload["error"]


def test_run_swab_unexpected_exit_code_is_error(tmp_path):
    mock_proc = subprocess.CompletedProcess(
        args=[],
        returncode=2,
        stdout='{"summary":{"all_passed":false}}',
        stderr="bad",
    )
    with patch("subprocess.run", return_value=mock_proc):
        ok, payload = _run_swab(tmp_path)
    assert ok is False
    assert payload["returncode"] == 2


def test_cmd_mcp_requires_serve_action(capsys, tmp_path):
    args = argparse.Namespace(mcp_action=None, project_root=str(tmp_path))
    result = cmd_mcp(args)
    captured = capsys.readouterr()
    assert result == 2
    assert "Usage: sm mcp serve" in captured.out


def test_cmd_mcp_rejects_missing_project_root(capsys, tmp_path):
    args = argparse.Namespace(
        mcp_action="serve",
        project_root=str(tmp_path / "missing"),
        allow_no_cache=False,
    )
    result = cmd_mcp(args)
    captured = capsys.readouterr()
    assert result == 1
    assert "MCP project root not found" in captured.out


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


def test_handle_invalid_method_and_unknown_method(tmp_path):
    server = SwabMcpServer(project_root=tmp_path)
    no_method = server.handle({"jsonrpc": "2.0", "id": 50})
    assert no_method is not None
    assert no_method["error"]["code"] == -32600

    unknown = server.handle({"jsonrpc": "2.0", "id": 51, "method": "bogus"})
    assert unknown is not None
    assert unknown["error"]["code"] == -32601


def test_initialized_notification_and_ping_without_id_are_noops(tmp_path):
    server = SwabMcpServer(project_root=tmp_path)
    assert (
        server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    )
    assert server.handle({"jsonrpc": "2.0", "method": "ping"}) is None
    assert (
        server.handle({"jsonrpc": "2.0", "method": "initialize", "params": {}}) is None
    )


def test_shutdown_and_exit_flags(tmp_path):
    server = SwabMcpServer(project_root=tmp_path)
    shutdown = server.handle({"jsonrpc": "2.0", "id": 60, "method": "shutdown"})
    assert shutdown is not None
    assert server.should_exit is False

    exit_resp = server.handle({"jsonrpc": "2.0", "method": "exit"})
    assert exit_resp is None
    assert server.should_exit is True


def test_run_stdio_server_stops_on_exit(tmp_path):
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "exit"},
    ]

    with (
        patch("slopmop.mcp.server._read_message", side_effect=messages + [None]),
        patch("slopmop.mcp.server._write_message") as write_mock,
    ):
        result = run_stdio_server(project_root=tmp_path)

    assert result == 0
    assert write_mock.call_count == 1
