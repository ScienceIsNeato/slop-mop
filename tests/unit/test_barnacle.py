"""Tests for the barnacle queue CLI."""

import argparse
import json
import re
from unittest.mock import patch

from slopmop.cli.barnacle import (
    QUEUE_DIR_ENVAR,
    SCHEMA_VERSION,
    STATUS_CLAIMED,
    STATUS_OPEN,
    STATUS_RESOLVED,
    _barnacle_id,
    _find_barnacle,
    _list_barnacles,
    _queue_dir,
    auto_file_barnacle,
    cmd_barnacle,
    cmd_barnacle_claim,
    cmd_barnacle_file,
    cmd_barnacle_list,
    cmd_barnacle_resolve,
    cmd_barnacle_show,
    cmd_barnacle_watch,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _args(**kwargs) -> argparse.Namespace:
    """Build a minimal Namespace; barnacle handlers only read named attrs."""
    defaults = dict(
        barnacle_action=None,
        barnacle_id=None,
        command="sm swab",
        gate=None,
        expected="swab passes",
        actual="swab failed",
        output_excerpt="",
        blocker_type="blocking",
        agent=None,
        project_root=".",
        auto_filed=False,
        status="open",
        json_output=False,
        commit=None,
        branch=None,
        notes=None,
        reproduction_steps=[],
        interval=15,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# Unit: barnacle_id format
# ---------------------------------------------------------------------------


class TestBarnacleId:
    def test_format(self):
        bid = _barnacle_id()
        assert bid.startswith("barnacle-")
        # barnacle-YYYYMMDD-HHMMSS-<8hex>
        assert re.match(r"^barnacle-\d{8}-\d{6}-[0-9a-f]{8}$", bid), bid

    def test_unique(self):
        ids = {_barnacle_id() for _ in range(20)}
        assert len(ids) == 20


# ---------------------------------------------------------------------------
# Unit: queue_dir override via env var
# ---------------------------------------------------------------------------


class TestQueueDir:
    def test_default_is_home_slopmop(self):
        qdir = _queue_dir()
        assert qdir.parts[-2:] == (".slopmop", "barnacles")

    def test_override_via_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path / "queue"))
        assert _queue_dir() == tmp_path / "queue"


# ---------------------------------------------------------------------------
# cmd_barnacle_file
# ---------------------------------------------------------------------------


class TestCmdBarnacleFile:
    def test_creates_json_file(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))
        rc = cmd_barnacle_file(_args(command="sm scour", expected="ok", actual="fail"))
        assert rc == 0
        files = list(tmp_path.glob("barnacle-*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["schema"] == SCHEMA_VERSION
        assert data["status"] == STATUS_OPEN
        assert data["command"] == "sm scour"

    def test_output_contains_id(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))
        cmd_barnacle_file(_args())
        out = capsys.readouterr().out
        assert "barnacle-" in out

    def test_auto_filed_flag(self, tmp_path, monkeypatch):
        """CLI-filed barnacles are never auto_filed (only auto_file_barnacle() sets True)."""
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))
        # passing auto_filed=True to _args has no effect — cmd_barnacle_file always writes False
        cmd_barnacle_file(_args(auto_filed=True))
        data = json.loads(next(tmp_path.glob("barnacle-*.json")).read_text())
        assert data["auto_filed"] is False


# ---------------------------------------------------------------------------
# cmd_barnacle_list
# ---------------------------------------------------------------------------


class TestCmdBarnacleList:
    def test_empty_queue_no_dir(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path / "nonexistent"))
        rc = cmd_barnacle_list(_args())
        assert rc == 0
        out = capsys.readouterr().out
        assert "barnacle" in out.lower()

    def test_files_show_in_list(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))
        cmd_barnacle_file(_args())
        cmd_barnacle_file(_args(command="sm refit"))
        rc = cmd_barnacle_list(_args(status="open"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "barnacle-" in out

    def test_all_status_filter(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))
        cmd_barnacle_file(_args())
        rc = cmd_barnacle_list(_args(status="all"))
        assert rc == 0


# ---------------------------------------------------------------------------
# _list_barnacles / _find_barnacle
# ---------------------------------------------------------------------------


class TestListAndFind:
    def test_list_empty_when_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path / "nope"))
        assert _list_barnacles() == []

    def test_list_filters_by_status(self, tmp_path, monkeypatch):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))
        cmd_barnacle_file(_args())
        assert len(_list_barnacles("open")) == 1
        assert len(_list_barnacles("claimed")) == 0

    def test_find_by_prefix(self, tmp_path, monkeypatch):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))
        cmd_barnacle_file(_args())
        files = list(tmp_path.glob("barnacle-*.json"))
        bid = files[0].stem
        # Find by first 20 characters
        found = _find_barnacle(bid[:20])
        assert found is not None
        assert found["id"] == bid

    def test_find_missing_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path / "empty"))
        assert _find_barnacle("barnacle-99999999") is None


