"""Tests for the doctor CLI command.

Covers parser wiring, environment checks, per-gate readiness checks,
orchestration (run_doctor), JSON output, --list-checks, --fix, and
the config-enable hook that triggers doctor readiness.
"""

import json
import os
import sys
from collections import namedtuple
from pathlib import Path
from unittest.mock import MagicMock, patch

from slopmop.cli.doctor import (
    DoctorCheckResult,
    DoctorReport,
    DoctorStatus,
    _check_config,
    _check_gate_readiness,
    _check_platform,
    _check_slopmop_dir,
    _check_sm_resolution,
    _check_stale_lock,
    _is_gate_enabled,
    check_single_gate_readiness,
    run_doctor,
)
from slopmop.sm import create_parser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VersionInfo = namedtuple(
    "version_info", ["major", "minor", "micro", "releaselevel", "serial"]
)


def _empty_report() -> DoctorReport:
    return DoctorReport()


def _mock_check(
    full_name="test:gate",
    tool_context_value="sm_tool",
    required_tools=None,
    is_applicable=True,
    install_hint="pip",
):
    """Build a mock gate check for doctor tests."""
    from slopmop.checks.base import ToolContext

    ctx_map = {
        "pure": ToolContext.PURE,
        "sm_tool": ToolContext.SM_TOOL,
        "project": ToolContext.PROJECT,
        "node": ToolContext.NODE,
    }
    check = MagicMock()
    check.full_name = full_name
    check.tool_context = ctx_map.get(tool_context_value, ToolContext.SM_TOOL)
    check.required_tools = required_tools or []
    check.install_hint = install_hint
    check.is_applicable.return_value = is_applicable
    check.skip_reason.return_value = "Not applicable"
    return check


def _mock_registry(gate_names=None, checks=None):
    """Build a mock registry."""
    reg = MagicMock()
    reg.list_checks.return_value = gate_names or []

    if checks:
        check_map = {c.full_name: c for c in checks}
        reg.get_check.side_effect = lambda name, _cfg: check_map.get(name)
    else:
        reg.get_check.return_value = None

    return reg


# ===========================================================================
# Parser tests
# ===========================================================================


class TestDoctorParser:
    """Test that the doctor subcommand parser is wired correctly."""

    def test_doctor_parses_with_defaults(self):
        parser = create_parser()
        args = parser.parse_args(["doctor"])
        assert args.verb == "doctor"
        # nargs="*" produces [] when no positional args given
        assert args.checks == []
        assert args.fix is False
        assert args.list_checks is False
        assert args.verbose is False
        assert args.quiet is False

    def test_doctor_fix(self):
        parser = create_parser()
        args = parser.parse_args(["doctor", "--fix"])
        assert args.fix is True

    def test_doctor_list_checks(self):
        parser = create_parser()
        args = parser.parse_args(["doctor", "--list-checks"])
        assert args.list_checks is True

    def test_doctor_json(self):
        parser = create_parser()
        args = parser.parse_args(["doctor", "--json"])
        assert args.json_output is True

    def test_doctor_no_json(self):
        parser = create_parser()
        args = parser.parse_args(["doctor", "--no-json"])
        assert args.json_output is False

    def test_doctor_specific_checks(self):
        parser = create_parser()
        args = parser.parse_args(["doctor", "laziness:dead-code.py", "config"])
        assert args.checks == ["laziness:dead-code.py", "config"]

    def test_doctor_project_root(self):
        parser = create_parser()
        args = parser.parse_args(["doctor", "--project-root", "/tmp/x"])
        assert args.project_root == "/tmp/x"

    def test_doctor_verbose(self):
        parser = create_parser()
        args = parser.parse_args(["doctor", "-v"])
        assert args.verbose is True

    def test_doctor_quiet(self):
        parser = create_parser()
        args = parser.parse_args(["doctor", "-q"])
        assert args.quiet is True


# ===========================================================================
# DoctorReport / DoctorCheckResult data tests
# ===========================================================================


