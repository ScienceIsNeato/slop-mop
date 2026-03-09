"""Repo-level mutual exclusion for sm runs.

Prevents concurrent ``sm swab`` / ``sm scour`` processes from racing
over the same project root.  The primary mechanism is POSIX ``flock``
(auto-released by the kernel when the process exits, even on SIGKILL).
A JSON sidecar stores human-readable metadata (PID, verb, start time)
so the error message can tell you *what* is already running.

Stale-lock detection covers edge cases where the sidecar survives after
the kernel lock is released (NFS, forced unmount, etc.):
  1. PID no longer alive  →  force-remove, re-acquire.
    2. PID is alive but no longer an sm/slopmop process (PID reuse) → stale.
    3. Age exceeds 2× the sum of historical gate timings  →  stale.
    4. Absolute fallback cap (10 min) when no timing history exists.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - platform-specific (Windows)
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

LOCK_DIR = ".slopmop"
LOCK_FILE = "sm.lock"

# If no timing history exists, treat locks older than this as stale.
_DEFAULT_STALE_SECONDS = 600  # 10 minutes

# Multiplier applied to sum-of-historical-maxes for stale detection.
_STALE_MULTIPLIER = 2


class SmLockError(RuntimeError):
    """Raised when another sm process holds the repo lock."""


# ── helpers ──────────────────────────────────────────────────────────────


def _lock_path(project_root: Path) -> Path:
    return project_root / LOCK_DIR / LOCK_FILE


def _pid_alive(pid: int) -> bool:
    """Return True if *pid* refers to a running process."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it (different user).
        return True
    return True


def _pid_looks_like_sm(pid: int) -> bool:
    """Return True when *pid* appears to be an sm/slopmop process.

    Guards against PID reuse where a dead lock-holder PID gets reassigned
    to an unrelated process.
    """
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False

    if result.returncode != 0:
        return False

    command = (result.stdout or "").strip().lower()
    if not command:
        return False

    return (
        "slopmop" in command
        or "python -m slopmop" in command
        or " sm " in f" {command} "
        or command.endswith("/sm")
    )


def _max_expected_duration(project_root: Path) -> float:
    """Estimate the longest plausible run duration from timing history.

    Returns ``_STALE_MULTIPLIER`` × (sum of per-check historical_max),
    or ``_DEFAULT_STALE_SECONDS`` when no history is available.
    """
    try:
        from slopmop.reporting.timings import load_timings

        stats = load_timings(str(project_root))
        if not stats:
            return _DEFAULT_STALE_SECONDS
        total_max = sum(ts.historical_max for ts in stats.values())
        return max(total_max * _STALE_MULTIPLIER, 30.0)  # floor 30s
    except Exception:
        return _DEFAULT_STALE_SECONDS


