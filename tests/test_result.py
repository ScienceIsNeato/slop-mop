"""
Tests for result.py — CheckResult and RunSummary formatting.
"""

from slopbucket.result import CheckResult, CheckStatus, RunSummary


class TestCheckResult:
    """Tests for individual check result behavior."""

    def test_passed_result(self) -> None:
        r = CheckResult(name="test-check", status=CheckStatus.PASSED)
        assert r.passed is True
        assert r.failed is False

    def test_failed_result(self) -> None:
        r = CheckResult(name="test-check", status=CheckStatus.FAILED)
        assert r.passed is False
        assert r.failed is True

    def test_error_is_failure(self) -> None:
        r = CheckResult(name="test-check", status=CheckStatus.ERROR)
        assert r.failed is True

    def test_skipped_is_not_failure(self) -> None:
        r = CheckResult(name="test-check", status=CheckStatus.SKIPPED)
        assert r.failed is False
        assert r.passed is False

    def test_brief_format_contains_name(self) -> None:
        r = CheckResult(name="my-check", status=CheckStatus.PASSED, duration_secs=1.5)
        brief = r.format_brief()
        assert "my-check" in brief
        assert "1.5s" in brief
        assert "PASS" in brief

    def test_failure_detail_contains_output(self) -> None:
        r = CheckResult(
            name="fail-check",
            status=CheckStatus.FAILED,
            output="line 42: undefined variable",
            fix_hint="Add the missing import",
        )
        detail = r.format_failure_detail()
        assert "undefined variable" in detail
        assert "Add the missing import" in detail
        assert "FAILED: fail-check" in detail

    def test_failure_detail_truncates_long_output(self) -> None:
        long_output = "\n".join(f"line {i}" for i in range(100))
        r = CheckResult(
            name="long-check", status=CheckStatus.FAILED, output=long_output
        )
        detail = r.format_failure_detail()
        assert "omitted" in detail


class TestRunSummary:
    """Tests for aggregated run summary."""

    def test_all_passed(self) -> None:
        summary = RunSummary(
            results=[
                CheckResult(name="a", status=CheckStatus.PASSED),
                CheckResult(name="b", status=CheckStatus.PASSED),
            ]
        )
        assert summary.all_passed is True
        assert summary.pass_count == 2
        assert summary.fail_count == 0

    def test_with_failures(self) -> None:
        summary = RunSummary(
            results=[
                CheckResult(name="a", status=CheckStatus.PASSED),
                CheckResult(name="b", status=CheckStatus.FAILED, output="broken"),
            ]
        )
        assert summary.all_passed is False
        assert summary.fail_count == 1

    def test_summary_format_contains_all_info(self) -> None:
        summary = RunSummary(
            profile_name="commit",
            results=[
                CheckResult(name="pass-check", status=CheckStatus.PASSED),
                CheckResult(
                    name="fail-check",
                    status=CheckStatus.FAILED,
                    output="error msg",
                    fix_hint="fix it",
                ),
                CheckResult(name="skip-check", status=CheckStatus.SKIPPED),
            ],
        )
        formatted = summary.format_summary()
        assert "commit" in formatted
        assert "pass-check" in formatted
        assert "fail-check" in formatted
        assert "error msg" in formatted
        assert "fix it" in formatted
        assert "VALIDATION FAILED" in formatted

    def test_summary_all_pass_message(self) -> None:
        summary = RunSummary(
            results=[CheckResult(name="ok", status=CheckStatus.PASSED)]
        )
        formatted = summary.format_summary()
        assert "ALL CHECKS PASSED" in formatted
