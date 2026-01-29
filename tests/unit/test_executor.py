"""Tests for check executor."""

import time
from unittest.mock import MagicMock

from slopbucket.checks.base import BaseCheck, GateCategory
from slopbucket.core.executor import CheckExecutor
from slopbucket.core.registry import CheckRegistry
from slopbucket.core.result import CheckResult, CheckStatus


class MockCheck(BaseCheck):
    """Mock check for testing."""

    _mock_name = "mock-check"
    _mock_display_name = "Mock Check"
    _mock_depends_on = []
    _mock_applicable = True
    _mock_status = CheckStatus.PASSED
    _mock_duration = 0.01
    _mock_can_fix = False
    run_count = 0  # Class-level counter for tracking

    @property
    def name(self) -> str:
        return self._mock_name

    @property
    def display_name(self) -> str:
        return self._mock_display_name

    @property
    def category(self) -> GateCategory:
        return GateCategory.PYTHON

    @property
    def depends_on(self) -> list:
        return self._mock_depends_on

    def is_applicable(self, project_root: str) -> bool:
        return self._mock_applicable

    def can_auto_fix(self) -> bool:
        return self._mock_can_fix

    def run(self, project_root: str) -> CheckResult:
        # Track runs at class level
        type(self).run_count += 1
        time.sleep(self._mock_duration)
        return CheckResult(
            name=self.name,
            status=self._mock_status,
            duration=self._mock_duration,
            output=f"Output from {self.name}",
        )


def make_mock_check_class(
    name: str,
    status: CheckStatus = CheckStatus.PASSED,
    duration: float = 0.01,
    depends_on: list = None,
    applicable: bool = True,
    can_fix: bool = False,
):
    """Factory to create mock check classes with specific behavior."""

    class DynamicMockCheck(MockCheck):
        _mock_name = name
        _mock_display_name = f"Mock: {name}"
        _mock_depends_on = depends_on or []
        _mock_applicable = applicable
        _mock_status = status
        _mock_duration = duration
        _mock_can_fix = can_fix
        run_count = 0  # Reset counter for each class

    return DynamicMockCheck