class TestDoctorDataTypes:
    def test_report_no_failures(self):
        report = DoctorReport()
        report.add(DoctorCheckResult(name="a", status=DoctorStatus.OK, summary="ok"))
        assert not report.has_failures
        assert report.exit_code == 0

    def test_report_with_failure(self):
        report = DoctorReport()
        report.add(DoctorCheckResult(name="a", status=DoctorStatus.FAIL, summary="bad"))
        assert report.has_failures
        assert report.exit_code == 1

    def test_report_with_warning(self):
        report = DoctorReport()
        report.add(DoctorCheckResult(name="a", status=DoctorStatus.WARN, summary="eh"))
        assert report.has_warnings
        assert not report.has_failures
        assert report.exit_code == 0

    def test_report_to_dict(self):
        report = DoctorReport(
            sm_version="0.10.1",
            python_version="3.11.5",
            platform_info="darwin arm64",
            project_root="/tmp",
        )
        report.add(DoctorCheckResult(name="a", status=DoctorStatus.OK, summary="ok"))
        d = report.to_dict()
        assert d["sm_version"] == "0.10.1"
        assert len(d["results"]) == 1
        assert d["results"][0]["status"] == "ok"

    def test_check_result_to_dict_minimal(self):
        r = DoctorCheckResult(name="x", status=DoctorStatus.OK, summary="fine")
        d = r.to_dict()
        assert d == {"name": "x", "status": "ok", "summary": "fine"}

    def test_check_result_to_dict_full(self):
        r = DoctorCheckResult(
            name="x",
            status=DoctorStatus.FAIL,
            summary="bad",
            details="detail",
            suggested_actions=["fix it"],
            gate="laziness:foo",
        )
        d = r.to_dict()
        assert d["details"] == "detail"
        assert d["suggested_actions"] == ["fix it"]
        assert d["gate"] == "laziness:foo"


# ===========================================================================
# Environment check tests
# ===========================================================================


class TestCheckPlatform:
    def test_ok_on_current_python(self):
        report = _empty_report()
        _check_platform(report)
        assert len(report.results) == 1
        assert report.results[0].name == "platform"
        assert report.results[0].status == DoctorStatus.OK
        assert report.sm_version != ""

    def test_fail_on_old_python(self):
        report = _empty_report()
        fake_vi = _VersionInfo(3, 9, 0, "final", 0)
        with patch.object(sys, "version_info", fake_vi):
            _check_platform(report)
        assert report.results[0].status == DoctorStatus.FAIL
        assert "3.10" in report.results[0].summary


class TestCheckSmResolution:
    def test_ok_reports_path(self):
        report = _empty_report()
        _check_sm_resolution(report)
        assert report.results[0].name == "sm-resolution"
        assert report.results[0].status in (DoctorStatus.OK, DoctorStatus.WARN)


class TestCheckConfig:
    def test_ok_on_valid_json(self, tmp_path):
        config = tmp_path / ".sb_config.json"
        config.write_text('{"disabled_gates": []}')
        report = _empty_report()
        _check_config(report, tmp_path)
        assert report.results[0].status == DoctorStatus.OK

    def test_warn_on_missing(self, tmp_path):
        report = _empty_report()
        _check_config(report, tmp_path)
        assert report.results[0].status == DoctorStatus.WARN

    def test_fail_on_malformed_json(self, tmp_path):
        config = tmp_path / ".sb_config.json"
        config.write_text("{not valid json")
        report = _empty_report()
        _check_config(report, tmp_path)
        assert report.results[0].status == DoctorStatus.FAIL

    def test_respects_sb_config_file_env(self, tmp_path):
        custom_config = tmp_path / "custom.json"
        custom_config.write_text('{"ok": true}')
        report = _empty_report()
        with patch.dict(os.environ, {"SB_CONFIG_FILE": str(custom_config)}):
            _check_config(report, tmp_path)
        assert report.results[0].status == DoctorStatus.OK


class TestCheckSlopmopDir:
    def test_ok_when_exists_and_writable(self, tmp_path):
        (tmp_path / ".slopmop").mkdir()
        report = _empty_report()
        _check_slopmop_dir(report, tmp_path, fix=False)
        assert report.results[0].status == DoctorStatus.OK

    def test_warn_when_missing_no_fix(self, tmp_path):
        report = _empty_report()
        _check_slopmop_dir(report, tmp_path, fix=False)
        assert report.results[0].status == DoctorStatus.WARN

    def test_fixed_when_missing_with_fix(self, tmp_path):
        report = _empty_report()
        _check_slopmop_dir(report, tmp_path, fix=True)
        assert report.results[0].status == DoctorStatus.FIXED
        assert (tmp_path / ".slopmop").exists()

    def test_fail_when_not_writable(self, tmp_path):
        slopmop_dir = tmp_path / ".slopmop"
        slopmop_dir.mkdir()
        report = _empty_report()
        with patch("os.access", return_value=False):
            _check_slopmop_dir(report, tmp_path, fix=False)
        assert report.results[0].status == DoctorStatus.FAIL


