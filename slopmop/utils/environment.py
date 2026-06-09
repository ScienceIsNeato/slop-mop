"""Environment and agent detection utilities for slop-mop."""

from __future__ import annotations

import os
import sys


def is_agent_environment() -> bool:
    """Return True if running inside an AI agent environment.

    Detects common agent CLI markers (Gemini, Claude, etc.) and CI.
    These environments usually prefer token-terse, machine-actionable
    output over rich animations and sparklines.
    """
    if os.environ.get("CI"):
        return True
    if os.environ.get("GEMINI_CLI"):
        return True
    if os.environ.get("CLAUDE_CODE"):
        return True
    if os.environ.get("AGENT_MODE"):
        return True
    # TERM_PROGRAM is often set by specialized terminal emulators or agents
    term_program = os.environ.get("TERM_PROGRAM", "")
    return term_program in ("Gemini", "ClaudeCode")


def is_interactive_terminal() -> bool:
    """Return True if stdout is a TTY and not an agent/CI environment."""
    if not sys.stdout.isatty():
        return False
    if is_agent_environment():
        return False
    return not os.environ.get("NO_COLOR")
