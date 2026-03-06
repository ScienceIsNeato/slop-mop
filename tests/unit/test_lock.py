"""Tests for slopmop.core.lock — repo-level mutual exclusion."""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from slopmop.core.lock import (
    LOCK_DIR,
    LOCK_FILE,
    SmLockError,
    _format_busy_message,
    _is_stale,
    _lock_path,
    _max_expected_duration,
    _pid_alive,
    _read_lock_meta,
    _write_lock_meta,
    sm_lock,
)

# ── Helpers ──────────────────────────────────────────────────────────────


@pytest.fixture()
def lock_root(tmp_path: Path) -> Path:
    """Provide a temp directory that acts as a project root."""
    slopmop_dir = tmp_path / LOCK_DIR
    slopmop_dir.mkdir()
    return tmp_path


# ── _lock_path ───────────────────────────────────────────────────────────


class TestLockPath:
    def test_returns_expected_path(self, tmp_path: Path) -> None:
        result = _lock_path(tmp_path)
        assert result == tmp_path / LOCK_DIR / LOCK_FILE

    def test_path_is_absolute(self, tmp_path: Path) -> None:
        assert _lock_path(tmp_path).is_absolute()


# ── _pid_alive ───────────────────────────────────────────────────────────


class TestPidAlive:
    def test_current_pid_is_alive(self) -> None:
        assert _pid_alive(os.getpid()) is True

    def test_nonexistent_pid_is_dead(self) -> None:
        # PID 99999999 is extremely unlikely to exist
        assert _pid_alive(99999999) is False

    def test_permission_error_treated_as_alive(self) -> None:
        with patch("os.kill", side_effect=PermissionError):
            assert _pid_alive(1) is True


# ── _read_lock_meta / _write_lock_meta ───────────────────────────────────


class TestLockMeta:
    def test_write_and_read_roundtrip(self, lock_root: Path) -> None:
        path = _lock_path(lock_root)
        _write_lock_meta(path, "swab")
        meta = _read_lock_meta(path)

        assert meta is not None
        assert meta["pid"] == os.getpid()
        assert meta["verb"] == "swab"
        assert isinstance(meta["started_at"], float)

    def test_read_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert _read_lock_meta(tmp_path / "nope") is None

    def test_read_corrupt_file_returns_none(self, lock_root: Path) -> None:
        path = _lock_path(lock_root)
        path.write_text("not json!")
        assert _read_lock_meta(path) is None

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "dirs" / "lock"
        _write_lock_meta(path, "scour")
        meta = _read_lock_meta(path)
        assert meta is not None
        assert meta["verb"] == "scour"


# ── _is_stale ────────────────────────────────────────────────────────────


class TestIsStale:
    def test_dead_pid_is_stale(self, tmp_path: Path) -> None:
        meta = {"pid": 99999999, "started_at": time.time(), "verb": "swab"}
        assert _is_stale(meta, tmp_path) is True

    def test_alive_pid_recent_is_not_stale(self, tmp_path: Path) -> None:
        meta = {
            "pid": os.getpid(),
            "started_at": time.time(),
            "verb": "swab",
        }
        assert _is_stale(meta, tmp_path) is False

    def test_alive_pid_old_lock_is_stale(self, tmp_path: Path) -> None:
        meta = {
            "pid": os.getpid(),
            "started_at": time.time() - 9999,  # way past any threshold
            "verb": "swab",
        }
        assert _is_stale(meta, tmp_path) is True


# ── _max_expected_duration ───────────────────────────────────────────────


