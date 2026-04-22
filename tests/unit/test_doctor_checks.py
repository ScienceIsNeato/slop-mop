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
from slopmop.doctor.gate_preflight import GatePreflightRecord
from slopmop.doctor.project_env import (
    ProjectGateRunnabilityCheck,
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
    GateDiagnosticsCheck,
    InstallModeCheck,
    SmPipCheck,
    ToolInventoryCheck,
    _check_version_constraint,
    _group_install_hints,
    _parse_tool_version,
    _reinstall_hint,
)
from slopmop.doctor.state import (
    StateConfigCheck,
    StateConfigGateRefsCheck,
    StateDirCheck,
    StateLockCheck,
    _find_newest_config_backup,
    _format_seconds_age,
)

# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def ctx(tmp_path: Path) -> DoctorContext:  # noqa: ambiguity-mine
    return DoctorContext(project_root=tmp_path)


def _mk_lock(root: Path, meta: dict) -> Path:  # noqa: ambiguity-mine
    lock_dir = root / LOCK_DIR
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / LOCK_FILE
    lock_file.write_text(json.dumps(meta))
    return lock_file


from tests.unit.conftest import mk_python_project as _mk_python_project, mk_project_venv as _mk_project_venv


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

    def test_collision_warns(self, monkeypatch, tmp_path):
        # Use a project_root that does NOT contain the sm binaries
        # so they aren't treated as project-owned.
        project_root = tmp_path / "project"
        project_root.mkdir()
        ext_ctx = DoctorContext(project_root=project_root)
        a, b = tmp_path / "a", tmp_path / "b"
        for d in (a, b):
            d.mkdir()
            sm = d / "sm"
            sm.write_text("#!/bin/sh\n")
            sm.chmod(0o755)
        monkeypatch.setenv("PATH", f"{a}{os.pathsep}{b}")
        r = SmResolutionCheck().run(ext_ctx)
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


