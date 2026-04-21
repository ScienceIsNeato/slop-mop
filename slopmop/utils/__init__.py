"""Shared utility functions for slop-mop."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional, cast


def iso_now() -> str:  # noqa: ambiguity-mine
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


_SLOPMOP_GITIGNORE_ENTRY = ".slopmop/"
_SLOPMOP_GITIGNORE_COMMENT = "# slop-mop working directory (machine-local state)"


def as_str_list(value: Any) -> list[str]:
    """Return string items from a config value, dropping non-strings."""
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in cast(list[object], value):
        if isinstance(item, str):
            result.append(item)
    return result


def normalize_path_filter(value: str) -> str:
    """Normalize a repo-relative path or glob from config/gitignore."""
    normalized = value.strip().replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.startswith("/"):
        normalized = normalized[1:]
    if normalized.endswith("/") and not normalized.endswith("/**"):
        normalized = normalized[:-1]
    return normalized


def _glob_match(path: str, pattern: str) -> bool:
    """Match a posix-style path against a glob pattern.

    Unlike ``fnmatch``, ``**`` is treated as a recursive wildcard that
    matches zero or more path components (e.g. ``**/*.snap`` matches both
    ``bar.snap`` at the root and ``foo/bar/baz.snap`` in subdirectories;
    ``vendor/**`` matches ``vendor/foo`` and ``vendor/foo/bar``).
    """
    if "**" not in pattern:
        return fnmatch(path, pattern)
    # Translate the glob to a regex character-by-character so that ** always
    # means "any characters including /" regardless of position.
    i = 0
    parts: list[str] = []
    while i < len(pattern):
        if pattern[i : i + 2] == "**":
            i += 2
            if i < len(pattern) and pattern[i] == "/":
                # **/ at the start/middle — matches zero or more dir components
                i += 1
                parts.append("(?:.+/)?")
            else:
                # trailing ** — matches anything remaining (including subdirs)
                parts.append(".*")
        elif pattern[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(pattern[i]))
            i += 1
    return bool(re.fullmatch("".join(parts), path))


def posix_relpath_to_path(posix_relpath: str) -> Path:
    """Convert a posix-style relative path string to a native OS ``Path``.

    ``pathlib`` accepts forward slashes on all platforms, so this is
    equivalent to ``Path(posix_relpath)`` but makes the conversion intent
    explicit and provides a single place to update if the approach changes.
    """
    return Path(posix_relpath)


def is_path_excluded(path: str | Path, raw_filters: Iterable[str]) -> bool:
    """Return whether a repo-relative path matches any exclude filter.

    Filters support:
    - plain directory tokens like ``vendor``
    - nested repo-relative paths like ``vendor/generated``
    - glob patterns like ``**/*.snap``
    """
    rel_path = normalize_path_filter(str(path))
    if not rel_path:
        return False

    rel_parts = PurePosixPath(rel_path).parts
    for raw_filter in raw_filters:
        normalized_filter = normalize_path_filter(raw_filter)
        if not normalized_filter:
            continue
        if any(ch in normalized_filter for ch in "*?[]"):
            if _glob_match(rel_path, normalized_filter):
                return True
            continue
        if "/" in normalized_filter:
            if rel_path == normalized_filter or rel_path.startswith(
                f"{normalized_filter}/"
            ):
                return True
            continue
        if normalized_filter in rel_parts:
            return True
    return False


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


def git_current_branch(path: Optional[str] = None) -> str:
    """Return the current git branch name, or ``"unknown"`` if it cannot be determined."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            cwd=path,
        )
        if result.returncode == 0:
            return result.stdout.strip() or "unknown"
    except Exception:
        pass
    return "unknown"


def dedupe_str_list(values: list[str]) -> list[str]:
    """Deduplicate strings while preserving input order."""
    return list(dict.fromkeys(values))