class TestCheckStaleLock:
    def test_ok_when_no_lock(self, tmp_path):
        (tmp_path / ".slopmop").mkdir()
        report = _empty_report()
        _check_stale_lock(report, tmp_path, fix=False)
        assert report.results[0].status == DoctorStatus.OK
        assert "No lock file" in report.results[0].summary

    def test_ok_when_lock_empty(self, tmp_path):
        lock_dir = tmp_path / ".slopmop"
        lock_dir.mkdir()
        (lock_dir / "sm.lock").write_text("{}")
        report = _empty_report()
        _check_stale_lock(report, tmp_path, fix=False)
        assert report.results[0].status == DoctorStatus.OK

    def test_warn_stale_lock_dead_pid_no_fix(self, tmp_path):
        lock_dir = tmp_path / ".slopmop"
        lock_dir.mkdir()
        (lock_dir / "sm.lock").write_text('{"pid": 999999, "verb": "swab"}')
        report = _empty_report()
        with patch("slopmop.core.lock._pid_alive", return_value=False):
            _check_stale_lock(report, tmp_path, fix=False)
        assert report.results[0].status == DoctorStatus.WARN
        assert "999999" in report.results[0].summary

    def test_fixed_stale_lock_dead_pid_with_fix(self, tmp_path):
        lock_dir = tmp_path / ".slopmop"
        lock_dir.mkdir()
        lock_path = lock_dir / "sm.lock"
        lock_path.write_text('{"pid": 999999, "verb": "swab"}')
        report = _empty_report()
        with patch("slopmop.core.lock._pid_alive", return_value=False):
            _check_stale_lock(report, tmp_path, fix=True)
        assert report.results[0].status == DoctorStatus.FIXED
        assert not lock_path.exists()

    def test_warn_lock_held_by_live_pid(self, tmp_path):
        lock_dir = tmp_path / ".slopmop"
        lock_dir.mkdir()
        (lock_dir / "sm.lock").write_text('{"pid": 12345, "verb": "scour"}')
        report = _empty_report()
        with patch("slopmop.core.lock._pid_alive", return_value=True):
            _check_stale_lock(report, tmp_path, fix=False)
        assert report.results[0].status == DoctorStatus.WARN
        assert "still running" in report.results[0].summary


# ===========================================================================
# Per-gate readiness tests
# ===========================================================================