class TestProjectGateRunnabilityCheck:
    def test_fails_when_any_applicable_gate_is_blocked(self, ctx):
        records = [
            GatePreflightRecord(
                gate="deceptiveness:bogus-tests.js",
                display_name="bogus-tests.js",
                enabled=True,
                applicable=True,
                skip_reason="",
                config_fingerprint="one",
                missing_tools=(),
            ),
            GatePreflightRecord(
                gate="overconfidence:coverage-gaps.js",
                display_name="coverage-gaps.js",
                enabled=True,
                applicable=True,
                skip_reason="",
                config_fingerprint="two",
                missing_tools=("deno",),
            ),
        ]
        with patch(
            "slopmop.doctor.project_env.gather_gate_preflight_records",
            return_value=records,
        ):
            result = ProjectGateRunnabilityCheck().run(ctx)
        assert result.status is DoctorStatus.FAIL
        assert "blocked before refit can start" in result.summary
        assert "coverage-gaps.js" in result.detail

    def test_warns_when_gate_is_disabled_pending_decision(self, ctx):
        records = [
            GatePreflightRecord(
                gate="overconfidence:coverage-gaps.js",
                display_name="coverage-gaps.js",
                enabled=False,
                applicable=True,
                skip_reason="",
                config_fingerprint="two",
                missing_tools=(),
            )
        ]
        with patch(
            "slopmop.doctor.project_env.gather_gate_preflight_records",
            return_value=records,
        ):
            result = ProjectGateRunnabilityCheck().run(ctx)
        assert result.status is DoctorStatus.WARN
        assert "disabled and need an explicit refit decision" in result.summary


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

    def test_tool_seen_by_multiple_gates_counted_once(self, ctx):
        """A tool that guards several gates shows up once, not N times."""
        fake_required = [
            ("black", "gate.format", "install-cmd"),
            ("black", "gate.lint", "install-cmd"),
            ("black", "gate.complex", "install-cmd"),
        ]
        with (
            patch("slopmop.doctor.sm_env.REQUIRED_TOOLS", fake_required),
            patch("slopmop.doctor.sm_env.find_tool", return_value=None),
        ):
            r = ToolInventoryCheck().run(ctx)
        assert r.status is DoctorStatus.FAIL
        # Previously overcounted — tuple-membership check on a tuple
        # that included the per-gate check_name never matched.
        assert len(r.data["missing"]) == 1
        assert r.data["missing"][0]["tool"] == "black"

    def test_validator_rejects_and_missing_both_reported(self, ctx):
        """Mixed failures: both classes must surface in one report.

        Early-returning on validator_rejects hid missing tools — user
        would fix the validator issue, re-run, then discover the missing
        ones.  Wasteful.  Report both.
        """
        from slopmop.subprocess.validator import SecurityError

        fake_required = [
            ("black", "gate.a", "pipx install slopmop[lint]"),
            ("notatool", "gate.b", "pipx install slopmop[misc]"),
        ]

        def fake_validate(self, cmd):
            raise SecurityError(f"Executable '{cmd[0]}' not in whitelist")

        def fake_find(name, root):
            # black resolves (then gets rejected); notatool doesn't.
            return "/bin/black" if name == "black" else None

        with (
            patch("slopmop.doctor.sm_env.REQUIRED_TOOLS", fake_required),
            patch("slopmop.doctor.sm_env.find_tool", side_effect=fake_find),
            patch(
                "slopmop.subprocess.validator.CommandValidator.validate",
                fake_validate,
            ),
        ):
            r = ToolInventoryCheck().run(ctx)

        assert r.status is DoctorStatus.FAIL
        assert "rejected" in r.summary and "missing" in r.summary
        # Both sections present in human detail.
        assert "REJECTED by the subprocess allowlist" in r.detail
        assert "Missing tools block these gates" in r.detail
        # And in the machine data.
        assert len(r.data["validator_rejects"]) == 1
        assert len(r.data["missing"]) == 1
        # Fix hint covers both.
        assert "slopmop bug" in r.fix_hint
        assert "pipx install slopmop[misc]" in r.fix_hint


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

    def test_deno_project_ok_when_binary_on_path(self, tmp_path):
        (tmp_path / "deno.json").write_text("{}")
        with patch(
            "slopmop.doctor.project_env.shutil.which",
            return_value="/usr/local/bin/deno",
        ):
            r = ProjectJsDepsCheck().run(DoctorContext(project_root=tmp_path))
        assert r.status is DoctorStatus.OK
        assert r.data["runtime"] == "deno"
        assert r.data["deno_binary"] == "/usr/local/bin/deno"

    def test_deno_project_warns_when_binary_missing(self, tmp_path):
        (tmp_path / "deno.json").write_text("{}")
        with patch("slopmop.doctor.project_env.shutil.which", return_value=None):
            r = ProjectJsDepsCheck().run(DoctorContext(project_root=tmp_path))
        assert r.status is DoctorStatus.WARN
        assert "not found" in r.summary
        assert "Install Deno" in r.fix_hint

    def test_deno_jsonc_also_detected(self, tmp_path):
        (tmp_path / "deno.jsonc").write_text("{}")
        with patch("slopmop.doctor.project_env.shutil.which", return_value="/opt/deno"):
            r = ProjectJsDepsCheck().run(DoctorContext(project_root=tmp_path))
        assert r.status is DoctorStatus.OK
        assert r.data["runtime"] == "deno"

    def test_deno_takes_priority_over_node(self, tmp_path):
        """When both deno.json and package.json exist, prefer Deno path."""
        (tmp_path / "deno.json").write_text("{}")
        (tmp_path / "package.json").write_text("{}")
        with patch(
            "slopmop.doctor.project_env.shutil.which",
            return_value="/usr/local/bin/deno",
        ):
            r = ProjectJsDepsCheck().run(DoctorContext(project_root=tmp_path))
        assert r.data["runtime"] == "deno"


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
        assert r.can_fix is False  # --fix refuses live locks; offering it misleads

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

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="chmod semantics differ on Windows; os.access ignores ACLs for admin users",
    )
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
    def test_clears_stale_lock_metadata(self, tmp_path):
        lock_file = _mk_lock(
            tmp_path,
            {"pid": 99999999, "verb": "swab", "started_at": 0},
        )
        assert lock_file.exists()
        r = StateLockCheck().fix(DoctorContext(project_root=tmp_path, apply_fix=True))
        assert r.status is DoctorStatus.OK
        # File preserved (inode kept for flock safety), metadata cleared
        assert lock_file.exists()
        assert json.loads(lock_file.read_text()) == {}

    def test_clears_unreadable_sidecar(self, tmp_path):
        lock_dir = tmp_path / LOCK_DIR
        lock_dir.mkdir()
        lock_file = lock_dir / LOCK_FILE
        lock_file.write_text("garbage")
        r = StateLockCheck().fix(DoctorContext(project_root=tmp_path, apply_fix=True))
        assert r.status is DoctorStatus.OK
        # File preserved (inode kept for flock safety), metadata cleared
        assert lock_file.exists()
        assert json.loads(lock_file.read_text()) == {}

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
        assert r.can_fix is False  # refusal result must not re-offer the fix

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
        assert r.can_fix is False  # requires elevation; sm can't auto-fix


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
        assert r.can_fix is False  # nothing to restore; re-offering fix is misleading

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
        assert _format_seconds_age(45) == "45s"

    def test_minutes(self):
        assert _format_seconds_age(300) == "5m"

    def test_hours(self):
        assert _format_seconds_age(7500) == "2.1h"

    def test_negative_clamps_to_zero(self):
        assert _format_seconds_age(-10) == "0s"


