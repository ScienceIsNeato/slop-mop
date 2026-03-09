"""CLI entrypoint for MCP server commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from slopmop.mcp.server import run_stdio_server


def cmd_mcp(args: argparse.Namespace) -> int:
    """Handle `sm mcp` subcommands."""
    if getattr(args, "mcp_action", None) != "serve":
        print("Usage: sm mcp serve [--project-root PATH] [--allow-no-cache]")
        return 2

    project_root = Path(args.project_root).resolve()
    if not project_root.is_dir():
        print(f"❌ Project root not found: {project_root}")
        return 1

    return run_stdio_server(
        project_root=project_root,
        allow_no_cache=bool(getattr(args, "allow_no_cache", False)),
    )

