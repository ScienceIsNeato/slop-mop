"""Fingerprint-based result cache for quality gate checks.

When source files and configuration haven't changed between runs,
re-running every check from scratch is wasted work.  This module
computes a project-wide fingerprint (based on file modification times
and config content) and caches check results keyed by that fingerprint.

On a cache hit the executor returns the stored result instantly,
making back-to-back ``sm swab`` runs take virtually zero time.

Cache location: ``.slopmop/cache.json`` (separate from timings.json).

Design decisions:
- **Project-wide fingerprint**: One fingerprint covers all checks.
  If *any* source file changes, all caches invalidate.  Conservative
  but cheap and always correct.
- **ERROR results are not cached**: Errors are often transient (missing
  tool, network issue) and should be retried.
- **auto_fixed results are not cached**: Auto-fix is a side effect;
  caching would skip the fix on the next run.
"""

import hashlib
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, cast

from slopmop.core.result import CheckResult, CheckStatus

logger = logging.getLogger(__name__)

CACHE_DIR = ".slopmop"
CACHE_FILE = "cache.json"

# Directories to skip when computing the source fingerprint.
# Same as SCOPE_EXCLUDED_DIRS in checks/base.py — no point hashing
# node_modules, .git, or build artifacts.
_EXCLUDED_DIRS = {
    "node_modules",
    ".git",
    "venv",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    ".tox",
    "htmlcov",
    "cursor-rules",
    ".mypy_cache",
    "logs",
    ".slopmop",
    ".egg-info",
    "slopmop.egg-info",
}

# Source extensions to include in the fingerprint.
_SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".cfg",
    ".ini",
    ".sh",
    ".bash",
}


def _cache_path(project_root: str) -> Path:
    return Path(project_root) / CACHE_DIR / CACHE_FILE


def hash_file_scope(
    project_root: str,
    dirs: list[str],
    extensions: set[str],
    config: Dict[str, Any],
    exclude_dirs: Optional[set[str]] = None,
) -> str:
    """Compute a fingerprint scoped to specific directories and extensions.

    Used by checks that override ``BaseCheck.cache_inputs()`` to declare
    a narrow input scope.  Only files matching *dirs* and *extensions*
    contribute to the hash, so edits outside this scope won't invalidate
    the check's cache.

    Args:
        project_root: Project root directory.
        dirs: Directories to scan (relative to root, e.g. ``["slopmop"]``).
        extensions: File extensions to include (e.g. ``{".py"}``).
        config: Check-specific config dict — hashed so config changes
            also invalidate the cache.
        exclude_dirs: Extra directories to exclude (merged with the
            module-level ``_EXCLUDED_DIRS``).

    Returns:
        Hex digest string.
    """
    hasher = hashlib.sha256()
    root = Path(project_root)
    excluded = _EXCLUDED_DIRS | (exclude_dirs or set())

    # 1. Hash the check config so config changes invalidate
    hasher.update(b"config:")
    hasher.update(json.dumps(config, sort_keys=True).encode())

    # 2. Collect (relative_path, mtime) for files in scope
    entries: list[tuple[str, int]] = []
    for dir_name in dirs:
        scan_path = root / dir_name
        if not scan_path.exists():
            continue

        for file_path in scan_path.rglob("*"):
            if not file_path.is_file():
                continue

            try:
                rel = file_path.relative_to(root)
            except ValueError:
                continue

            parts = rel.parts
            if any(p in excluded or ".egg-info" in p for p in parts):
                continue

            if file_path.suffix not in extensions:
                continue

            try:
                mtime = file_path.stat().st_mtime_ns
                entries.append((str(rel), mtime))
            except OSError:
                continue

    entries.sort()
    for rel_path, mtime in entries:
        hasher.update(f"{rel_path}:{mtime}\n".encode())

    return hasher.hexdigest()


def compute_fingerprint(project_root: str) -> str:
    """Compute a project-wide fingerprint from source file mtimes and config.

    The fingerprint changes whenever:
    - Any source file is created, modified, or deleted
    - .sb_config.json changes

    Returns a hex digest string.
    """
    hasher = hashlib.sha256()
    root = Path(project_root)

    # 1. Hash .sb_config.json content (if it exists)
    config_path = root / ".sb_config.json"
    if config_path.exists():
        try:
            config_bytes = config_path.read_bytes()
            hasher.update(b"config:")
            hasher.update(config_bytes)
        except OSError:
            hasher.update(b"config:unreadable")
    else:
        hasher.update(b"config:missing")

    # 2. Collect (relative_path, mtime) for all source files, sorted
    entries: list[tuple[str, int]] = []
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue

        # Skip excluded directories
        try:
            rel = file_path.relative_to(root)
        except ValueError:
            continue

        parts = rel.parts
        if any(p in _EXCLUDED_DIRS or ".egg-info" in p for p in parts):
            continue

        if file_path.suffix not in _SOURCE_EXTENSIONS:
            continue

        try:
            mtime = file_path.stat().st_mtime_ns
            entries.append((str(rel), mtime))
        except OSError:
            continue

    # Sort for deterministic ordering
    entries.sort()

    # Hash each entry
    for rel_path, mtime in entries:
        hasher.update(f"{rel_path}:{mtime}\n".encode())

    return hasher.hexdigest()


def load_cache(project_root: str) -> Dict[str, Any]:
    """Load the cache file, returning an empty dict on any error."""
    path = _cache_path(project_root)
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return cast(Dict[str, Any], data)
        return {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(project_root: str, cache: Dict[str, Any]) -> None:
    """Write the cache dict to disk."""
    path = _cache_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w") as f:
            json.dump(cache, f, indent=2)
    except OSError as e:
        logger.debug(f"Failed to write cache: {e}")


def get_cached_result(
    cache: Dict[str, Any],
    check_name: str,
    fingerprint: str,
) -> Optional[CheckResult]:
    """Return cached CheckResult if fingerprint matches, else None."""
    entry = cache.get(check_name)
    if not isinstance(entry, dict):
        return None
    entry_d = cast(Dict[str, Any], entry)
    if entry_d.get("fingerprint") != fingerprint:
        return None
    result_dict = entry_d.get("result")
    if not isinstance(result_dict, dict):
        return None
    try:
        result = CheckResult.from_dict(cast(Dict[str, Any], result_dict))
        result.duration = 0.0
        result.cached = True
        result.cache_timestamp = entry_d.get("timestamp")
        result.cache_commit = entry_d.get("commit")
        return result
    except Exception:
        return None


def _get_head_short(project_root: Optional[str] = None) -> Optional[str]:
    """Return the short (7-char) HEAD commit hash, or None on failure."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def store_result(
    cache: Dict[str, Any],
    check_name: str,
    fingerprint: str,
    result: CheckResult,
    project_root: Optional[str] = None,
) -> None:
    """Store a check result in the cache dict (call save_cache to persist).

    Skips ERROR results (transient) and auto_fixed results (side-effecting).
    """
    if result.status == CheckStatus.ERROR:
        return
    if result.auto_fixed:
        return
    cache[check_name] = {
        "fingerprint": fingerprint,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit": _get_head_short(project_root),
        "result": result.to_dict(),
    }