# ── StateConfigGateRefsCheck ─────────────────────────────────────────────────


class TestStateConfigGateRefsCheck:
    """Tests for the gate-ref validation doctor check."""

    def _write_config(self, tmp_path: Path, data: dict) -> None:
        from slopmop.core.config import CONFIG_FILE

        (tmp_path / CONFIG_FILE).write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )

    def _run(self, tmp_path: Path) -> object:
        ctx = DoctorContext(project_root=tmp_path)
        return StateConfigGateRefsCheck().run(ctx)

    def test_skip_when_no_config(self, tmp_path: Path):
        r = self._run(tmp_path)
        assert r.status is DoctorStatus.SKIP

    def test_skip_when_config_unparseable(self, tmp_path: Path):
        from slopmop.core.config import CONFIG_FILE

        (tmp_path / CONFIG_FILE).write_text("not json", encoding="utf-8")
        r = self._run(tmp_path)
        assert r.status is DoctorStatus.SKIP

    def test_ok_when_empty_config(self, tmp_path: Path):
        self._write_config(tmp_path, {})
        r = self._run(tmp_path)
        assert r.status is DoctorStatus.OK

    def test_ok_when_all_refs_valid(self, tmp_path: Path):
        # Use a gate that definitely exists: laziness:sloppy-formatting.py
        from slopmop.checks import ensure_checks_registered
        from slopmop.core.registry import get_registry

        ensure_checks_registered()
        valid_gate = next(iter(get_registry().list_checks()))
        self._write_config(tmp_path, {"disabled_gates": [valid_gate]})
        r = self._run(tmp_path)
        assert r.status is DoctorStatus.OK

    def test_warn_on_unknown_disabled_gate(self, tmp_path: Path):
        self._write_config(
            tmp_path, {"disabled_gates": ["myopia:nonexistent-gate-xyz"]}
        )
        r = self._run(tmp_path)
        assert r.status is DoctorStatus.WARN
        assert "myopia:nonexistent-gate-xyz" in (r.detail or "")

    def test_warn_on_unknown_flat_config_key(self, tmp_path: Path):
        self._write_config(
            tmp_path, {"category:completely-bogus-gate": {"enabled": False}}
        )
        r = self._run(tmp_path)
        assert r.status is DoctorStatus.WARN

    def test_ok_with_hierarchical_config(self, tmp_path: Path):
        """Hierarchical category→gates dict: extract refs and validate them."""
        # Use a real gate name that will be in the registry.
        from slopmop.checks import ensure_checks_registered
        from slopmop.core.registry import get_registry

        ensure_checks_registered()
        registry = get_registry()
        # Pick any known gate name to construct a valid hierarchical ref.
        known = next(iter(registry.list_checks()))
        if ":" not in known:
            return  # skip if no colon gates registered
        category, gate = known.split(":", 1)
        self._write_config(tmp_path, {category: {"gates": {gate: {"enabled": True}}}})
        r = self._run(tmp_path)
        assert r.status is DoctorStatus.OK

    def test_warn_hierarchical_unknown_gate(self, tmp_path: Path):
        """Hierarchical config with a bogus gate name should WARN."""
        self._write_config(
            tmp_path, {"myopia": {"gates": {"totally-made-up-gate-xyz": {}}}}
        )
        r = self._run(tmp_path)
        assert r.status is DoctorStatus.WARN


