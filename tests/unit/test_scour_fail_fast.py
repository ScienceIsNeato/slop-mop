"""Tests for swab/scour fail-fast behavior."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch


class TestScourDisablesFailFast:
    """Scour must never use fail-fast so every gate runs to completion."""

    def _make_args(self, tmp_path, no_fail_fast=False):
        return argparse.Namespace(
            project_root=str(tmp_path),
            quiet=True,
            verbose=False,
            no_fail_fast=no_fail_fast,
            no_auto_fix=True,
            static=True,
            clear_history=False,
            swabbing_timeout=None,
            json_output=False,
        )

    @patch("slopmop.cli.validate.ConsoleAdapter")
    @patch("slopmop.cli.validate.ConsoleReporter")
    @patch("slopmop.cli.validate.CheckExecutor")
    @patch("slopmop.cli.validate.get_registry")
    @patch("slopmop.cli.validate.read_phase")
    @patch("slopmop.sm.load_config", return_value={})
    def test_scour_forces_fail_fast_off(
        self,
        _mock_config,
        mock_read_phase,
        mock_reg,
        mock_executor_cls,
        _mock_reporter,
        _mock_adapter,
        tmp_path,
    ):
        """Scour always creates executor with fail_fast=False."""
        from slopmop.cli.validate import _run_validation
        from slopmop.workflow.state_machine import RepoPhase

        mock_executor = MagicMock()
        mock_executor.run_checks.return_value = MagicMock(all_passed=True)
        mock_executor_cls.return_value = mock_executor
        mock_read_phase.return_value = RepoPhase.REMEDIATION

        _run_validation(self._make_args(tmp_path), ["gate1"], "scour")

        mock_executor_cls.assert_called_once()
        _, kwargs = mock_executor_cls.call_args
        assert kwargs["fail_fast"] is False
        assert kwargs["process_results_in_remediation_order"] is True

    @patch("slopmop.cli.validate.ConsoleAdapter")
    @patch("slopmop.cli.validate.ConsoleReporter")
    @patch("slopmop.cli.validate.CheckExecutor")
    @patch("slopmop.cli.validate.get_registry")
    @patch("slopmop.cli.validate.read_phase")
    @patch("slopmop.sm.load_config", return_value={})
    def test_scour_ignores_no_fail_fast_flag(
        self,
        _mock_config,
        mock_read_phase,
        mock_reg,
        mock_executor_cls,
        _mock_reporter,
        _mock_adapter,
        tmp_path,
    ):
        """Even with --no-fail-fast omitted, scour still disables fail-fast."""
        from slopmop.cli.validate import _run_validation
        from slopmop.workflow.state_machine import RepoPhase

        mock_executor = MagicMock()
        mock_executor.run_checks.return_value = MagicMock(all_passed=True)
        mock_executor_cls.return_value = mock_executor
        mock_read_phase.return_value = RepoPhase.REMEDIATION

        # no_fail_fast=False means the user did NOT pass --no-fail-fast,
        # which normally means fail_fast=True. Scour overrides this.
        _run_validation(
            self._make_args(tmp_path, no_fail_fast=False), ["gate1"], "scour"
        )

        _, kwargs = mock_executor_cls.call_args
        assert kwargs["fail_fast"] is False

    @patch("slopmop.cli.validate.ConsoleAdapter")
    @patch("slopmop.cli.validate.ConsoleReporter")
    @patch("slopmop.cli.validate.CheckExecutor")
    @patch("slopmop.cli.validate.get_registry")
    @patch("slopmop.cli.validate.read_phase")
    @patch("slopmop.sm.load_config", return_value={})
    def test_swab_defaults_to_fail_fast(
        self,
        _mock_config,
        mock_read_phase,
        mock_reg,
        mock_executor_cls,
        _mock_reporter,
        _mock_adapter,
        tmp_path,
    ):
        """Swab defaults to fail_fast=True."""
        from slopmop.cli.validate import _run_validation
        from slopmop.workflow.state_machine import RepoPhase

        mock_executor = MagicMock()
        mock_executor.run_checks.return_value = MagicMock(all_passed=True)
        mock_executor_cls.return_value = mock_executor
        mock_read_phase.return_value = RepoPhase.REMEDIATION

        _run_validation(self._make_args(tmp_path), ["gate1"], "swab")

        _, kwargs = mock_executor_cls.call_args
        assert kwargs["fail_fast"] is True
        assert kwargs["process_results_in_remediation_order"] is True

    @patch("slopmop.cli.validate.ConsoleAdapter")
    @patch("slopmop.cli.validate.ConsoleReporter")
    @patch("slopmop.cli.validate.CheckExecutor")
    @patch("slopmop.cli.validate.get_registry")
    @patch("slopmop.cli.validate.read_phase")
    @patch("slopmop.sm.load_config", return_value={})
    def test_swab_respects_no_fail_fast_flag(
        self,
        _mock_config,
        mock_read_phase,
        mock_reg,
        mock_executor_cls,
        _mock_reporter,
        _mock_adapter,
        tmp_path,
    ):
        """Swab with --no-fail-fast creates executor with fail_fast=False."""
        from slopmop.cli.validate import _run_validation
        from slopmop.workflow.state_machine import RepoPhase

        mock_executor = MagicMock()
        mock_executor.run_checks.return_value = MagicMock(all_passed=True)
        mock_executor_cls.return_value = mock_executor
        mock_read_phase.return_value = RepoPhase.REMEDIATION

        _run_validation(self._make_args(tmp_path, no_fail_fast=True), ["gate1"], "swab")

        _, kwargs = mock_executor_cls.call_args
        assert kwargs["fail_fast"] is False

    @patch("slopmop.cli.validate.ConsoleAdapter")
    @patch("slopmop.cli.validate.ConsoleReporter")
    @patch("slopmop.cli.validate.CheckExecutor")
    @patch("slopmop.cli.validate.get_registry")
    @patch("slopmop.cli.validate.read_phase")
    @patch("slopmop.sm.load_config", return_value={})
    def test_maintenance_phase_disables_remediation_order_processing(
        self,
        _mock_config,
        mock_read_phase,
        mock_reg,
        mock_executor_cls,
        _mock_reporter,
        _mock_adapter,
        tmp_path,
    ):
        """Maintenance mode keeps default completion-order processing."""
        from slopmop.cli.validate import _run_validation
        from slopmop.workflow.state_machine import RepoPhase

        mock_executor = MagicMock()
        mock_executor.run_checks.return_value = MagicMock(all_passed=True)
        mock_executor_cls.return_value = mock_executor
        mock_read_phase.return_value = RepoPhase.MAINTENANCE

        _run_validation(self._make_args(tmp_path), ["gate1"], "swab")

        _, kwargs = mock_executor_cls.call_args
        assert kwargs["process_results_in_remediation_order"] is False


class TestRemediationBannerCISuppression:
    """Remediation-mode banner must not appear in CI environments."""

    def _make_args(self, tmp_path):
        return argparse.Namespace(
            project_root=str(tmp_path),
            quiet=False,
            verbose=False,
            no_fail_fast=False,
            no_auto_fix=False,
            static=True,
            clear_history=False,
            swabbing_timeout=None,
            json_output=False,
        )

    @patch("slopmop.cli.validate.ConsoleAdapter")
    @patch("slopmop.cli.validate.ConsoleReporter")
    @patch("slopmop.cli.validate.CheckExecutor")
    @patch("slopmop.cli.validate.get_registry")
    @patch("slopmop.cli.validate.read_phase")
    @patch("slopmop.sm.load_config", return_value={})
    def test_remediation_banner_suppressed_when_ci_env_set(
        self,
        _mock_config,
        mock_read_phase,
        mock_reg,
        mock_executor_cls,
        _mock_reporter,
        _mock_adapter,
        tmp_path,
        monkeypatch,
        capsys,
    ):
        """Banner is hidden in CI environments (CI=true) even when phase is REMEDIATION."""
        from slopmop.cli.validate import _run_validation
        from slopmop.workflow.state_machine import RepoPhase

        monkeypatch.setenv("CI", "true")
        mock_executor = MagicMock()
        mock_executor.run_checks.return_value = MagicMock(all_passed=True)
        mock_executor_cls.return_value = mock_executor
        mock_read_phase.return_value = RepoPhase.REMEDIATION

        _run_validation(self._make_args(tmp_path), ["gate1"], "scour")

        captured = capsys.readouterr()
        assert "Remediation mode" not in captured.out

    @patch("slopmop.cli.validate.ConsoleAdapter")
    @patch("slopmop.cli.validate.ConsoleReporter")
    @patch("slopmop.cli.validate.CheckExecutor")
    @patch("slopmop.cli.validate.get_registry")
    @patch("slopmop.cli.validate.read_phase")
    @patch("slopmop.sm.load_config", return_value={})
    def test_remediation_banner_shown_outside_ci(
        self,
        _mock_config,
        mock_read_phase,
        mock_reg,
        mock_executor_cls,
        _mock_reporter,
        _mock_adapter,
        tmp_path,
        monkeypatch,
        capsys,
    ):
        """Banner is shown for interactive dev use when CI env is not set."""
        from slopmop.cli.validate import _run_validation
        from slopmop.workflow.state_machine import RepoPhase

        monkeypatch.delenv("CI", raising=False)
        mock_executor = MagicMock()
        mock_executor.run_checks.return_value = MagicMock(all_passed=True)
        mock_executor_cls.return_value = mock_executor
        mock_read_phase.return_value = RepoPhase.REMEDIATION

        _run_validation(self._make_args(tmp_path), ["gate1"], "scour")

        captured = capsys.readouterr()
        assert "Remediation mode" in captured.out
