"""Tests for check executor."""

import time
from unittest.mock import MagicMock

from slopmop.checks.base import BaseCheck, Flaw, GateCategory
from slopmop.core.executor import CheckExecutor, run_quality_checks
from slopmop.core.registry import CheckRegistry
from slopmop.core.result import CheckResult, CheckStatus, SkipReason


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
        return GateCategory.OVERCONFIDENCE

    @property
    def flaw(self) -> Flaw:
        return Flaw.OVERCONFIDENCE

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

    def test_run_single_check(self, tmp_path):
        """Test running a single check."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("check1")
        registry.register(check_class)

        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks(str(tmp_path), ["overconfidence:check1"])

        assert summary.total_checks == 1
        assert summary.passed == 1
        assert summary.failed == 0
        assert check_class.run_count == 1

    def test_run_multiple_checks(self, tmp_path):
        """Test running multiple checks."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("check1")
        check_class2 = make_mock_check_class("check2")
        registry.register(check_class1)
        registry.register(check_class2)

        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks(
            str(tmp_path), ["overconfidence:check1", "overconfidence:check2"]
        )

        assert summary.total_checks == 2
        assert summary.passed == 2
        assert check_class1.run_count == 1
        assert check_class2.run_count == 1

    def test_fail_fast_stops_on_failure(self, tmp_path):
        """Test fail-fast mode stops after first failure."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class(
            "check1", status=CheckStatus.FAILED, duration=0.01
        )
        check_class2 = make_mock_check_class("check2", duration=0.1)
        registry.register(check_class1)
        registry.register(check_class2)

        executor = CheckExecutor(registry=registry, fail_fast=True)
        summary = executor.run_checks(
            str(tmp_path), ["overconfidence:check1", "overconfidence:check2"]
        )

        assert summary.failed >= 1
        # check2 may or may not run depending on timing

    def test_no_fail_fast_runs_all(self, tmp_path):
        """Test without fail-fast, all checks run."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("check1", status=CheckStatus.FAILED)
        check_class2 = make_mock_check_class("check2")
        registry.register(check_class1)
        registry.register(check_class2)

        executor = CheckExecutor(registry=registry, fail_fast=False)
        summary = executor.run_checks(
            str(tmp_path), ["overconfidence:check1", "overconfidence:check2"]
        )

        assert summary.total_checks == 2
        assert check_class1.run_count == 1
        assert check_class2.run_count == 1

    def test_skips_inapplicable_checks(self, tmp_path):
        """Test that inapplicable checks are marked not applicable."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("check1", applicable=True)
        check_class2 = make_mock_check_class("check2", applicable=False)
        registry.register(check_class1)
        registry.register(check_class2)

        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks(
            str(tmp_path), ["overconfidence:check1", "overconfidence:check2"]
        )

        assert summary.passed == 1
        assert summary.not_applicable == 1
        assert check_class1.run_count == 1
        assert check_class2.run_count == 0
        # Verify skip_reason enum is set
        na_result = next(
            r for r in summary.results if r.status == CheckStatus.NOT_APPLICABLE
        )
        assert na_result.skip_reason == SkipReason.NOT_APPLICABLE

    def test_respects_dependencies(self, tmp_path):
        """Test that dependencies are respected."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("check1")
        check_class2 = make_mock_check_class(
            "check2", depends_on=["overconfidence:check1"]
        )
        registry.register(check_class1)
        registry.register(check_class2)

        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks(
            str(tmp_path), ["overconfidence:check1", "overconfidence:check2"]
        )

        assert summary.total_checks == 2
        assert summary.passed == 2

    def test_auto_includes_dependencies(self, tmp_path):
        """Test that dependencies are auto-included when not explicitly requested."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("dep-check")
        check_class2 = make_mock_check_class(
            "main-check", depends_on=["overconfidence:dep-check"]
        )
        registry.register(check_class1)
        registry.register(check_class2)

        executor = CheckExecutor(registry=registry)
        # Only request main-check, but it depends on dep-check
        summary = executor.run_checks(str(tmp_path), ["overconfidence:main-check"])

        # Both checks should run (dep-check auto-included)
        assert summary.total_checks == 2
        assert summary.passed == 2
        assert check_class1.run_count == 1  # dep-check was auto-included and ran
        assert check_class2.run_count == 1

    def test_skips_check_if_dependency_fails(self, tmp_path):
        """Test that checks are skipped if dependency fails."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("check1", status=CheckStatus.FAILED)
        check_class2 = make_mock_check_class(
            "check2", depends_on=["overconfidence:check1"]
        )
        registry.register(check_class1)
        registry.register(check_class2)

        executor = CheckExecutor(registry=registry, fail_fast=False)
        summary = executor.run_checks(
            str(tmp_path), ["overconfidence:check1", "overconfidence:check2"]
        )

        assert summary.failed == 1
        assert summary.skipped == 1
        assert check_class2.run_count == 0
        # Verify skip_reason enum is set
        skipped_result = next(
            r for r in summary.results if r.status == CheckStatus.SKIPPED
        )
        assert skipped_result.skip_reason == SkipReason.FAILED_DEPENDENCY

    def test_progress_callback(self, tmp_path):
        """Test progress callback is called."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("check1")
        registry.register(check_class)

        callback = MagicMock()
        executor = CheckExecutor(registry=registry)
        executor.set_progress_callback(callback)
        executor.run_checks(str(tmp_path), ["overconfidence:check1"])

        callback.assert_called_once()
        result = callback.call_args[0][0]
        assert isinstance(result, CheckResult)
        assert result.name == "check1"

    def test_empty_check_list(self, tmp_path):
        """Test running with empty check list."""
        registry = CheckRegistry()
        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks(str(tmp_path), [])

        assert summary.total_checks == 0

    def test_summary_includes_duration(self, tmp_path):
        """Test that summary includes total duration."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("check1", duration=0.05)
        registry.register(check_class)

        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks(str(tmp_path), ["overconfidence:check1"])

        assert summary.total_duration >= 0.05

    def test_handles_check_exception(self, tmp_path):
        """Test that check exceptions are handled gracefully."""
        registry = CheckRegistry()

        class ExceptionCheck(MockCheck):
            _mock_name = "exception-check"
            _mock_display_name = "Exception Check"

            def run(self, project_root: str) -> CheckResult:
                raise RuntimeError("Test error")

        registry.register(ExceptionCheck)

        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks(str(tmp_path), ["overconfidence:exception-check"])

        assert summary.errors == 1

    def test_unknown_check_returns_empty_summary(self, tmp_path):
        """Test running unknown check returns empty summary."""
        registry = CheckRegistry()
        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks(str(tmp_path), ["nonexistent"])

        assert summary.total_checks == 0

    def test_auto_fix_attempted_when_enabled(self, tmp_path):
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
        executor.run_checks(
            str(tmp_path), ["overconfidence:fixable-check"], auto_fix=True
        )

        assert FixableCheck.fix_called

    def test_auto_fix_not_called_when_disabled(self, tmp_path):
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
        executor.run_checks(
            str(tmp_path), ["overconfidence:fixable-check2"], auto_fix=False
        )

        assert not FixableCheck.fix_called

    def test_config_passed_to_checks(self, tmp_path):
        """Test that config is extracted and passed to check instances."""
        registry = CheckRegistry()

        class ConfigCheck(MockCheck):
            _mock_name = "config-check"
            _mock_display_name = "Config Check"
            received_config = None

            def __init__(self, config, runner=None):
                super().__init__(config, runner)
                type(self).received_config = config

        registry.register(ConfigCheck)

        # Config structure: { "category": { "gates": { "check-name": {...} } } }
        full_config = {"overconfidence": {"gates": {"config-check": {"key": "value"}}}}
        executor = CheckExecutor(registry=registry)
        executor.run_checks(
            str(tmp_path), ["overconfidence:config-check"], config=full_config
        )

        assert ConfigCheck.received_config == {"key": "value"}

    def test_all_checks_inapplicable_returns_early(self, tmp_path):
        """Test that when all checks are inapplicable, we return early with not_applicable."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("check1", applicable=False)
        check_class2 = make_mock_check_class("check2", applicable=False)
        registry.register(check_class1)
        registry.register(check_class2)

        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks(
            str(tmp_path), ["overconfidence:check1", "overconfidence:check2"]
        )

        # All checks should be not applicable
        assert summary.total_checks == 2
        assert summary.not_applicable == 2
        assert summary.passed == 0
        assert check_class1.run_count == 0
        assert check_class2.run_count == 0

    def test_fail_fast_skips_remaining_pending_checks(self, tmp_path):
        """Test that fail-fast marks remaining pending checks as skipped."""
        registry = CheckRegistry()
        # First check fails quickly
        check_class1 = make_mock_check_class(
            "check1", status=CheckStatus.FAILED, duration=0.01
        )
        # Second check depends on first (so would be pending)
        check_class2 = make_mock_check_class(
            "check2", depends_on=["overconfidence:check1"], duration=0.5
        )
        # Third check also depends on first
        check_class3 = make_mock_check_class(
            "check3", depends_on=["overconfidence:check1"], duration=0.5
        )
        registry.register(check_class1)
        registry.register(check_class2)
        registry.register(check_class3)

        executor = CheckExecutor(registry=registry, fail_fast=True)
        summary = executor.run_checks(
            str(tmp_path),
            ["overconfidence:check1", "overconfidence:check2", "overconfidence:check3"],
        )

        # check1 failed, check2/check3 should be skipped due to dependency failure
        assert summary.failed == 1
        assert summary.skipped >= 2

    def test_auto_fix_exception_handled(self, tmp_path):
        """Test that auto-fix exceptions are handled gracefully."""
        registry = CheckRegistry()

        class FixExceptionCheck(MockCheck):
            _mock_name = "fix-exception-check"
            _mock_display_name = "Fix Exception Check"

            def can_auto_fix(self) -> bool:
                return True

            def auto_fix(self, project_root: str) -> bool:
                raise RuntimeError("Auto-fix error")

            def run(self, project_root: str) -> CheckResult:
                return CheckResult(
                    name=self.name,
                    status=CheckStatus.PASSED,
                    duration=0.01,
                    output="Check passed",
                )

        registry.register(FixExceptionCheck)

        executor = CheckExecutor(registry=registry)
        # Should not raise, just log warning and continue
        summary = executor.run_checks(
            str(tmp_path), ["overconfidence:fix-exception-check"], auto_fix=True
        )

        # Check should still run and pass
        assert summary.passed == 1

    def test_config_disables_gate_via_disabled_gates(self, tmp_path):
        """Test that gates listed in disabled_gates are not executed."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("disabled-check")
        registry.register(check_class)

        config = {"disabled_gates": ["overconfidence:disabled-check"]}
        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks(
            str(tmp_path), ["overconfidence:disabled-check"], config=config
        )

        # Disabled gate should not appear in results at all
        assert check_class.run_count == 0
        assert summary.total_checks == 0

    def test_config_disables_gate_via_category_enabled_false(self, tmp_path):
        """Test that gates are skipped when their category is disabled."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("lint")
        registry.register(check_class)

        config = {"overconfidence": {"enabled": False}}
        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks(
            str(tmp_path), ["overconfidence:lint"], config=config
        )

        assert check_class.run_count == 0
        assert summary.total_checks == 0

    def test_config_disables_gate_via_gate_enabled_false(self, tmp_path):
        """Test that individual gates can be disabled via gates config."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("enabled-gate")
        check_class2 = make_mock_check_class("disabled-gate")
        registry.register(check_class1)
        registry.register(check_class2)

        config = {
            "overconfidence": {
                "gates": {
                    "disabled-gate": {"enabled": False},
                }
            }
        }
        executor = CheckExecutor(registry=registry)
        summary = executor.run_checks(
            str(tmp_path),
            ["overconfidence:enabled-gate", "overconfidence:disabled-gate"],
            config=config,
        )

        assert check_class1.run_count == 1
        assert check_class2.run_count == 0
        assert summary.passed == 1

    def test_disabled_gate_propagates_to_dependents(self, tmp_path):
        """Test that disabling a gate also disables checks that depend on it."""
        registry = CheckRegistry()
        dep_class = make_mock_check_class("tests")
        dependent_class = make_mock_check_class(
            "coverage", depends_on=["overconfidence:py-tests"]
        )
        registry.register(dep_class)
        registry.register(dependent_class)

        config = {"disabled_gates": ["overconfidence:py-tests"]}
        executor = CheckExecutor(registry=registry, fail_fast=False)
        summary = executor.run_checks(
            str(tmp_path),
            ["overconfidence:py-tests", "deceptiveness:py-coverage"],
            config=config,
        )

        # Both should be disabled — tests explicitly, coverage by propagation
        assert dep_class.run_count == 0
        assert dependent_class.run_count == 0
        assert summary.total_checks == 0

    def test_na_callback_fires_for_inapplicable_checks(self, tmp_path):
        """Test set_na_callback fires when a check is not applicable."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("js-types", applicable=False)
        registry.register(check_class)

        na_names = []
        executor = CheckExecutor(registry=registry)
        executor.set_na_callback(na_names.append)

        executor.run_checks(str(tmp_path), ["overconfidence:js-types"])

        assert na_names == ["overconfidence:js-types"]

    def test_na_callback_not_called_for_applicable_checks(self, tmp_path):
        """Test set_na_callback is NOT called when check is applicable."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("my-check", applicable=True)
        registry.register(check_class)

        na_names = []
        executor = CheckExecutor(registry=registry)
        executor.set_na_callback(na_names.append)

        executor.run_checks(str(tmp_path), ["overconfidence:my-check"])

        assert na_names == []

    def test_set_na_callback_registers_callback(self):
        """Test set_na_callback stores the callback."""
        executor = CheckExecutor()
        cb = lambda name: None  # noqa: E731
        executor.set_na_callback(cb)
        assert executor._on_check_na is cb

    def test_dep_skipped_check_fires_progress_callback(self, tmp_path):
        """Checks skipped due to failed dependency must fire the progress callback."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("check1", status=CheckStatus.FAILED)
        check_class2 = make_mock_check_class(
            "check2", depends_on=["overconfidence:check1"]
        )
        registry.register(check_class1)
        registry.register(check_class2)

        completed_names: list = []
        executor = CheckExecutor(registry=registry, fail_fast=False)
        executor.set_progress_callback(lambda r: completed_names.append(r.name))

        executor.run_checks(
            str(tmp_path), ["overconfidence:check1", "overconfidence:check2"]
        )

        # Both checks must fire the callback so progress bar reaches 100%
        assert any("check1" in n for n in completed_names)
        assert any("check2" in n for n in completed_names)

    def test_fail_fast_pending_checks_fire_callback(self, tmp_path):
        """Checks remaining in pending after fail-fast must fire the progress callback."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class(
            "check1", status=CheckStatus.FAILED, duration=0.01
        )
        check_class2 = make_mock_check_class(
            "check2", depends_on=["overconfidence:check1"], duration=0.5
        )
        registry.register(check_class1)
        registry.register(check_class2)

        completed_names: list = []
        executor = CheckExecutor(registry=registry, fail_fast=True)
        executor.set_progress_callback(lambda r: completed_names.append(r.name))

        executor.run_checks(
            str(tmp_path), ["overconfidence:check1", "overconfidence:check2"]
        )

        assert any("check1" in n for n in completed_names)
        assert any("check2" in n for n in completed_names)

    def test_run_single_check_skips_when_stop_event_set(self, tmp_path):
        """_run_single_check short-circuits when stop event is already set."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("check1")
        registry.register(check_class)

        executor = CheckExecutor(registry=registry, fail_fast=True)
        # Pre-set the stop event (simulates fail-fast already triggered)
        executor._stop_event.set()

        check_instance = check_class({})
        result = executor._run_single_check(check_instance, str(tmp_path), False)

        assert result.status == CheckStatus.SKIPPED
        assert "fail-fast" in result.output.lower()
        # The check's run() should NOT have been called
        assert check_class.run_count == 0


class TestRunQualityChecks:
    """Tests for the run_quality_checks convenience function."""

    def test_run_quality_checks_convenience_function(self, tmp_path):
        """Test run_quality_checks is a convenience wrapper."""
        # Reset the global registry to avoid interference from other tests
        import slopmop.checks as checks_module
        import slopmop.core.registry as registry_module

        old_registry = registry_module._default_registry
        old_checks_registered = checks_module._checks_registered

        try:
            registry_module._default_registry = None
            checks_module._checks_registered = False

            # Register a test check
            from slopmop.core.registry import register_check

            @register_check
            class ConvenienceTestCheck(BaseCheck):
                @property
                def name(self) -> str:
                    return "convenience-test"

                @property
                def display_name(self) -> str:
                    return "Convenience Test"

                @property
                def category(self) -> GateCategory:
                    return GateCategory.OVERCONFIDENCE

                @property
                def flaw(self) -> Flaw:
                    return Flaw.OVERCONFIDENCE

                def is_applicable(self, project_root: str) -> bool:
                    return True

                def run(self, project_root: str) -> CheckResult:
                    return CheckResult(
                        name=self.name,
                        status=CheckStatus.PASSED,
                        duration=0.01,
                        output="Pass",
                    )

            summary = run_quality_checks(
                str(tmp_path),
                ["overconfidence:convenience-test"],
                config=None,
                fail_fast=True,
                auto_fix=False,
            )

            assert summary.passed >= 1
        finally:
            # Restore registry state for subsequent tests
            registry_module._default_registry = old_registry
            checks_module._checks_registered = old_checks_registered