# ---------------------------------------------------------------------------
# File → Claim → Resolve lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_full_lifecycle(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))

        # FILE
        cmd_barnacle_file(_args(command="sm upgrade"))
        files = list(tmp_path.glob("barnacle-*.json"))
        assert len(files) == 1
        bid = files[0].stem

        # CLAIM
        rc = cmd_barnacle_claim(_args(barnacle_id=bid, agent="test-agent"))
        assert rc == 0
        data = json.loads(files[0].read_text())
        assert data["status"] == STATUS_CLAIMED
        assert data["claim"]["agent"] == "test-agent"

        # RESOLVE
        rc = cmd_barnacle_resolve(
            _args(
                barnacle_id=bid,
                commit="abc1234",
                branch="fix/test",
                notes="fixed it",
                agent="test-agent",
            )
        )
        assert rc == 0
        data = json.loads(files[0].read_text())
        assert data["status"] == STATUS_RESOLVED
        assert data["resolution"]["fix_commit"] == "abc1234"

    def test_cannot_claim_already_claimed(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))
        cmd_barnacle_file(_args())
        bid = next(tmp_path.glob("barnacle-*.json")).stem
        cmd_barnacle_claim(_args(barnacle_id=bid))
        rc = cmd_barnacle_claim(_args(barnacle_id=bid))
        assert rc != 0

    def test_resolve_already_resolved_is_noop(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))
        cmd_barnacle_file(_args())
        bid = next(tmp_path.glob("barnacle-*.json")).stem
        cmd_barnacle_claim(_args(barnacle_id=bid))
        cmd_barnacle_resolve(_args(barnacle_id=bid))
        rc = cmd_barnacle_resolve(_args(barnacle_id=bid))
        assert rc == 0  # second resolve is a no-op, not an error


# ---------------------------------------------------------------------------
# cmd_barnacle_show
# ---------------------------------------------------------------------------


class TestCmdBarnacleShow:
    def test_show_renders_fields(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))
        cmd_barnacle_file(
            _args(command="sm buff", expected="buff ok", actual="buff fail")
        )
        bid = next(tmp_path.glob("barnacle-*.json")).stem
        rc = cmd_barnacle_show(_args(barnacle_id=bid))
        assert rc == 0
        out = capsys.readouterr().out
        assert "sm buff" in out
        assert "buff ok" in out

    def test_show_json_flag(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))
        cmd_barnacle_file(_args())
        capsys.readouterr()  # clear file command output
        bid = next(tmp_path.glob("barnacle-*.json")).stem
        rc = cmd_barnacle_show(_args(barnacle_id=bid, json_output=True))
        assert rc == 0
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["id"] == bid

    def test_show_missing_id_fails(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path / "empty"))
        rc = cmd_barnacle_show(_args(barnacle_id="barnacle-nonexistent"))
        assert rc != 0

    def test_show_none_id_fails(self, tmp_path, monkeypatch):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))
        rc = cmd_barnacle_show(_args(barnacle_id=None))
        assert rc != 0


# ---------------------------------------------------------------------------
# auto_file_barnacle
# ---------------------------------------------------------------------------


class TestAutoFileBarnacle:
    def test_creates_file_returns_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))
        bid = auto_file_barnacle(
            command="sm upgrade",
            expected="swab passes",
            actual="swab failed",
            output_excerpt="gate failed",
            blocker_type="blocking",
            project_root=str(tmp_path),
        )
        assert bid is not None
        assert bid.startswith("barnacle-")
        assert (tmp_path / f"{bid}.json").exists()

    def test_auto_filed_flag_in_data(self, tmp_path, monkeypatch):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))
        bid = auto_file_barnacle(
            command="sm upgrade",
            expected="ok",
            actual="fail",
            output_excerpt="",
        )
        data = json.loads((tmp_path / f"{bid}.json").read_text())
        assert data["auto_filed"] is True

    def test_never_raises_on_failure(self, tmp_path, monkeypatch):
        # Make the queue dir unwritable by monkeypatching _write_barnacle
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))
        with patch(
            "slopmop.cli.barnacle._write_barnacle", side_effect=OSError("no disk")
        ):
            result = auto_file_barnacle(
                command="sm upgrade",
                expected="ok",
                actual="fail",
                output_excerpt="",
            )
        assert result is None


# ---------------------------------------------------------------------------
# cmd_barnacle dispatcher
# ---------------------------------------------------------------------------


class TestCmdBarnacleDispatcher:
    def test_no_action_returns_nonzero(self):
        rc = cmd_barnacle(_args(barnacle_action=None))
        assert rc == 2

    def test_file_action_dispatches(self, tmp_path, monkeypatch):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))
        rc = cmd_barnacle(_args(barnacle_action="file"))
        assert rc == 0

    def test_list_action_dispatches(self, tmp_path, monkeypatch):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path / "empty"))
        rc = cmd_barnacle(_args(barnacle_action="list"))
        assert rc == 0


# ---------------------------------------------------------------------------
# cmd_barnacle_watch
# ---------------------------------------------------------------------------


class TestCmdBarnacleWatch:
    def test_invalid_interval_returns_nonzero(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))
        rc = cmd_barnacle_watch(_args(interval=0))
        assert rc != 0
        err = capsys.readouterr().err
        assert "--interval" in err

    def test_negative_interval_returns_nonzero(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))
        rc = cmd_barnacle_watch(_args(interval=-5))
        assert rc != 0

    def test_exits_on_keyboard_interrupt(self, tmp_path, monkeypatch, capsys):
        """Watch exits cleanly on KeyboardInterrupt after finding new entries."""
        import unittest.mock as mock

        monkeypatch.setenv(QUEUE_DIR_ENVAR, str(tmp_path))
        cmd_barnacle_file(_args(command="sm swab"))

        call_count = 0

        def _sleep_once(seconds):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise KeyboardInterrupt

        with mock.patch("slopmop.cli.barnacle.time.sleep", side_effect=_sleep_once):
            rc = cmd_barnacle_watch(_args(interval=1, status="open"))

        assert rc == 0
        out = capsys.readouterr().out
        assert "barnacle-" in out
