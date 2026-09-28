"""The Python test gate runs for as long as the repo said it may.

``overconfidence:untested-code.py`` declared a ``timeout`` setting —
documented, defaulted, written into every generated config — and then ran
pytest under a hardcoded 300s. A repo whose suite needed six minutes on a
2-vCPU CI runner was killed at 300s — raising the setting changed nothing —
under a message blaming a "5 minutes" budget nobody had chosen.
"""

from pathlib import Path
from typing import Any, Dict, Tuple
from unittest.mock import MagicMock, patch

import pytest

from slopmop.checks.python.tests import PythonTestsCheck
from slopmop.checks.timeouts import HEAVY_TASK_TIMEOUT
from slopmop.core.registry import CheckRegistry
from slopmop.core.result import CheckResult, CheckStatus
from slopmop.subprocess.runner import SubprocessResult, SubprocessRunner


def _python_project(root: Path) -> None:
    (root / "tests").mkdir()
    (root / "tests" / "test_example.py").write_text("def test_ok(): pass\n")


def _run_timeout_gate(
    check: PythonTestsCheck, root: Path, result: SubprocessResult
) -> Tuple[CheckResult, MagicMock]:
    """Run the gate with a stub runner; return (check result, runner mock)."""
    runner = MagicMock()
    runner.run.return_value = result
    check._runner = runner
    with patch.object(check, "check_project_venv_or_warn", return_value=None):
        with patch.object(check, "_testmon_available", return_value=True):
            outcome = check.run(str(root))
    return outcome, runner


def _passed() -> SubprocessResult:
    return SubprocessResult(
        returncode=0, stdout="1 passed in 0.1s", stderr="", duration=0.1
    )


def _timed_out() -> SubprocessResult:
    return SubprocessResult(
        returncode=-1, stdout="", stderr="", duration=450.0, timed_out=True
    )


class TestTheSuiteGetsTheConfiguredBudget:
    def test_default_is_unchanged_when_unset(self, tmp_path: Path) -> None:
        _python_project(tmp_path)
        check = PythonTestsCheck({})

        _, runner = _run_timeout_gate(check, tmp_path, _passed())

        assert check._test_timeout() == HEAVY_TASK_TIMEOUT
        assert runner.run.call_args.kwargs["timeout"] == HEAVY_TASK_TIMEOUT

    def test_a_configured_timeout_reaches_the_subprocess(self, tmp_path: Path) -> None:
        _python_project(tmp_path)
        check = PythonTestsCheck({"timeout": 540})

        _, runner = _run_timeout_gate(check, tmp_path, _passed())

        assert runner.run.call_args.kwargs["timeout"] == 540

    def test_the_testmon_path_gets_it_too(self, tmp_path: Path) -> None:
        _python_project(tmp_path)
        (tmp_path / ".testmondata").touch()
        (tmp_path / "coverage.xml").write_text("<coverage></coverage>")
        check = PythonTestsCheck({"timeout": 540})

        _, runner = _run_timeout_gate(check, tmp_path, _passed())

        assert "--testmon" in runner.run.call_args.args[0]
        assert runner.run.call_args.kwargs["timeout"] == 540

    def test_the_config_file_shape_reaches_the_subprocess(self, tmp_path: Path) -> None:
        """Through the registry, as `.sb_config.json` actually spells it."""
        _python_project(tmp_path)
        registry = CheckRegistry()
        registry.register(PythonTestsCheck)
        full_config: Dict[str, Any] = {
            "overconfidence": {"gates": {"untested-code.py": {"timeout": 540}}}
        }
        check = registry.get_check("overconfidence:untested-code.py", full_config)
        assert isinstance(check, PythonTestsCheck)

        _, runner = _run_timeout_gate(check, tmp_path, _passed())

        assert runner.run.call_args.kwargs["timeout"] == 540

    def test_a_numeric_string_is_read_as_seconds(self) -> None:
        assert PythonTestsCheck({"timeout": "450"})._test_timeout() == 450


class TestABadBudgetFallsBackRatherThanCrashing:
    @pytest.mark.parametrize(
        "bad",
        [
            "abc",
            "",
            None,
            0,
            -5,
            [1],
            {"s": 1},
            True,
            False,
            450.9,
            float("inf"),
            float("-inf"),
            float("nan"),
        ],
    )
    def test_nonsense_falls_back_to_the_default(self, bad: Any) -> None:
        assert PythonTestsCheck({"timeout": bad})._test_timeout() == HEAVY_TASK_TIMEOUT

    def test_a_bad_value_still_runs_the_suite_at_the_default(
        self, tmp_path: Path
    ) -> None:
        _python_project(tmp_path)
        check = PythonTestsCheck({"timeout": 0})

        _, runner = _run_timeout_gate(check, tmp_path, _passed())

        assert runner.run.call_args.kwargs["timeout"] == HEAVY_TASK_TIMEOUT


class TestTheRunnerCeilingIsTheLimit:
    def test_a_budget_over_the_ceiling_is_clamped(self, tmp_path: Path) -> None:
        """The runner would clamp it anyway; passing the clamped value keeps
        the number handed down and the number quoted on a timeout honest."""
        _python_project(tmp_path)
        check = PythonTestsCheck({"timeout": 900})

        _, runner = _run_timeout_gate(check, tmp_path, _passed())

        assert runner.run.call_args.kwargs["timeout"] == SubprocessRunner.MAX_TIMEOUT

    def test_the_schema_says_so(self) -> None:
        (field,) = [
            f for f in PythonTestsCheck({}).config_schema if f.name == "timeout"
        ]
        assert field.default == HEAVY_TASK_TIMEOUT
        assert f"{SubprocessRunner.MAX_TIMEOUT}s" in field.description


class TestATimeoutQuotesTheBudgetInForce:
    def test_the_message_names_the_configured_budget(self, tmp_path: Path) -> None:
        _python_project(tmp_path)
        check = PythonTestsCheck({"timeout": 450})

        outcome, _ = _run_timeout_gate(check, tmp_path, _timed_out())

        assert outcome.status == CheckStatus.FAILED
        assert "450s" in (outcome.error or "")
        assert "5 minutes" not in (outcome.error or "")
        assert "timeout" in (outcome.fix_suggestion or "")

    def test_the_default_budget_is_quoted_when_unset(self, tmp_path: Path) -> None:
        _python_project(tmp_path)
        check = PythonTestsCheck({})

        outcome, _ = _run_timeout_gate(check, tmp_path, _timed_out())

        assert f"{HEAVY_TASK_TIMEOUT}s" in (outcome.error or "")