class TestMaxExpectedDuration:
    def test_returns_default_when_no_history(self, tmp_path: Path) -> None:
        result = _max_expected_duration(tmp_path)
        assert result == 600  # _DEFAULT_STALE_SECONDS

    def test_uses_timing_history_when_available(self, tmp_path: Path) -> None:
        from slopmop.reporting.timings import TimingStats

        mock_stats = {
            "check-a": TimingStats(
                median=5.0,
                q1=4.0,
                q3=6.0,
                iqr=2.0,
                historical_max=10.0,
                sample_count=5,
            ),
            "check-b": TimingStats(
                median=3.0,
                q1=2.0,
                q3=4.0,
                iqr=2.0,
                historical_max=8.0,
                sample_count=5,
            ),
        }
        with patch(
            "slopmop.reporting.timings.load_timings",
            return_value=mock_stats,
        ):
            result = _max_expected_duration(tmp_path)
        # (10 + 8) * 2 = 36, but floor is 30
        assert result == 36.0

    def test_floor_of_30_seconds(self, tmp_path: Path) -> None:
        from slopmop.reporting.timings import TimingStats

        mock_stats = {
            "fast-check": TimingStats(
                median=0.1,
                q1=0.05,
                q3=0.15,
                iqr=0.1,
                historical_max=0.2,
                sample_count=3,
            ),
        }
        with patch(
            "slopmop.reporting.timings.load_timings",
            return_value=mock_stats,
        ):
            result = _max_expected_duration(tmp_path)
        # 0.2 * 2 = 0.4, floor is 30
        assert result == 30.0


# ── _format_busy_message ─────────────────────────────────────────────────


class TestFormatBusyMessage:
    def test_includes_pid_and_verb(self) -> None:
        meta = {"pid": 12345, "verb": "swab", "started_at": time.time() - 5}
        msg = _format_busy_message(meta)
        assert "12345" in msg
        assert "swab" in msg
        assert "5s" in msg or "running for" in msg

    def test_handles_missing_started_at(self) -> None:
        meta = {"pid": 12345, "verb": "scour"}
        msg = _format_busy_message(meta)
        assert "12345" in msg
        assert "running for" not in msg

    def test_includes_manual_removal_hint(self) -> None:
        meta = {"pid": 1, "verb": "swab"}
        msg = _format_busy_message(meta)
        assert f"rm {LOCK_DIR}/{LOCK_FILE}" in msg


# ── sm_lock (integration) ───────────────────────────────────────────────


class TestSmLock:
    def test_acquires_and_releases_cleanly(self, lock_root: Path) -> None:
        with sm_lock(lock_root, "swab"):
            path = _lock_path(lock_root)
            assert path.exists()
            meta = _read_lock_meta(path)
            assert meta is not None
            assert meta["verb"] == "swab"

        # After release, metadata should be cleared
        meta_after = _read_lock_meta(path)
        assert meta_after == {}

    def test_creates_lock_dir_if_missing(self, tmp_path: Path) -> None:
        # No .slopmop dir yet
        with sm_lock(tmp_path, "scour"):
            assert (tmp_path / LOCK_DIR).is_dir()

    def test_concurrent_lock_raises_error(self, lock_root: Path) -> None:
        with sm_lock(lock_root, "swab"):
            with pytest.raises(SmLockError, match="Another sm process"):
                with sm_lock(lock_root, "scour"):
                    pass  # pragma: no cover

    def test_stale_dead_pid_lock_is_recovered(self, lock_root: Path) -> None:
        """Simulate a dead process that left a lock behind."""
        path = _lock_path(lock_root)

        # Write metadata claiming a dead PID holds the lock
        meta = {
            "pid": 99999999,
            "started_at": time.time() - 100,
            "verb": "swab",
        }
        path.write_text(json.dumps(meta))

        # flock is NOT held (dead process), so we should acquire
        with sm_lock(lock_root, "scour"):
            new_meta = _read_lock_meta(path)
            assert new_meta is not None
            assert new_meta["verb"] == "scour"
            assert new_meta["pid"] == os.getpid()

    def test_lock_released_on_exception(self, lock_root: Path) -> None:
        with pytest.raises(ValueError, match="boom"):
            with sm_lock(lock_root, "swab"):
                raise ValueError("boom")

        # Lock should be released — re-acquisition should work
        with sm_lock(lock_root, "scour"):
            pass

    def test_different_roots_do_not_conflict(self, tmp_path: Path) -> None:
        root_a = tmp_path / "project_a"
        root_b = tmp_path / "project_b"
        root_a.mkdir()
        root_b.mkdir()

        with sm_lock(root_a, "swab"):
            # Different project root should not conflict
            with sm_lock(root_b, "scour"):
                pass  # Both locked simultaneously — no error