# ── sm_env version helpers ────────────────────────────────────────────────


class TestParseToolVersion:
    def test_extracts_version_from_stdout(self):
        pass

        with patch(
            "subprocess.run",
            return_value=MagicMock(
                stdout="black, 23.1.0 (compiled: yes)\n", stderr="", returncode=0
            ),
        ):
            result = _parse_tool_version("/usr/bin/black")
        assert result == "23.1.0"

    def test_extracts_version_from_stderr(self):
        with patch(
            "subprocess.run",
            return_value=MagicMock(stdout="", stderr="mypy 1.4.1\n", returncode=1),
        ):
            result = _parse_tool_version("/usr/bin/mypy")
        assert result == "1.4.1"

    def test_returns_none_on_os_error(self):
        with patch("subprocess.run", side_effect=OSError("not found")):
            result = _parse_tool_version("/no/such/tool")
        assert result is None

    def test_returns_none_on_timeout(self):
        import subprocess

        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=5)
        ):
            result = _parse_tool_version("/slow/tool")
        assert result is None

    def test_returns_none_when_no_version_in_output(self):
        with patch(
            "subprocess.run",
            return_value=MagicMock(
                stdout="no version info here", stderr="", returncode=0
            ),
        ):
            result = _parse_tool_version("/usr/bin/weird")
        assert result is None


class TestCheckVersionConstraint:
    def test_satisfied_constraint_returns_none(self):
        with patch("slopmop.doctor.sm_env._parse_tool_version", return_value="23.1.0"):
            result = _check_version_constraint("black", "/bin/black", ">=22.0")
        assert result is None

    def test_violated_constraint_returns_message(self):
        with patch("slopmop.doctor.sm_env._parse_tool_version", return_value="21.9.0"):
            result = _check_version_constraint("black", "/bin/black", ">=22.0")
        assert result is not None
        assert "21.9.0" in result
        assert ">=22.0" in result

    def test_returns_none_when_version_unreadable(self):
        with patch("slopmop.doctor.sm_env._parse_tool_version", return_value=None):
            result = _check_version_constraint("black", "/bin/black", ">=22.0")
        assert result is None

    def test_returns_none_when_packaging_unavailable(self):
        with (
            patch("slopmop.doctor.sm_env._parse_tool_version", return_value="1.0.0"),
            patch.dict(
                "sys.modules", {"packaging": None, "packaging.specifiers": None}
            ),
        ):
            # packaging import fails → should return None silently
            result = _check_version_constraint("black", "/bin/black", ">=22.0")
        # result can be None or raise — both acceptable; just shouldn't crash caller
        assert result is None or isinstance(result, str)


class TestToolInventoryVersionViolations:
    """ToolInventoryCheck covers version-violation reporting paths."""

    def test_version_violation_reported_as_warn(self, ctx):
        """When tool is found but version constraint fails → WARN (not FAIL)."""
        from slopmop.checks.base import BaseCheck

        class FakeGate(BaseCheck):
            name = "test:fake-version-gate"
            required_tools = ["black"]
            required_tool_versions = {"black": ">=999.0"}

            def run(self, project_root, config=None):  # type: ignore[override]
                return self._pass()

        with (
            patch(
                "slopmop.doctor.sm_env.find_tool",
                side_effect=lambda name, root: f"/usr/local/bin/{name}",
            ),
            patch(
                "slopmop.doctor.sm_env._check_version_constraint",
                return_value="found 23.1.0, requires >=999.0",
            ),
            patch(
                "slopmop.core.registry.get_registry",
                return_value=MagicMock(
                    list_checks=lambda: ["test:fake-version-gate"],
                    _check_classes={"test:fake-version-gate": FakeGate},
                ),
            ),
        ):
            r = ToolInventoryCheck().run(ctx)
        # No missing/rejected tools but a version violation → WARN
        assert r.status is DoctorStatus.WARN
        assert "version constraint" in r.summary