class TestGateReadiness:
    def test_pure_gate_always_ok(self):
        report = _empty_report()
        check = _mock_check(tool_context_value="pure")
        _check_gate_readiness(report, check, Path("/tmp"))
        assert report.results[0].status == DoctorStatus.OK
        assert "Pure analysis" in report.results[0].summary

    def test_sm_tool_all_found(self):
        report = _empty_report()
        check = _mock_check(required_tools=["vulture"])
        with patch("slopmop.cli.doctor.find_tool", return_value="/usr/bin/vulture"):
            _check_gate_readiness(report, check, Path("/tmp"))
        assert report.results[0].status == DoctorStatus.OK
        assert "vulture" in report.results[0].summary

    def test_sm_tool_missing(self):
        report = _empty_report()
        check = _mock_check(required_tools=["vulture", "radon"])
        with patch(
            "slopmop.cli.doctor.find_tool", side_effect=[None, "/usr/bin/radon"]
        ):
            _check_gate_readiness(report, check, Path("/tmp"))
        assert report.results[0].status == DoctorStatus.FAIL
        assert "vulture" in report.results[0].summary
        # Default install_hint is "pip", so suggested action should use pip
        assert any("pip install" in a for a in report.results[0].suggested_actions)

    def test_sm_tool_missing_non_pip_hint(self):
        report = _empty_report()
        check = _mock_check(
            required_tools=["flutter"],
            install_hint="path",
            full_name="laziness:formatting.dart",
        )
        with patch("slopmop.cli.doctor.find_tool", return_value=None):
            _check_gate_readiness(report, check, Path("/tmp"))
        assert report.results[0].status == DoctorStatus.FAIL
        # Non-pip hint should NOT suggest pip install
        assert not any("pip install" in a for a in report.results[0].suggested_actions)
        assert any("Install flutter" in a for a in report.results[0].suggested_actions)

    def test_sm_tool_empty_required_tools(self):
        report = _empty_report()
        check = _mock_check(required_tools=[])
        _check_gate_readiness(report, check, Path("/tmp"))
        assert report.results[0].status == DoctorStatus.OK
        assert "no specific tools" in report.results[0].summary

    def test_project_gate_with_venv(self, tmp_path):
        # Create a fake venv
        (tmp_path / "venv" / "bin").mkdir(parents=True)
        (tmp_path / "venv" / "bin" / "python").touch()
        report = _empty_report()
        check = _mock_check(tool_context_value="project")
        _check_gate_readiness(report, check, tmp_path)
        assert report.results[0].status == DoctorStatus.OK

    def test_project_gate_without_venv(self, tmp_path):
        report = _empty_report()
        check = _mock_check(tool_context_value="project")
        _check_gate_readiness(report, check, tmp_path)
        # PROJECT gates warn+skip at runtime, so doctor reports WARN not FAIL.
        assert report.results[0].status == DoctorStatus.WARN
        assert "virtual environment" in report.results[0].summary

    def test_node_gate_with_package_and_modules(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "node_modules").mkdir()
        report = _empty_report()
        check = _mock_check(tool_context_value="node")
        _check_gate_readiness(report, check, tmp_path)
        assert report.results[0].status == DoctorStatus.OK

    def test_node_gate_missing_node_modules(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        report = _empty_report()
        check = _mock_check(tool_context_value="node")
        _check_gate_readiness(report, check, tmp_path)
        assert report.results[0].status == DoctorStatus.FAIL
        assert "node_modules" in report.results[0].summary

    def test_node_gate_missing_package_json(self, tmp_path):
        report = _empty_report()
        check = _mock_check(tool_context_value="node")
        _check_gate_readiness(report, check, tmp_path)
        assert report.results[0].status == DoctorStatus.FAIL
        assert "package.json" in report.results[0].summary


# ===========================================================================
# _is_gate_enabled tests
# ===========================================================================


class TestIsGateEnabled:
    def test_enabled_by_default(self):
        assert _is_gate_enabled({}, "laziness:dead-code.py") is True

    def test_disabled_via_disabled_gates(self):
        cfg = {"disabled_gates": ["laziness:dead-code.py"]}
        assert _is_gate_enabled(cfg, "laziness:dead-code.py") is False

    def test_disabled_via_nested_config(self):
        cfg = {"laziness": {"gates": {"dead-code.py": {"enabled": False}}}}
        assert _is_gate_enabled(cfg, "laziness:dead-code.py") is False

    def test_enabled_via_nested_config(self):
        cfg = {"laziness": {"gates": {"dead-code.py": {"enabled": True}}}}
        assert _is_gate_enabled(cfg, "laziness:dead-code.py") is True

    def test_no_colon_in_name(self):
        assert _is_gate_enabled({}, "standalone") is True


# ===========================================================================
# Integration: run_doctor
# ===========================================================================


class TestRunDoctor:
    """Integration tests for run_doctor orchestrator.

    Patches lazy imports at their source modules so that the local
    ``from X import Y`` inside run_doctor() picks up the mock.
    """

    @patch("slopmop.cli.doctor.get_registry")
    @patch("slopmop.sm.load_config", return_value={})
    @patch("slopmop.checks.ensure_checks_registered")
    def test_returns_0_when_all_ok(self, _ensure, _load, mock_get_reg, tmp_path):
        mock_get_reg.return_value = _mock_registry()
        result = run_doctor(
            project_root=str(tmp_path),
            json_output=True,
        )
        # Platform check will be OK, config will WARN (no file), slopmop-dir
        # will WARN (missing) — but no FAILs, so exit code 0
        assert result == 0

    @patch("slopmop.cli.doctor.get_registry")
    @patch("slopmop.sm.load_config", return_value={})
    @patch("slopmop.checks.ensure_checks_registered")
    def test_returns_1_when_fail_exists(self, _ensure, _load, mock_get_reg, tmp_path):
        # Make config file with invalid JSON to trigger FAIL
        (tmp_path / ".sb_config.json").write_text("{bad json")
        mock_get_reg.return_value = _mock_registry()
        result = run_doctor(project_root=str(tmp_path), json_output=True)
        assert result == 1

    @patch("slopmop.cli.doctor.get_registry")
    @patch("slopmop.sm.load_config", return_value={})
    @patch("slopmop.checks.ensure_checks_registered")
    def test_json_output_is_valid(self, _ensure, _load, mock_get_reg, tmp_path, capsys):
        mock_get_reg.return_value = _mock_registry()
        run_doctor(project_root=str(tmp_path), json_output=True)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "results" in data
        assert "sm_version" in data
        assert isinstance(data["results"], list)

    @patch("slopmop.cli.doctor.get_registry")
    @patch("slopmop.sm.load_config", return_value={})
    @patch("slopmop.checks.ensure_checks_registered")
    def test_list_checks_mode(self, _ensure, _load, mock_get_reg, tmp_path, capsys):
        mock_get_reg.return_value = _mock_registry()
        result = run_doctor(
            project_root=str(tmp_path),
            list_checks=True,
            json_output=False,
        )
        assert result == 0
        captured = capsys.readouterr()
        assert "platform" in captured.out
        assert "stale-lock" in captured.out

    @patch("slopmop.cli.doctor.get_registry")
    @patch("slopmop.sm.load_config", return_value={})
    @patch("slopmop.checks.ensure_checks_registered")
    def test_list_checks_json(self, _ensure, _load, mock_get_reg, tmp_path, capsys):
        mock_get_reg.return_value = _mock_registry()
        result = run_doctor(
            project_root=str(tmp_path),
            list_checks=True,
            json_output=True,
        )
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        names = [c["name"] for c in data]
        assert "platform" in names

    @patch("slopmop.cli.doctor.get_registry")
    @patch("slopmop.sm.load_config", return_value={})
    @patch("slopmop.checks.ensure_checks_registered")
    def test_filter_runs_only_specified(
        self, _ensure, _load, mock_get_reg, tmp_path, capsys
    ):
        mock_get_reg.return_value = _mock_registry()
        run_doctor(
            project_root=str(tmp_path),
            checks_filter=["config"],
            json_output=True,
        )
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        names = [r["name"] for r in data["results"]]
        assert "config" in names
        # stale-lock should NOT have run since it wasn't in the filter
        assert "stale-lock" not in names

    @patch("slopmop.cli.doctor.get_registry")
    @patch("slopmop.sm.load_config", return_value={})
    @patch("slopmop.checks.ensure_checks_registered")
    def test_gate_filter_skips_env(
        self, _ensure, _load, mock_get_reg, tmp_path, capsys
    ):
        """When filter contains only gate names, env checks are skipped."""
        check = _mock_check(
            full_name="laziness:dead-code.py",
            tool_context_value="sm_tool",
            required_tools=["vulture"],
        )
        mock_get_reg.return_value = _mock_registry(
            gate_names=["laziness:dead-code.py"],
            checks=[check],
        )
        with patch("slopmop.cli.doctor.find_tool", return_value="/usr/bin/vulture"):
            run_doctor(
                project_root=str(tmp_path),
                checks_filter=["laziness:dead-code.py"],
                json_output=True,
            )
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        names = [r["name"] for r in data["results"]]
        assert "laziness:dead-code.py" in names
        assert "platform" not in names

    @patch("slopmop.cli.doctor.get_registry")
    @patch("slopmop.sm.load_config", return_value={})
    @patch("slopmop.checks.ensure_checks_registered")
    def test_console_output(self, _ensure, _load, mock_get_reg, tmp_path, capsys):
        mock_get_reg.return_value = _mock_registry()
        run_doctor(project_root=str(tmp_path), json_output=False)
        captured = capsys.readouterr()
        assert "sm doctor" in captured.out
        assert "Environment" in captured.out

    @patch("slopmop.cli.doctor.get_registry")
    @patch("slopmop.sm.load_config", return_value={})
    @patch("slopmop.checks.ensure_checks_registered")
    def test_quiet_mode_suppresses_output(
        self, _ensure, _load, mock_get_reg, tmp_path, capsys
    ):
        mock_get_reg.return_value = _mock_registry()
        run_doctor(project_root=str(tmp_path), json_output=False, quiet=True)
        captured = capsys.readouterr()
        assert captured.out == ""

    @patch("slopmop.cli.doctor.get_registry")
    @patch("slopmop.sm.load_config", return_value={})
    @patch("slopmop.checks.ensure_checks_registered")
    def test_fix_creates_slopmop_dir(
        self, _ensure, _load, mock_get_reg, tmp_path, capsys
    ):
        mock_get_reg.return_value = _mock_registry()
        run_doctor(project_root=str(tmp_path), fix=True, json_output=True)
        assert (tmp_path / ".slopmop").exists()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        statuses = {r["name"]: r["status"] for r in data["results"]}
        assert statuses.get("slopmop-dir") == "fixed"

    @patch("slopmop.cli.doctor.get_registry")
    @patch(
        "slopmop.sm.load_config",
        return_value={"disabled_gates": ["laziness:dead-code.py"]},
    )
    @patch("slopmop.checks.ensure_checks_registered")
    def test_disabled_gate_is_skipped(
        self, _ensure, _load, mock_get_reg, tmp_path, capsys
    ):
        check = _mock_check(full_name="laziness:dead-code.py")
        mock_get_reg.return_value = _mock_registry(
            gate_names=["laziness:dead-code.py"],
            checks=[check],
        )
        run_doctor(project_root=str(tmp_path), json_output=True)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        gate_names = [r["name"] for r in data["results"] if r.get("gate")]
        assert "laziness:dead-code.py" not in gate_names


# ===========================================================================
# check_single_gate_readiness (config hook API)
# ===========================================================================


class TestCheckSingleGateReadiness:
    @patch("slopmop.cli.doctor.get_registry")
    @patch("slopmop.checks.ensure_checks_registered")
    def test_returns_report_for_known_gate(self, _ensure, mock_get_reg, tmp_path):
        check = _mock_check(
            full_name="laziness:dead-code.py",
            tool_context_value="sm_tool",
            required_tools=["vulture"],
        )
        mock_get_reg.return_value = _mock_registry(
            gate_names=["laziness:dead-code.py"],
            checks=[check],
        )
        with patch("slopmop.cli.doctor.find_tool", return_value="/usr/bin/vulture"):
            report = check_single_gate_readiness("laziness:dead-code.py", tmp_path, {})
        assert len(report.results) == 1
        assert report.results[0].status == DoctorStatus.OK

    @patch("slopmop.cli.doctor.get_registry")
    @patch("slopmop.checks.ensure_checks_registered")
    def test_returns_empty_for_unknown_gate(self, _ensure, mock_get_reg, tmp_path):
        mock_get_reg.return_value = _mock_registry()
        report = check_single_gate_readiness("nonexistent:gate", tmp_path, {})
        assert len(report.results) == 0


# ===========================================================================
# Config enable hook integration
# ===========================================================================


class TestConfigEnableHook:
    """Test that config --enable triggers doctor readiness check."""

    @patch("slopmop.cli.doctor.get_registry")
    @patch("slopmop.checks.ensure_checks_registered")
    def test_enable_gate_shows_readiness_warning(self, _ensure, mock_get_reg, tmp_path):
        """When a gate is enabled but tools are missing, readiness report has FAIL."""
        check = _mock_check(
            full_name="laziness:dead-code.py",
            tool_context_value="sm_tool",
            required_tools=["vulture"],
        )
        mock_get_reg.return_value = _mock_registry(
            gate_names=["laziness:dead-code.py"],
            checks=[check],
        )

        with patch("slopmop.cli.doctor.find_tool", return_value=None):
            report = check_single_gate_readiness("laziness:dead-code.py", tmp_path, {})

        assert any(r.status == DoctorStatus.FAIL for r in report.results)
        fail = next(r for r in report.results if r.status == DoctorStatus.FAIL)
        assert "vulture" in fail.summary

    @patch("slopmop.cli.doctor.get_registry")
    @patch("slopmop.checks.ensure_checks_registered")
    def test_enable_gate_no_warning_when_ready(self, _ensure, mock_get_reg, tmp_path):
        """When gate is ready, no warnings in readiness report."""
        check = _mock_check(
            full_name="laziness:dead-code.py",
            tool_context_value="sm_tool",
            required_tools=["vulture"],
        )
        mock_get_reg.return_value = _mock_registry(
            gate_names=["laziness:dead-code.py"],
            checks=[check],
        )

        with patch("slopmop.cli.doctor.find_tool", return_value="/usr/bin/vulture"):
            report = check_single_gate_readiness("laziness:dead-code.py", tmp_path, {})

        assert all(r.status == DoctorStatus.OK for r in report.results)