def _read_lock_meta(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data: Dict[str, Any] = json.loads(path.read_text())
        if isinstance(data, dict):
            return data
        return None
    except Exception:
        return None


def _format_utc_epoch(epoch: float) -> str:
    """Return an ISO8601 UTC timestamp for *epoch* (seconds since epoch)."""
    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _write_lock_meta(path: Path, verb: str, expected_duration_seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    started_at = time.time()
    expected_duration = max(float(expected_duration_seconds), 1.0)
    expected_done_at = started_at + expected_duration
    payload: Dict[str, Any] = {
        "pid": os.getpid(),
        "verb": verb,
        "started_at": started_at,
        "expected_duration_seconds": round(expected_duration, 1),
        "expected_done_at": expected_done_at,
        "expected_done_at_utc": _format_utc_epoch(expected_done_at),
    }
    path.write_text(json.dumps(payload))


def _is_stale(
    meta: Dict[str, Any],
    project_root: Path,
    stale_after_seconds: Optional[float] = None,
) -> bool:
    """Determine whether the lock described by *meta* is stale."""
    pid = meta.get("pid")

    # 1. If the holding process is dead, the lock is definitely stale.
    if isinstance(pid, int) and not _pid_alive(pid):
        logger.debug("Lock holder PID %d is dead — treating as stale", pid)
        return True

    # 2. PID reuse guard: process exists, but isn't an sm/slopmop process.
    if isinstance(pid, int) and _pid_alive(pid) and not _pid_looks_like_sm(pid):
        logger.debug(
            "Lock holder PID %d exists but is not sm/slopmop — treating as stale",
            pid,
        )
        return True

    # 3. If the lock is older than the max expected duration, stale.
    started = meta.get("started_at", 0)
    age = time.time() - started
    threshold = (
        stale_after_seconds
        if stale_after_seconds is not None and stale_after_seconds > 0
        else _max_expected_duration(project_root)
    )
    if age > threshold:
        logger.debug(
            "Lock age %.1fs exceeds threshold %.1fs — treating as stale",
            age,
            threshold,
        )
        return True

    return False


def _format_busy_message(meta: Dict[str, Any]) -> str:
    """Build an informative error message for the user/agent."""
    pid = meta.get("pid", "?")
    verb = meta.get("verb", "unknown")
    started = meta.get("started_at")
    expected_done_at = meta.get("expected_done_at")
    expected_done_at_utc = meta.get("expected_done_at_utc")

    if started:
        elapsed = time.time() - started
        time_str = f" (running for {elapsed:.0f}s)"
    else:
        time_str = ""

    eta_str = ""
    if isinstance(expected_done_at, (int, float)):
        remaining = max(0.0, float(expected_done_at) - time.time())
        eta_str = f"\n   ETA: ~{remaining:.0f}s until lock is free"
        if isinstance(expected_done_at_utc, str) and expected_done_at_utc:
            eta_str += f" (expected done at {expected_done_at_utc})"
    elif isinstance(expected_done_at_utc, str) and expected_done_at_utc:
        eta_str = f"\n   ETA: expected done at {expected_done_at_utc}"

    return (
        f"⏳ Another sm process is already running on this project.\n"
        f"   PID {pid} · verb: {verb}{time_str}\n"
        f"{eta_str}\n"
        f"\n"
        f"   Wait for it to finish, or if it crashed:\n"
        f"     rm {LOCK_DIR}/{LOCK_FILE}"
    )


# ── public API ───────────────────────────────────────────────────────────


@contextmanager
def sm_lock(
    project_root: str | Path,
    verb: str,
    stale_after_seconds: Optional[float] = None,
    expected_duration_seconds: Optional[float] = None,
) -> Iterator[None]:
    """Context manager that acquires a per-repo lock.

    Usage::

        with sm_lock(project_root, "swab"):
            # run checks — guaranteed single-writer
            ...

    Raises:
        SmLockError: If another sm process holds the lock and it
            is *not* stale (live PID + within expected duration).
    """
    root = Path(project_root).resolve()
    path = _lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Windows fallback: no fcntl available. Keep behavior functional
    # without crashing imports/calls on non-POSIX systems.
    if fcntl is None:
        logger.warning("fcntl unavailable; running without repo lock")
        yield
        return

    fd = None
    try:
        # Open (or create) the lock file.
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)

        # Try non-blocking exclusive lock.
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            # Could not acquire — someone else holds the flock.
            # Check staleness via the metadata sidecar.
            meta = _read_lock_meta(path)
            if meta and _is_stale(
                meta,
                root,
                stale_after_seconds=stale_after_seconds,
            ):
                logger.info("Clearing stale lock (PID %s)", meta.get("pid"))
                # Force-acquire: the kernel lock is gone (holder died)
                # or holder is hung past threshold.  Truncate + re-lock.
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except (BlockingIOError, OSError):
                    # Kernel lock still held (hung process, not dead).
                    # We can't safely steal it.
                    if meta:
                        raise SmLockError(_format_busy_message(meta))
                    raise SmLockError(
                        "⏳ Another sm process is running " "(could not acquire lock)."
                    )
            else:
                if meta:
                    raise SmLockError(_format_busy_message(meta))
                raise SmLockError(
                    "⏳ Another sm process is running " "(could not acquire lock)."
                )

        # We hold the flock.  Write metadata for diagnostics.
        expected_duration = (
            expected_duration_seconds
            if expected_duration_seconds is not None and expected_duration_seconds > 0
            else _max_expected_duration(root)
        )
        _write_lock_meta(path, verb, expected_duration)

        yield

    finally:
        # Clean metadata, release flock, close fd.
        if fd is not None:
            try:
                # Remove metadata so stale-detection doesn't fire on
                # leftover content after a clean exit.
                if path.exists():
                    path.write_text("{}")
            except OSError:
                pass
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass
