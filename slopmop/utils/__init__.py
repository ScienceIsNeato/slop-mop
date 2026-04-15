"""Shared utility functions for slop-mop."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def iso_now() -> str:  # noqa: ambiguity-mine
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


_SLOPMOP_GITIGNORE_ENTRY = ".slopmop/"
_SLOPMOP_GITIGNORE_COMMENT = "# slop-mop working directory (machine-local state)"


def ensure_slopmop_gitignored(project_root: Path) -> bool:
    """Idempotently add ``.slopmop/`` to the project's ``.gitignore``.

    Returns ``True`` if the entry was added, ``False`` if it was already
    present or the line already appears in the file.
    """
    gitignore = project_root / ".gitignore"

    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            if stripped == _SLOPMOP_GITIGNORE_ENTRY:
                return False
        # Ensure we start on a new line
        if content and not content.endswith("\n"):
            content += "\n"
        content += f"\n{_SLOPMOP_GITIGNORE_COMMENT}\n{_SLOPMOP_GITIGNORE_ENTRY}\n"
        gitignore.write_text(content, encoding="utf-8")
    else:
        gitignore.write_text(
            f"{_SLOPMOP_GITIGNORE_COMMENT}\n{_SLOPMOP_GITIGNORE_ENTRY}\n",
            encoding="utf-8",
        )

    return True
