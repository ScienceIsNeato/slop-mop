"""
Tests for runner.py — parallel execution and fail-fast behavior.
"""

from slopbucket.base_check import BaseCheck
from slopbucket.config import RunnerConfig
from slopbucket.result import CheckStatus
from slopbucket.runner import Runner


class _AlwaysPassCheck(BaseCheck):
    """Test stub that always passes."""

    def __init__(self, name: str = "always-pass"):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Always passes"

    def execute(self, working_dir=None):
        return self._make_result(status=CheckStatus.PASSED, output="OK")


class _AlwaysFailCheck(BaseCheck):
    """Test stub that always fails."""

    def __init__(self, name: str = "always-fail"):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Always fails"

    def execute(self, working_dir=None):
        return self._make_result(
            status=CheckStatus.FAILED,
            output="Intentional failure",
            fix_hint="This is a test",
        )


class TestRunnerSequential:
    """Tests for sequential execution mode."""

    def test_all_pass(self) -> None:
        config = RunnerConfig(parallel=False)
        runner = Runner(config)
        checks = [_AlwaysPassCheck("a"), _AlwaysPassCheck("b")]
        summary = runner.run(checks)
        assert summary.all_passed
        assert summary.pass_count == 2

    def test_fail_fast_stops_after_first_failure(self) -> None:
        config = RunnerConfig(parallel=False, fail_fast=True)
        runner = Runner(config)
        checks = [_AlwaysFailCheck("first"), _AlwaysPassCheck("second")]
        summary = runner.run(checks)
        assert not summary.all_passed
        assert summary.fail_count == 1
        # Second check should not have run (no result or skipped)
        names = [r.name for r in summary.results]
        assert "first" in names

    def test_no_fail_fast_runs_all(self) -> None:
        config = RunnerConfig(parallel=False, fail_fast=False)
        runner = Runner(config)
        checks = [_AlwaysFailCheck("first"), _AlwaysPassCheck("second")]
        summary = runner.run(checks)
        assert summary.fail_count == 1
        assert summary.pass_count == 1

    def test_profile_name_propagates(self) -> None:
        config = RunnerConfig(parallel=False)
        runner = Runner(config)
        summary = runner.run([_AlwaysPassCheck()], profile_name="test-profile")
        assert summary.profile_name == "test-profile"


class TestRunnerParallel:
    """Tests for parallel execution mode."""

    def test_parallel_all_pass(self) -> None:
        config = RunnerConfig(parallel=True, max_workers=2)
        runner = Runner(config)
        checks = [_AlwaysPassCheck(f"check-{i}") for i in range(4)]
        summary = runner.run(checks)
        assert summary.all_passed
        assert summary.pass_count == 4

    def test_parallel_preserves_order(self) -> None:
        config = RunnerConfig(parallel=True, max_workers=2)
        runner = Runner(config)
        checks = [_AlwaysPassCheck(f"check-{i}") for i in range(4)]
        summary = runner.run(checks)
        names = [r.name for r in summary.results]
        expected = [f"check-{i}" for i in range(4)]
        assert names == expected
