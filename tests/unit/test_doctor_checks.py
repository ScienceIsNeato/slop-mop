"""Per-check tests for ``sm doctor`` — including the ``--fix`` flows.

Framework/CLI scaffolding lives in ``test_doctor.py``.  This file
exercises each concrete ``DoctorCheck`` against ``tmp_path`` fixtures
so the tests reflect what gates will actually see.  Mocking is limited
to external state (``subprocess.run``, PID liveness) that the test
can't control directly.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slopmop.core.config import CONFIG_FILE, STATE_DIR
from slopmop.core.lock import LOCK_DIR, LOCK_FILE
from slopmop.doctor import DoctorContext, DoctorStatus
from slopmop.doctor.project_env import (
    ProjectJsDepsCheck,
    ProjectPipCheck,
    ProjectVenvCheck,
)
from slopmop.doctor.runtime import (
    PlatformCheck,
    SmResolutionCheck,
    _find_all_on_path,
)
from slopmop.doctor.sm_env import (
    InstallModeCheck,
    SmPipCheck,
    ToolInventoryCheck,
    _group_install_hints,
    _reinstall_hint,
)
from slopmop.doctor.state import (
    StateConfigCheck,
    StateDirCheck,
    StateLockCheck,
    _find_newest_config_backup,
    _format_age,
)

# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def ctx(tmp_path: Path) -> DoctorContext:
    return DoctorContext(project_root=tmp_path)


def _mk_lock(root: Path, meta: dict) -> Path:
    lock_dir = root / LOCK_DIR
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / LOCK_FILE
    lock_file.write_text(json.dumps(meta))
    return lock_file


def _mk_python_project(root: Path) -> None:
    (root / "pyproject.toml").write_text("[project]\nname='x'\n")


def _mk_project_venv(root: Path) -> Path:
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


# ── runtime.* ────────────────────────────────────────────────────────────


class TestPlatformCheck:
    def test_always_ok(self, ctx):
        r = PlatformCheck().run(ctx)
        assert r.status is DoctorStatus.OK
        assert r.can_fix is False

    def test_detail_includes_bug_report_fields(self, ctx):
        r = PlatformCheck().run(ctx)
        assert "Python:" in r.detail
        assert "Executable:" in r.detail
        assert "OS:" in r.detail
        assert "slopmop:" in r.detail
        assert str(ctx.project_root) in r.detail

    def test_data_structured(self, ctx):
        r = PlatformCheck().run(ctx)
        assert r.data["python_executable"] == sys.executable
        assert r.data["project_root"] == str(ctx.project_root)


class TestFindAllOnPath:
    def test_finds_multiple_distinct(self, tmp_path, monkeypatch):
        """Two dirs on PATH, both with an ``sm`` — both reported."""
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        for d in (a, b):
            sm = d / "sm"
            sm.write_text("#!/bin/sh\n")
            sm.chmod(0o755)
        monkeypatch.setenv("PATH", f"{a}{os.pathsep}{b}")
        found = _find_all_on_path("sm")
        assert len(found) == 2
        assert found[0].startswith(str(a))  # order follows PATH

    def test_dedups_symlinks(self, tmp_path, monkeypatch):
        """``~/.local/bin/sm`` → pipx shim → real binary — count as one."""
        real_dir = tmp_path / "real"
        link_dir = tmp_path / "link"
        real_dir.mkdir()
        link_dir.mkdir()
        real = real_dir / "sm"
        real.write_text("#!/bin/sh\n")
        real.chmod(0o755)
        (link_dir / "sm").symlink_to(real)
        monkeypatch.setenv("PATH", f"{link_dir}{os.pathsep}{real_dir}")
        assert len(_find_all_on_path("sm")) == 1

    def test_empty_path_segment_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PATH", f"{os.pathsep}{tmp_path}{os.pathsep}")
        assert _find_all_on_path("definitely-not-there") == []


class TestSmResolutionCheck:
    def test_single_sm_ok(self, ctx, monkeypatch, tmp_path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        sm = bin_dir / "sm"
        sm.write_text("#!/bin/sh\n")
        sm.chmod(0o755)
        monkeypatch.setenv("PATH", str(bin_dir))
        r = SmResolutionCheck().run(ctx)
        assert r.status is DoctorStatus.OK
        assert str(sm) in r.summary or str(sm.resolve()) in r.summary

    def test_collision_warns(self, ctx, monkeypatch, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        for d in (a, b):
            d.mkdir()
            sm = d / "sm"
            sm.write_text("#!/bin/sh\n")
            sm.chmod(0o755)
        monkeypatch.setenv("PATH", f"{a}{os.pathsep}{b}")
        r = SmResolutionCheck().run(ctx)
        assert r.status is DoctorStatus.WARN
        assert "2 sm binaries" in r.summary
        assert "← active" in r.detail
        assert "type -a sm" in r.fix_hint

    def test_no_sm_on_path_source_checkout_warns(self, ctx, monkeypatch, tmp_path):
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        with patch(
            "slopmop.cli.upgrade._running_from_source_checkout",
            return_value=True,
        ):
            r = SmResolutionCheck().run(ctx)
        assert r.status is DoctorStatus.WARN
        assert "source checkout" in r.summary

    def test_no_sm_on_path_installed_fails(self, ctx, monkeypatch, tmp_path):
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        with patch(
            "slopmop.cli.upgrade._running_from_source_checkout",
            return_value=False,
        ):
            r = SmResolutionCheck().run(ctx)
        assert r.status is DoctorStatus.FAIL
        assert "pipx install slopmop" in r.fix_hint


# ── sm_env.* ─────────────────────────────────────────────────────────────


class TestInstallModeCheck:
    def test_pipx_ok(self, ctx):
        with patch("slopmop.doctor.sm_env.classify_install", return_value="pipx"):
            r = InstallModeCheck().run(ctx)
        assert r.status is DoctorStatus.OK
        assert r.data["install_mode"] == "pipx"

    def test_editable_ok(self, ctx):
        with patch("slopmop.doctor.sm_env.classify_install", return_value="editable"):
            r = InstallModeCheck().run(ctx)
        assert r.status is DoctorStatus.OK
        assert "git pull" in r.detail

    def test_system_warns(self, ctx):
        with patch("slopmop.doctor.sm_env.classify_install", return_value="system"):
            r = InstallModeCheck().run(ctx)
        assert r.status is DoctorStatus.WARN
        assert "pipx install slopmop" in r.fix_hint


class TestSmPipCheck:
    def test_clean_env_ok(self, ctx):
        proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=proc):
            r = SmPipCheck().run(ctx)
        assert r.status is DoctorStatus.OK

    def test_conflicts_fail(self, ctx):
        proc = MagicMock(
            returncode=1,
            stdout="pkg-a 1.0 requires pkg-b<2, but you have pkg-b 3.0",
            stderr="",
        )
        with patch("subprocess.run", return_value=proc):
            r = SmPipCheck().run(ctx)
        assert r.status is DoctorStatus.FAIL
        assert "pkg-b 3.0" in r.detail
        assert r.fix_hint

    def test_timeout_warns(self, ctx):
        import subprocess as sp

        with patch("subprocess.run", side_effect=sp.TimeoutExpired("pip", 60)):
            r = SmPipCheck().run(ctx)
        assert r.status is DoctorStatus.WARN

    def test_pip_missing_skips(self, ctx):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            r = SmPipCheck().run(ctx)
        assert r.status is DoctorStatus.SKIP


class TestReinstallHint:
    def test_pipx_mode(self):
        with patch("slopmop.doctor.sm_env.classify_install", return_value="pipx"):
            assert _reinstall_hint() == "pipx reinstall slopmop"

    def test_editable_mode(self):
        with patch("slopmop.doctor.sm_env.classify_install", return_value="editable"):
            assert "pip install -e" in _reinstall_hint()

    def test_venv_mode(self):
        with patch("slopmop.doctor.sm_env.classify_install", return_value="venv"):
            assert "pip install --force-reinstall" in _reinstall_hint()


class TestToolInventoryCheck:
    def test_all_resolved_ok(self, ctx):
        # Path must normalize to an allowlisted name so the validator
        # tripwire doesn't fire — it's testing the "all found" branch,
        # not validator rejection (that's the next test).
        with patch(
            "slopmop.doctor.sm_env.find_tool",
            side_effect=lambda name, root: f"/usr/local/bin/{name}",
        ):
            r = ToolInventoryCheck().run(ctx)
        assert r.status is DoctorStatus.OK
        assert "all " in r.summary

    def test_missing_tools_fail(self, ctx):
        with patch("slopmop.doctor.sm_env.find_tool", return_value=None):
            r = ToolInventoryCheck().run(ctx)
        assert r.status is DoctorStatus.FAIL
        assert "missing" in r.summary.lower()
        assert r.fix_hint
        # Hint should be deduped — not one line per tool.
        assert r.fix_hint.count("pipx install slopmop[lint]") == 1

    def test_validator_reject_is_fail(self, ctx):
        """Tool resolves on disk but allowlist rejects — the Windows tripwire."""
        from slopmop.subprocess.validator import SecurityError

        def fake_validate(self, cmd):
            raise SecurityError(f"Executable '{cmd[0]}' not in whitelist")

        with (
            patch(
                "slopmop.doctor.sm_env.find_tool",
                return_value="/venv/Scripts/black.exe",
            ),
            patch(
                "slopmop.subprocess.validator.CommandValidator.validate",
                fake_validate,
            ),
        ):
            r = ToolInventoryCheck().run(ctx)

        assert r.status is DoctorStatus.FAIL
        assert "rejected by allowlist" in r.summary
        assert "slopmop bug" in r.fix_hint
        assert r.data["validator_rejects"]

    def test_group_install_hints_dedups(self):
        missing = [
            ("black", "gate.a", "pipx install slopmop[lint]"),
            ("isort", "gate.b", "pipx install slopmop[lint]"),
            ("bandit", "gate.c", "pipx install slopmop[security]"),
        ]
        hint = _group_install_hints(missing)
        lines = hint.splitlines()
        assert len(lines) == 2
        assert lines[0] == "pipx install slopmop[lint]"


# ── project.* ────────────────────────────────────────────────────────────


class TestProjectVenvCheck:
    def test_no_python_markers_skips(self, ctx):
        r = ProjectVenvCheck().run(ctx)
        assert r.status is DoctorStatus.SKIP

    def test_venv_present_ok(self, tmp_path):
        _mk_python_project(tmp_path)
        python = _mk_project_venv(tmp_path)
        ctx = DoctorContext(project_root=tmp_path)
        r = ProjectVenvCheck().run(ctx)
        assert r.status is DoctorStatus.OK
        assert str(python) in r.summary

    def test_no_venv_warns_with_fallback(self, tmp_path, monkeypatch):
        _mk_python_project(tmp_path)
        # Ensure VIRTUAL_ENV fallback doesn't mask the missing-venv path.
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
        ctx = DoctorContext(project_root=tmp_path)
        r = ProjectVenvCheck().run(ctx)
        assert r.status is DoctorStatus.WARN
        assert "fall back" in r.summary
        assert "venv" in r.fix_hint


class TestProjectPipCheck:
    def test_skips_without_python_markers(self, ctx):
        assert ProjectPipCheck().run(ctx).status is DoctorStatus.SKIP

    def test_skips_without_local_venv(self, tmp_path, monkeypatch):
        _mk_python_project(tmp_path)
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
        ctx = DoctorContext(project_root=tmp_path)
        r = ProjectPipCheck().run(ctx)
        assert r.status is DoctorStatus.SKIP
        assert "project.python_venv" in r.summary

    def test_runs_pip_check_in_project_venv(self, tmp_path):
        _mk_python_project(tmp_path)
        _mk_project_venv(tmp_path)
        proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=proc) as mock_run:
            r = ProjectPipCheck().run(DoctorContext(project_root=tmp_path))
        assert r.status is DoctorStatus.OK
        # First arg should be the project's python, not sys.executable.
        called_python = mock_run.call_args.args[0][0]
        assert str(tmp_path) in called_python

    def test_conflicts_fail(self, tmp_path):
        _mk_python_project(tmp_path)
        _mk_project_venv(tmp_path)
        proc = MagicMock(returncode=1, stdout="conflict detected", stderr="")
        with patch("subprocess.run", return_value=proc):
            r = ProjectPipCheck().run(DoctorContext(project_root=tmp_path))
        assert r.status is DoctorStatus.FAIL
        assert "conflict detected" in r.detail


class TestProjectJsDepsCheck:
    def test_skips_without_package_json(self, ctx):
        assert ProjectJsDepsCheck().run(ctx).status is DoctorStatus.SKIP

    def test_node_modules_present_ok(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "node_modules").mkdir()
        r = ProjectJsDepsCheck().run(DoctorContext(project_root=tmp_path))
        assert r.status is DoctorStatus.OK

    def test_missing_node_modules_warns_with_pm_specific_hint(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "pnpm-lock.yaml").write_text("")
        r = ProjectJsDepsCheck().run(DoctorContext(project_root=tmp_path))
        assert r.status is DoctorStatus.WARN
        assert "pnpm" in r.summary
        assert "pnpm install" in r.fix_hint

    def test_yarn_detected(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "yarn.lock").write_text("")
        r = ProjectJsDepsCheck().run(DoctorContext(project_root=tmp_path))
        assert r.data["package_manager"] == "yarn"

    def test_npmrc_legacy_peer_deps_in_hint(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / ".npmrc").write_text("legacy-peer-deps = true\n")
        r = ProjectJsDepsCheck().run(DoctorContext(project_root=tmp_path))
        assert "--legacy-peer-deps" in r.fix_hint


# ── state.* (read-only) ──────────────────────────────────────────────────


class TestStateLockCheck:
    def test_no_lock_ok(self, ctx):
        r = StateLockCheck().run(ctx)
        assert r.status is DoctorStatus.OK

    def test_stale_dead_pid_fails(self, tmp_path):
        _mk_lock(tmp_path, {"pid": 99999999, "verb": "swab", "started_at": 0})
        r = StateLockCheck().run(DoctorContext(project_root=tmp_path))
        assert r.status is DoctorStatus.FAIL
        assert "stale lock" in r.summary
        assert "sm doctor --fix state.lock" in r.fix_hint

    def test_live_lock_warns(self, tmp_path):
        _mk_lock(
            tmp_path,
            {"pid": os.getpid(), "verb": "swab", "started_at": time.time()},
        )
        with patch("slopmop.core.lock._pid_looks_like_sm", return_value=True):
            r = StateLockCheck().run(DoctorContext(project_root=tmp_path))
        assert r.status is DoctorStatus.WARN
        assert "live lock" in r.summary

    def test_unreadable_sidecar_fails(self, tmp_path):
        lock_dir = tmp_path / LOCK_DIR
        lock_dir.mkdir()
        (lock_dir / LOCK_FILE).write_text("not json at all{{")
        r = StateLockCheck().run(DoctorContext(project_root=tmp_path))
        assert r.status is DoctorStatus.FAIL
        assert "unparseable" in r.summary


class TestStateDirCheck:
    def test_absent_with_writable_parent_ok(self, ctx):
        r = StateDirCheck().run(ctx)
        assert r.status is DoctorStatus.OK
        assert "not yet created" in r.summary

    def test_exists_and_writable_ok(self, tmp_path):
        (tmp_path / STATE_DIR).mkdir()
        r = StateDirCheck().run(DoctorContext(project_root=tmp_path))
        assert r.status is DoctorStatus.OK
        assert "writable" in r.summary

    @pytest.mark.skipif(
        sys.platform == "win32", reason="chmod semantics differ on Windows"
    )
    def test_unwritable_fails(self, tmp_path):
        state = tmp_path / STATE_DIR
        state.mkdir()
        state.chmod(0o500)  # r-x only
        try:
            r = StateDirCheck().run(DoctorContext(project_root=tmp_path))
            assert r.status is DoctorStatus.FAIL
            assert "chmod u+rwx" in r.fix_hint
        finally:
            state.chmod(0o700)  # let pytest clean up

    def test_absent_with_unwritable_parent_fails(self, tmp_path):
        nested = tmp_path / "project"
        nested.mkdir()
        nested.chmod(0o500)
        try:
            r = StateDirCheck().run(DoctorContext(project_root=nested))
            assert r.status is DoctorStatus.FAIL
        finally:
            nested.chmod(0o700)


class TestStateConfigCheck:
    def test_no_config_ok(self, ctx):
        r = StateConfigCheck().run(ctx)
        assert r.status is DoctorStatus.OK
        assert "sm init" in r.summary

    def test_valid_config_ok(self, tmp_path):
        (tmp_path / CONFIG_FILE).write_text(json.dumps({"version": "1.0"}))
        r = StateConfigCheck().run(DoctorContext(project_root=tmp_path))
        assert r.status is DoctorStatus.OK

    def test_broken_config_fails_no_backup(self, tmp_path):
        (tmp_path / CONFIG_FILE).write_text("not { json")
        r = StateConfigCheck().run(DoctorContext(project_root=tmp_path))
        assert r.status is DoctorStatus.FAIL
        assert r.data["backup_available"] is None
        assert "sm init" in r.fix_hint

    def test_broken_config_fails_with_backup_hint(self, tmp_path):
        (tmp_path / CONFIG_FILE).write_text("broken{")
        backup_dir = tmp_path / STATE_DIR / "backups" / "20260101_000000"
        backup_dir.mkdir(parents=True)
        backup = backup_dir / CONFIG_FILE
        backup.write_text(json.dumps({"version": "0.9"}))
        r = StateConfigCheck().run(DoctorContext(project_root=tmp_path))
        assert r.status is DoctorStatus.FAIL
        assert str(backup) == r.data["backup_available"]
        assert "sm doctor --fix state.config_readable" in r.fix_hint


# ── state.* --fix ────────────────────────────────────────────────────────


class TestStateLockFix:
    def test_removes_stale_lock(self, tmp_path):
        lock_file = _mk_lock(
            tmp_path,
            {"pid": 99999999, "verb": "swab", "started_at": 0},
        )
        assert lock_file.exists()
        r = StateLockCheck().fix(DoctorContext(project_root=tmp_path, apply_fix=True))
        assert r.status is DoctorStatus.OK
        assert not lock_file.exists()

    def test_removes_unreadable_sidecar(self, tmp_path):
        lock_dir = tmp_path / LOCK_DIR
        lock_dir.mkdir()
        lock_file = lock_dir / LOCK_FILE
        lock_file.write_text("garbage")
        r = StateLockCheck().fix(DoctorContext(project_root=tmp_path, apply_fix=True))
        assert r.status is DoctorStatus.OK
        assert not lock_file.exists()

    def test_refuses_live_lock(self, tmp_path):
        """--fix must never delete a lock held by a real running sm."""
        lock_file = _mk_lock(
            tmp_path,
            {"pid": os.getpid(), "verb": "swab", "started_at": time.time()},
        )
        with patch("slopmop.core.lock._pid_looks_like_sm", return_value=True):
            r = StateLockCheck().fix(
                DoctorContext(project_root=tmp_path, apply_fix=True)
            )
        assert r.status is DoctorStatus.WARN
        assert "refusing" in r.summary.lower()
        assert lock_file.exists()  # untouched

    def test_no_lock_is_noop_ok(self, tmp_path):
        r = StateLockCheck().fix(DoctorContext(project_root=tmp_path, apply_fix=True))
        assert r.status is DoctorStatus.OK


class TestStateDirFix:
    def test_creates_missing_dir(self, tmp_path):
        state = tmp_path / STATE_DIR
        assert not state.exists()
        r = StateDirCheck().fix(DoctorContext(project_root=tmp_path, apply_fix=True))
        assert r.status is DoctorStatus.OK
        assert state.is_dir()

    @pytest.mark.skipif(
        sys.platform == "win32", reason="chmod semantics differ on Windows"
    )
    def test_repairs_unwritable_dir(self, tmp_path):
        state = tmp_path / STATE_DIR
        state.mkdir()
        state.chmod(0o500)
        try:
            r = StateDirCheck().fix(
                DoctorContext(project_root=tmp_path, apply_fix=True)
            )
            assert r.status is DoctorStatus.OK
            # Verify the repair actually added write — re-run the check.
            post = StateDirCheck().run(DoctorContext(project_root=tmp_path))
            assert post.status is DoctorStatus.OK
        finally:
            state.chmod(0o700)

    @pytest.mark.skipif(
        not hasattr(os, "getuid"), reason="uid ownership check is POSIX-only"
    )
    def test_refuses_chmod_when_not_owner(self, tmp_path):
        state = tmp_path / STATE_DIR
        state.mkdir()
        fake_stat = MagicMock()
        fake_stat.st_uid = os.getuid() + 1  # someone else
        fake_stat.st_mode = stat.S_IFDIR | 0o500
        with patch.object(Path, "stat", return_value=fake_stat):
            r = StateDirCheck().fix(
                DoctorContext(project_root=tmp_path, apply_fix=True)
            )
        assert r.status is DoctorStatus.FAIL
        assert "sudo chown" in r.fix_hint


class TestStateConfigFix:
    def test_restores_from_newest_backup(self, tmp_path):
        cfg = tmp_path / CONFIG_FILE
        cfg.write_text("broken{{")

        older = tmp_path / STATE_DIR / "backups" / "old"
        newer = tmp_path / STATE_DIR / "backups" / "new"
        older.mkdir(parents=True)
        newer.mkdir(parents=True)
        (older / CONFIG_FILE).write_text(json.dumps({"v": "old"}))
        newer_backup = newer / CONFIG_FILE
        newer_backup.write_text(json.dumps({"v": "new"}))
        # Ensure mtime ordering is unambiguous.
        os.utime(older / CONFIG_FILE, (1000, 1000))
        os.utime(newer_backup, (9000, 9000))

        r = StateConfigCheck().fix(DoctorContext(project_root=tmp_path, apply_fix=True))
        assert r.status is DoctorStatus.OK
        assert json.loads(cfg.read_text()) == {"v": "new"}
        # Broken file moved aside, not deleted.
        aside = Path(r.data["moved_aside"])
        assert aside.exists()
        assert "broken" in aside.name

    def test_no_backup_fails_without_touching_file(self, tmp_path):
        cfg = tmp_path / CONFIG_FILE
        cfg.write_text("broken{{")
        r = StateConfigCheck().fix(DoctorContext(project_root=tmp_path, apply_fix=True))
        assert r.status is DoctorStatus.FAIL
        assert cfg.read_text() == "broken{{"  # untouched

    def test_already_valid_is_noop(self, tmp_path):
        cfg = tmp_path / CONFIG_FILE
        cfg.write_text(json.dumps({"ok": True}))
        r = StateConfigCheck().fix(DoctorContext(project_root=tmp_path, apply_fix=True))
        assert r.status is DoctorStatus.OK
        assert "already parses" in r.summary
        assert json.loads(cfg.read_text()) == {"ok": True}

    def test_no_config_is_noop(self, tmp_path):
        r = StateConfigCheck().fix(DoctorContext(project_root=tmp_path, apply_fix=True))
        assert r.status is DoctorStatus.OK


class TestBackupDiscovery:
    def test_finds_newest_by_mtime(self, tmp_path):
        a = tmp_path / STATE_DIR / "backups" / "a"
        b = tmp_path / STATE_DIR / "backups" / "b"
        for d in (a, b):
            d.mkdir(parents=True)
            (d / CONFIG_FILE).write_text("{}")
        os.utime(a / CONFIG_FILE, (1000, 1000))
        os.utime(b / CONFIG_FILE, (5000, 5000))
        assert _find_newest_config_backup(tmp_path) == b / CONFIG_FILE

    def test_none_when_no_backups_dir(self, tmp_path):
        assert _find_newest_config_backup(tmp_path) is None


class TestFormatAge:
    def test_seconds(self):
        assert _format_age(45) == "45s"

    def test_minutes(self):
        assert _format_age(300) == "5m"

    def test_hours(self):
        assert _format_age(7500) == "2.1h"

    def test_negative_clamps_to_zero(self):
        assert _format_age(-10) == "0s"
