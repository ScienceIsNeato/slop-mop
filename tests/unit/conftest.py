"""Shared helpers for unit tests."""

from __future__ import annotations

from pathlib import Path

import pytest

_AGENT_ENV_VARS = ("CI", "GEMINI_CLI", "CLAUDE_CODE", "AGENT_MODE", "TERM_PROGRAM")


@pytest.fixture(autouse=True)
def _neutralize_agent_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unit tests deterministic regardless of where they run.

    sm auto-detects agent/CI environments and switches to terse/JSON output.
    Under GitHub Actions (CI=true) that would flip commands the tests exercise
    into JSON/non-interactive mode and break assertions written against human
    output. Clear the markers so every test starts from a human-output
    baseline; tests that exercise agent behavior re-set the vars they need.
    """
    for var in _AGENT_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def mk_python_project(root: Path) -> None:
    """Write a minimal pyproject.toml so doctor checks see a Python project."""
    (root / "pyproject.toml").write_text("[project]\nname='x'\n")


def mk_project_venv(root: Path) -> Path:
    """Create a minimal fake venv with a real ``bin/python`` entry.

    The file has to *exist* (``find_python_in_venv`` checks that) but
    doesn't need to be executable for most checks.  For ``pip check``
    tests we mock ``subprocess.run`` anyway.
    """
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    python = bin_dir / "python"
    python.write_text("#!/bin/false\n")
    return python