class TestCheckExecutor:
    """Tests for CheckExecutor class."""

    def test_run_single_check(self):
        """Test running a single check."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("check1")
        registry.register(check_class)

        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks("/tmp", ["python:check1"])

        assert summary.total_checks == 1
        assert summary.passed == 1
        assert summary.failed == 0
        assert check_class.run_count == 1

    def test_run_multiple_checks(self):
        """Test running multiple checks."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("check1")
        check_class2 = make_mock_check_class("check2")
        registry.register(check_class1)
        registry.register(check_class2)

        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks("/tmp", ["python:check1", "python:check2"])

        assert summary.total_checks == 2
        assert summary.passed == 2
        assert check_class1.run_count == 1
        assert check_class2.run_count == 1

    def test_fail_fast_stops_on_failure(self):
        """Test fail-fast mode stops after first failure."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class(
            "check1", status=CheckStatus.FAILED, duration=0.01
        )
        check_class2 = make_mock_check_class("check2", duration=0.1)
        registry.register(check_class1)
        registry.register(check_class2)

        executor = CheckExecutor(registry=registry, fail_fast=True)
        summary = executor.run_checks("/tmp", ["python:check1", "python:check2"])

        assert summary.failed >= 1
        # check2 may or may not run depending on timing

    def test_no_fail_fast_runs_all(self):
        """Test without fail-fast, all checks run."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("check1", status=CheckStatus.FAILED)
        check_class2 = make_mock_check_class("check2")
        registry.register(check_class1)
        registry.register(check_class2)

        executor = CheckExecutor(registry=registry, fail_fast=False)
        summary = executor.run_checks("/tmp", ["python:check1", "python:check2"])

        assert summary.total_checks == 2
        assert check_class1.run_count == 1
        assert check_class2.run_count == 1

    def test_skips_inapplicable_checks(self):
        """Test that inapplicable checks are skipped."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("check1", applicable=True)
        check_class2 = make_mock_check_class("check2", applicable=False)
        registry.register(check_class1)
        registry.register(check_class2)

        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks("/tmp", ["python:check1", "python:check2"])

        assert summary.passed == 1
        assert summary.skipped == 1
        assert check_class1.run_count == 1
        assert check_class2.run_count == 0

    def test_respects_dependencies(self):
        """Test that dependencies are respected."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("check1")
        check_class2 = make_mock_check_class("check2", depends_on=["python:check1"])
        registry.register(check_class1)
        registry.register(check_class2)

        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks("/tmp", ["python:check1", "python:check2"])

        assert summary.total_checks == 2
        assert summary.passed == 2

    def test_skips_check_if_dependency_fails(self):
        """Test that checks are skipped if dependency fails."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("check1", status=CheckStatus.FAILED)
        check_class2 = make_mock_check_class("check2", depends_on=["python:check1"])
        registry.register(check_class1)
        registry.register(check_class2)

        executor = CheckExecutor(registry=registry, fail_fast=False)
        summary = executor.run_checks("/tmp", ["python:check1", "python:check2"])

        assert summary.failed == 1
        assert summary.skipped == 1
        assert check_class2.run_count == 0

    def test_progress_callback(self):
        """Test progress callback is called."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("check1")
        registry.register(check_class)

        callback = MagicMock()
        executor = CheckExecutor(registry=registry)
        executor.set_progress_callback(callback)
        executor.run_checks("/tmp", ["python:check1"])

        callback.assert_called_once()
        result = callback.call_args[0][0]
        assert isinstance(result, CheckResult)
        assert result.name == "check1"

    def test_empty_check_list(self):
        """Test running with empty check list."""
        registry = CheckRegistry()
        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks("/tmp", [])

        assert summary.total_checks == 0

    def test_summary_includes_duration(self):
        """Test that summary includes total duration."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("check1", duration=0.05)
        registry.register(check_class)

        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks("/tmp", ["python:check1"])

        assert summary.total_duration >= 0.05

    def test_handles_check_exception(self):
        """Test that check exceptions are handled gracefully."""
        registry = CheckRegistry()

        class ExceptionCheck(MockCheck):
            _mock_name = "exception-check"
            _mock_display_name = "Exception Check"

            def run(self, project_root: str) -> CheckResult:
                raise RuntimeError("Test error")

        registry.register(ExceptionCheck)

        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks("/tmp", ["python:exception-check"])

        assert summary.errors == 1

    def test_unknown_check_returns_empty_summary(self):
        """Test running unknown check returns empty summary."""
        registry = CheckRegistry()
        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks("/tmp", ["nonexistent"])

        assert summary.total_checks == 0

    def test_auto_fix_attempted_when_enabled(self):
        """Test auto-fix is attempted when enabled and check supports it."""
        registry = CheckRegistry()

        class FixableCheck(MockCheck):
            _mock_name = "fixable-check"
            _mock_display_name = "Fixable Check"
            fix_called = False

            def can_auto_fix(self) -> bool:
                return True

            def auto_fix(self, project_root: str) -> bool:
                type(self).fix_called = True
                return True

        registry.register(FixableCheck)

        executor = CheckExecutor(registry=registry)
        executor.run_checks("/tmp", ["python:fixable-check"], auto_fix=True)

        assert FixableCheck.fix_called

    def test_auto_fix_not_called_when_disabled(self):
        """Test auto-fix is not called when disabled."""
        registry = CheckRegistry()

        class FixableCheck(MockCheck):
            _mock_name = "fixable-check2"
            _mock_display_name = "Fixable Check"
            fix_called = False

            def can_auto_fix(self) -> bool:
                return True

            def auto_fix(self, project_root: str) -> bool:
                type(self).fix_called = True
                return True

        registry.register(FixableCheck)

        executor = CheckExecutor(registry=registry)
        executor.run_checks("/tmp", ["python:fixable-check2"], auto_fix=False)

        assert not FixableCheck.fix_called

    def test_config_passed_to_checks(self):
        """Test that config is passed to check instances."""
        registry = CheckRegistry()

        class ConfigCheck(MockCheck):
            _mock_name = "config-check"
            _mock_display_name = "Config Check"
            received_config = None

            def __init__(self, config, runner=None):
                super().__init__(config, runner)
                type(self).received_config = config

        registry.register(ConfigCheck)

        executor = CheckExecutor(registry=registry)
        executor.run_checks("/tmp", ["python:config-check"], config={"key": "value"})

        assert ConfigCheck.received_config == {"key": "value"}