# ── sm_env.GateDiagnosticsCheck ──────────────────────────────────────────


class TestGateDiagnosticsCheck:
    def _make_concrete_gate_class(self, base_cls, overrides: dict):
        """Create a concrete BaseCheck subclass with all abstract methods filled in."""
        from slopmop.checks.base import Flaw, GateCategory

        attrs = {
            "name": "test:stub",
            "required_tools": [],
            "display_name": property(lambda self: "Test Gate"),
            "category": property(lambda self: GateCategory.GENERAL),
            "flaw": property(lambda self: Flaw("test", "🔬", "Test")),
            "is_applicable": lambda self, root: True,
            "run": lambda self, root: self._pass(),
        }
        attrs.update(overrides)
        return type("ConcreteGate", (base_cls,), attrs)

    def test_ok_when_no_gates_override_diagnose(self, ctx):
        from slopmop.checks.base import BaseCheck

        NoOpGate = self._make_concrete_gate_class(BaseCheck, {"name": "test:noop"})

        with patch(
            "slopmop.core.registry.get_registry",
            return_value=MagicMock(
                _check_classes={"test:noop": NoOpGate},
            ),
        ):
            r = GateDiagnosticsCheck().run(ctx)
        assert r.status is DoctorStatus.OK

    def test_warn_when_gate_diagnose_returns_warn(self, ctx):
        from slopmop.checks.base import BaseCheck, GateDiagnosticResult

        DiagnosticGate = self._make_concrete_gate_class(
            BaseCheck,
            {
                "name": "test:diag-warn",
                "diagnose": lambda self, root: [
                    GateDiagnosticResult(severity="warn", summary="low disk space")
                ],
            },
        )

        with patch(
            "slopmop.core.registry.get_registry",
            return_value=MagicMock(
                _check_classes={"test:diag-warn": DiagnosticGate},
            ),
        ):
            r = GateDiagnosticsCheck().run(ctx)
        assert r.status is DoctorStatus.WARN
        assert "low disk space" in (r.detail or "")

    def test_fail_when_gate_diagnose_returns_fail(self, ctx):
        from slopmop.checks.base import BaseCheck, GateDiagnosticResult

        DiagnosticGate = self._make_concrete_gate_class(
            BaseCheck,
            {
                "name": "test:diag-fail",
                "diagnose": lambda self, root: [
                    GateDiagnosticResult(severity="fail", summary="no .coverage file")
                ],
            },
        )

        with patch(
            "slopmop.core.registry.get_registry",
            return_value=MagicMock(
                _check_classes={"test:diag-fail": DiagnosticGate},
            ),
        ):
            r = GateDiagnosticsCheck().run(ctx)
        assert r.status is DoctorStatus.FAIL
        assert "no .coverage file" in (r.detail or "")

    def test_exception_in_diagnose_is_skipped(self, ctx):
        from slopmop.checks.base import BaseCheck

        def _crash_diagnose(self, root):
            raise RuntimeError("oops")

        CrashingGate = self._make_concrete_gate_class(
            BaseCheck,
            {
                "name": "test:crash",
                "diagnose": _crash_diagnose,
            },
        )

        with patch(
            "slopmop.core.registry.get_registry",
            return_value=MagicMock(
                _check_classes={"test:crash": CrashingGate},
            ),
        ):
            r = GateDiagnosticsCheck().run(ctx)
        # The crashing gate is silently skipped — overall result is OK
        assert r.status is DoctorStatus.OK
