"""Detect the Python formatter already configured by the host project.

Used by sloppy-formatting.py to defer to the project's own formatter
instead of imposing slop-mop's defaults (autoflake + black + isort).

When a project already pins ruff (or black), slop-mop running a different
formatter produces churn: the gate-fix commit ends up in a style that the
host's CI then immediately undoes. Detecting the host formatter and using
it keeps the output in sync with what CI expects.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


def detect_host_python_formatter(project_root: str) -> Optional[str]:
    """Return the formatter the project has configured, or None.

    Return values:
      'ruff'  — project configured ruff; use ``ruff format`` + ``ruff check``
      'black' — project configured black explicitly (no ruff)
      None    — no host formatter detected; caller should use defaults

    Detection priority:
      1. pyproject.toml [tool.ruff.*] → 'ruff'
      2. .ruff.toml or ruff.toml presence → 'ruff'
      3. .pre-commit-config.yaml containing a ruff hook → 'ruff'
      4. pyproject.toml [tool.black] (no ruff) → 'black'
      5. Nothing found → None
    """
    root = Path(project_root)

    # 1. pyproject.toml
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text(encoding="utf-8")
            # Matches [tool.ruff], [tool.ruff.format], [tool.ruff.lint], etc.
            if re.search(r"^\s*\[tool\.ruff[.\]]", content, re.MULTILINE):
                return "ruff"
            # Matches [tool.black] or [tool.black.*]
            if re.search(r"^\s*\[tool\.black[.\]]", content, re.MULTILINE):
                return "black"
        except OSError:
            pass  # Unreadable pyproject — fall through

    # 2. Standalone ruff config files
    if (root / ".ruff.toml").exists() or (root / "ruff.toml").exists():
        return "ruff"

    # 3. .pre-commit-config.yaml with a ruff hook
    precommit = root / ".pre-commit-config.yaml"
    if precommit.exists():
        try:
            content = precommit.read_text(encoding="utf-8")
            # astral-sh/ruff-pre-commit or any repo with 'ruff' as hook id
            if re.search(r"\bruff\b", content):
                return "ruff"
        except OSError:
            pass

    return None
