"""Tests for check executor."""

import time
from unittest.mock import MagicMock

from slopmop.checks.base import BaseCheck, Flaw, GateCategory, RemediationChurn
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
    remediation_churn: RemediationChurn = RemediationChurn.DOWNSTREAM_CHANGES_UNLIKELY,
    remediation_priority: int | None = None,
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

    DynamicMockCheck.remediation_churn = remediation_churn
    DynamicMockCheck.remediation_priority = remediation_priority

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

    def test_remediation_mode_processes_results_in_priority_order(self, tmp_path):
        """Completed results are processed by remediation order, not finish order."""
        registry = CheckRegistry()
        high = make_mock_check_class(
            "high",
            status=CheckStatus.PASSED,
            duration=0.10,
            remediation_churn=RemediationChurn.DOWNSTREAM_CHANGES_VERY_LIKELY,
        )
        medium = make_mock_check_class(
            "medium",
            status=CheckStatus.PASSED,
            duration=0.02,
            remediation_churn=RemediationChurn.DOWNSTREAM_CHANGES_LIKELY,
        )
        low = make_mock_check_class(
            "low",
            status=CheckStatus.FAILED,
            duration=0.01,
            remediation_churn=RemediationChurn.DOWNSTREAM_CHANGES_VERY_UNLIKELY,
        )
        registry.register(high)
        registry.register(medium)
        registry.register(low)

        executor = CheckExecutor(
            registry=registry,
            fail_fast=True,
            max_workers=2,
            process_results_in_remediation_order=True,
        )
        summary = executor.run_checks(
            str(tmp_path),
            [
                "overconfidence:high",
                "overconfidence:medium",
                "overconfidence:low",
            ],
            timings={
                "overconfidence:high": 10.0,
                "overconfidence:medium": 0.5,
                "overconfidence:low": 1.0,
            },
        )

        names = [
            result.name
            for result in summary.results
            if result.status != CheckStatus.SKIPPED
        ]
        assert names[:3] == ["high", "medium", "low"]
        assert high.run_count == 1
        assert medium.run_count == 1
        assert low.run_count == 1

    def test_remediation_mode_fail_fast_waits_for_higher_priority_gate(self, tmp_path):
        """A fast low-priority failure must not block a higher-priority gate."""
        registry = CheckRegistry()
        high = make_mock_check_class(
            "high-priority",
            status=CheckStatus.PASSED,
            duration=0.10,
            remediation_churn=RemediationChurn.DOWNSTREAM_CHANGES_VERY_LIKELY,
        )
        low = make_mock_check_class(
            "low-priority",
            status=CheckStatus.FAILED,
            duration=0.01,
            remediation_churn=RemediationChurn.DOWNSTREAM_CHANGES_VERY_UNLIKELY,
        )
        queued = make_mock_check_class(
            "queued",
            status=CheckStatus.PASSED,
            duration=0.02,
            remediation_churn=RemediationChurn.DOWNSTREAM_CHANGES_LIKELY,
        )
        registry.register(high)
        registry.register(low)
        registry.register(queued)

        executor = CheckExecutor(
            registry=registry,
            fail_fast=True,
            max_workers=2,
            process_results_in_remediation_order=True,
        )
        summary = executor.run_checks(
            str(tmp_path),
            [
                "overconfidence:high-priority",
                "overconfidence:low-priority",
                "overconfidence:queued",
            ],
            timings={
                "overconfidence:high-priority": 10.0,
                "overconfidence:low-priority": 1.0,
                "overconfidence:queued": 0.5,
            },
        )

        assert high.run_count == 1
        assert queued.run_count == 1
        assert summary.failed == 1

    def test_remediation_mode_fail_fast_preserves_completed_buffered_results(
        self, tmp_path
    ):
        """Fail-fast should not relabel already-completed buffered results as skipped."""
        registry = CheckRegistry()
        high = make_mock_check_class(
            "high-priority",
            status=CheckStatus.FAILED,
            duration=0.10,
            remediation_churn=RemediationChurn.DOWNSTREAM_CHANGES_VERY_LIKELY,
        )
        low = make_mock_check_class(
            "low-priority",
            status=CheckStatus.FAILED,
            duration=0.01,
            remediation_churn=RemediationChurn.DOWNSTREAM_CHANGES_VERY_UNLIKELY,
        )
        pending = make_mock_check_class(
            "pending",
            status=CheckStatus.PASSED,
            duration=0.20,
            remediation_churn=RemediationChurn.DOWNSTREAM_CHANGES_LIKELY,
        )
        registry.register(high)
        registry.register(low)
        registry.register(pending)

        executor = CheckExecutor(
            registry=registry,
            fail_fast=True,
            max_workers=2,
            process_results_in_remediation_order=True,
        )
        summary = executor.run_checks(
            str(tmp_path),
            [
                "overconfidence:high-priority",
                "overconfidence:low-priority",
                "overconfidence:pending",
            ],
            timings={
                "overconfidence:high-priority": 10.0,
                "overconfidence:low-priority": 1.0,
                "overconfidence:pending": 5.0,
            },
        )

        results = {result.name: result for result in summary.results}
        assert results["high-priority"].status == CheckStatus.FAILED
        assert results["low-priority"].status == CheckStatus.FAILED
        assert results["pending"].status in {
            CheckStatus.PASSED,
            CheckStatus.SKIPPED,
        }

    def test_drain_completed_buffer_ignores_pending_names_already_recorded(self):
        """Pending names already converted to results must not block buffered drains."""
        executor = CheckExecutor(
            registry=CheckRegistry(),
            fail_fast=True,
            process_results_in_remediation_order=True,
        )
        executor._processing_priority = {
            "pending": (100, 0, "pending"),
            "low": (200, 0, "low"),
        }
        executor._results["pending"] = CheckResult(
            name="pending",
            status=CheckStatus.SKIPPED,
            duration=0,
            skip_reason=SkipReason.FAIL_FAST,
        )
        buffered_low = CheckResult(
            name="low",
            status=CheckStatus.FAILED,
            duration=0.1,
            error="late buffered failure",
        )

        executor._drain_completed_buffer(
            buffered_results={"low": buffered_low},
            pending={"pending"},
            futures={},
        )

        assert executor._results["low"] is buffered_low

    def test_drain_completed_buffer_sorts_unknown_names_after_known_priorities(self):
        """Unknown names should not jump ahead of known remediation priorities."""
        executor = CheckExecutor(
            registry=CheckRegistry(),
            fail_fast=False,
            process_results_in_remediation_order=True,
        )
        executor._processing_priority = {
            "known": (0, 100, "known"),
        }
        known = CheckResult(
            name="known",
            status=CheckStatus.PASSED,
            duration=0.1,
        )
        unknown = CheckResult(
            name="unknown",
            status=CheckStatus.PASSED,
            duration=0.1,
        )

        executor._drain_completed_buffer(
            buffered_results={"known": known, "unknown": unknown},
            pending=set(),
            futures={},
        )

        assert list(executor._results)[:2] == ["known", "unknown"]

    def test_dependency_scheduler_uses_committed_results_in_remediation_mode(self):
        """Completed-but-buffered dependencies must not unblock downstream gates."""
        executor = CheckExecutor(
            registry=CheckRegistry(),
            fail_fast=False,
            process_results_in_remediation_order=True,
        )
        available = {
            "dep": CheckResult(
                name="dep",
                status=CheckStatus.PASSED,
                duration=0.1,
            )
        }

        dependency_results = executor._dependency_results_for_scheduler(available)

        assert dependency_results == {}

    def test_collect_remaining_futures_buffers_before_final_drain(self):
        """Leftover futures should be harvested into the buffer before final ordering."""
        executor = CheckExecutor(
            registry=CheckRegistry(),
            fail_fast=False,
            process_results_in_remediation_order=True,
        )
        executor._processing_priority = {
            "high": (0, 100, "high"),
            "low": (0, 200, "low"),
        }
        low = CheckResult(name="low", status=CheckStatus.PASSED, duration=0.1)
        high = CheckResult(name="high", status=CheckStatus.PASSED, duration=0.1)

        future = MagicMock()
        future.result.return_value = high

        available_results: dict[str, CheckResult] = {}
        buffered_results = {"low": low}
        completed: set[str] = set()

        executor._collect_remaining_futures(
            {future: "high"},
            available_results,
            buffered_results,
            completed,
        )
        executor._drain_completed_buffer(buffered_results, pending=set(), futures={})

        assert list(executor._results)[:2] == ["high", "low"]

    def test_maintenance_mode_processes_results_in_completion_order(self, tmp_path):
        """Maintenance mode should surface results as soon as they complete."""
        registry = CheckRegistry()
        slow = make_mock_check_class(
            "slow",
            status=CheckStatus.PASSED,
            duration=0.10,
            remediation_churn=RemediationChurn.DOWNSTREAM_CHANGES_VERY_LIKELY,
        )
        fast = make_mock_check_class(
            "fast",
            status=CheckStatus.PASSED,
            duration=0.01,
            remediation_churn=RemediationChurn.DOWNSTREAM_CHANGES_VERY_UNLIKELY,
        )
        registry.register(slow)
        registry.register(fast)

        executor = CheckExecutor(
            registry=registry,
            fail_fast=False,
            max_workers=2,
            process_results_in_remediation_order=False,
        )
        summary = executor.run_checks(
            str(tmp_path),
            ["overconfidence:slow", "overconfidence:fast"],
        )

        names = [result.name for result in summary.results]
        assert names[:2] == ["fast", "slow"]

    def test_explicit_remediation_priority_allows_fine_grained_order(self, tmp_path):
        """Explicit remediation_priority overrides coarse churn bands."""
        registry = CheckRegistry()
        first = make_mock_check_class(
            "first",
            duration=0.05,
            remediation_churn=RemediationChurn.DOWNSTREAM_CHANGES_UNLIKELY,
            remediation_priority=120,
        )
        second = make_mock_check_class(
            "second",
            duration=0.01,
            remediation_churn=RemediationChurn.DOWNSTREAM_CHANGES_VERY_LIKELY,
            remediation_priority=130,
        )
        third = make_mock_check_class(
            "third",
            duration=0.02,
            remediation_churn=RemediationChurn.DOWNSTREAM_CHANGES_VERY_UNLIKELY,
            remediation_priority=140,
        )
        registry.register(first)
        registry.register(second)
        registry.register(third)

        executor = CheckExecutor(
            registry=registry,
            fail_fast=False,
            process_results_in_remediation_order=True,
        )
        summary = executor.run_checks(
            str(tmp_path),
            [
                "overconfidence:first",
                "overconfidence:second",
                "overconfidence:third",
            ],
        )

        ordered_names = [result.name for result in summary.results]
        assert ordered_names[:3] == ["first", "second", "third"]

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

        # Disabled gate should appear in results as skipped
        assert check_class.run_count == 0
        assert summary.total_checks == 1
        assert summary.skipped == 1
        result = summary.results[0]
        assert result.skip_reason == SkipReason.DISABLED
        assert result.status == CheckStatus.SKIPPED

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
        assert summary.total_checks == 1
        assert summary.skipped == 1

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
        dep_class = make_mock_check_class("dep-check")
        dependent_class = make_mock_check_class(
            "child-check", depends_on=["overconfidence:dep-check"]
        )
        registry.register(dep_class)
        registry.register(dependent_class)

        config = {"disabled_gates": ["overconfidence:dep-check"]}
        executor = CheckExecutor(registry=registry, fail_fast=False)
        summary = executor.run_checks(
            str(tmp_path),
            ["overconfidence:dep-check", "overconfidence:child-check"],
            config=config,
        )

        # Both should be disabled — dep-check explicitly, child-check by propagation
        assert dep_class.run_count == 0
        assert dependent_class.run_count == 0
        assert summary.total_checks == 2
        assert summary.skipped == 2
        reasons = {r.name: r.skip_reason for r in summary.results}
        assert reasons["overconfidence:dep-check"] == SkipReason.DISABLED
        assert reasons["overconfidence:child-check"] == SkipReason.DISABLED

    def test_na_callback_fires_for_inapplicable_checks(self, tmp_path):
        """Test set_na_callback fires when a check is not applicable."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("type-blindness.js", applicable=False)
        registry.register(check_class)

        na_names = []
        executor = CheckExecutor(registry=registry)
        executor.set_na_callback(na_names.append)

        executor.run_checks(str(tmp_path), ["overconfidence:type-blindness.js"])

        assert na_names == ["overconfidence:type-blindness.js"]

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

        def cb(name: str) -> None:
            pass

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
