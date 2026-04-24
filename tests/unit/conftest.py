"""Shared helpers for unit tests."""

from __future__ import annotations

from pathlib import Path


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
