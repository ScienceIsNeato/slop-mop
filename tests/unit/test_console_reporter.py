"""Tests for console reporter."""

import pytest  # noqa: F401  # Required for fixtures

from slopbucket.core.result import CheckResult, CheckStatus, ExecutionSummary
from slopbucket.reporting.console import ConsoleReporter


class TestConsoleReporter:
    """Tests for ConsoleReporter class."""

    def test_init_default(self):
        """Test default initialization."""
        reporter = ConsoleReporter()
        assert reporter.quiet is False
        assert reporter.verbose is False

    def test_init_quiet(self):
        """Test initialization with quiet mode."""
        reporter = ConsoleReporter(quiet=True)
        assert reporter.quiet is True
        assert reporter.verbose is False

    def test_init_verbose(self):
        """Test initialization with verbose mode."""
        reporter = ConsoleReporter(verbose=True)
        assert reporter.quiet is False
        assert reporter.verbose is True

    def test_on_check_complete_passed(self, capsys):
        """Test reporting a passed check."""
        reporter = ConsoleReporter()
        result = CheckResult(
            name="test-check",
            status=CheckStatus.PASSED,
            duration=1.5,
            output="Test passed",
        )

        reporter.on_check_complete(result)

        captured = capsys.readouterr()
        assert "test-check" in captured.out
        assert "passed" in captured.out.lower()
        assert "1.50s" in captured.out

    def test_on_check_complete_failed(self, capsys):
        """Test reporting a failed check."""
        reporter = ConsoleReporter()
        result = CheckResult(
            name="test-check",
            status=CheckStatus.FAILED,
            duration=2.0,
            output="Test failed\nError details here",
            error="Something went wrong",
        )

        reporter.on_check_complete(result)

        captured = capsys.readouterr()
        assert "test-check" in captured.out
        assert "failed" in captured.out.lower()
        assert "Something went wrong" in captured.out

    def test_on_check_complete_quiet_passed(self, capsys):
        """Test that passed checks are not reported in quiet mode."""
        reporter = ConsoleReporter(quiet=True)
        result = CheckResult(
            name="test-check",
            status=CheckStatus.PASSED,
            duration=1.0,
        )

        reporter.on_check_complete(result)

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_on_check_complete_quiet_failed(self, capsys):
        """Test that failed checks are reported in quiet mode."""
        reporter = ConsoleReporter(quiet=True)
        result = CheckResult(
            name="test-check",
            status=CheckStatus.FAILED,
            duration=1.0,
            error="Error message",
        )

        reporter.on_check_complete(result)

        captured = capsys.readouterr()
        assert "test-check" in captured.out
        assert "failed" in captured.out.lower()

    def test_on_check_complete_verbose_passed(self, capsys):
        """Test verbose output for passed checks."""
        reporter = ConsoleReporter(verbose=True)
        result = CheckResult(
            name="test-check",
            status=CheckStatus.PASSED,
            duration=1.0,
            output="Some verbose output here",
        )

        reporter.on_check_complete(result)

        captured = capsys.readouterr()
        assert "Some verbose output" in captured.out

    def test_on_check_complete_error(self, capsys):
        """Test reporting a check with error status."""
        reporter = ConsoleReporter()
        result = CheckResult(
            name="test-check",
            status=CheckStatus.ERROR,
            duration=0.5,
            error="Exception occurred",
        )

        reporter.on_check_complete(result)

        captured = capsys.readouterr()
        assert "test-check" in captured.out
        assert "error" in captured.out.lower()
        assert "Exception occurred" in captured.out

    def test_on_check_complete_skipped(self, capsys):
        """Test reporting a skipped check."""
        reporter = ConsoleReporter()
        result = CheckResult(
            name="test-check",
            status=CheckStatus.SKIPPED,
            duration=0.0,
            output="Not applicable",
        )

        reporter.on_check_complete(result)

        captured = capsys.readouterr()
        assert "test-check" in captured.out
        assert "skipped" in captured.out.lower()

    def test_on_check_complete_with_fix_suggestion(self, capsys):
        """Test reporting a failed check with fix suggestion."""
        reporter = ConsoleReporter()
        result = CheckResult(
            name="test-check",
            status=CheckStatus.FAILED,
            duration=1.0,
            output="Test failed",
            error="Lint error",
            fix_suggestion="Run: black . to fix formatting",
        )

        reporter.on_check_complete(result)

        captured = capsys.readouterr()
        assert "Run: black . to fix formatting" in captured.out

    def test_print_summary_all_passed(self, capsys):
        """Test printing summary when all checks pass."""
        results = [
            CheckResult("check1", CheckStatus.PASSED, 1.0),
            CheckResult("check2", CheckStatus.PASSED, 2.0),
        ]
        summary = ExecutionSummary.from_results(results, 3.0)
        reporter = ConsoleReporter()

        reporter.print_summary(summary)

        captured = capsys.readouterr()
        assert "Quality Gate Summary" in captured.out
        assert "Total: 2 checks" in captured.out
        assert "Passed:  2" in captured.out
        assert "Failed:  0" in captured.out
        assert "ALL CHECKS PASSED" in captured.out

    def test_print_summary_with_failures(self, capsys):
        """Test printing summary with failures."""
        results = [
            CheckResult("check1", CheckStatus.PASSED, 1.0),
            CheckResult("check2", CheckStatus.FAILED, 2.0, error="Something broke"),
        ]
        summary = ExecutionSummary.from_results(results, 3.0)
        reporter = ConsoleReporter()

        reporter.print_summary(summary)

        captured = capsys.readouterr()
        assert "Passed:  1" in captured.out
        assert "Failed:  1" in captured.out
        assert "QUALITY GATE FAILED" in captured.out
        assert "check2" in captured.out

    def test_print_summary_with_errors(self, capsys):
        """Test printing summary with errors."""
        results = [
            CheckResult("check1", CheckStatus.ERROR, 1.0, error="Exception!"),
        ]
        summary = ExecutionSummary.from_results(results, 1.0)
        reporter = ConsoleReporter()

        reporter.print_summary(summary)

        captured = capsys.readouterr()
        assert "Errors:  1" in captured.out
        assert "ERRORS:" in captured.out
        assert "Exception!" in captured.out

    def test_print_summary_with_skipped_verbose(self, capsys):
        """Test printing summary shows skipped in verbose mode."""
        results = [
            CheckResult("check1", CheckStatus.PASSED, 1.0),
            CheckResult("check2", CheckStatus.SKIPPED, 0.0),
        ]
        summary = ExecutionSummary.from_results(results, 1.0)
        reporter = ConsoleReporter(verbose=True)

        reporter.print_summary(summary)

        captured = capsys.readouterr()
        assert "SKIPPED:" in captured.out
        assert "check2" in captured.out

    def test_print_summary_quiet_mode(self, capsys):
        """Test printing summary in quiet mode doesn't show passed list."""
        results = [
            CheckResult("check1", CheckStatus.PASSED, 1.0),
            CheckResult("check2", CheckStatus.PASSED, 2.0),
        ]
        summary = ExecutionSummary.from_results(results, 3.0)
        reporter = ConsoleReporter(quiet=True)

        reporter.print_summary(summary)

        captured = capsys.readouterr()
        # Summary should still appear, but PASSED list should not
        assert "Quality Gate Summary" in captured.out
        # The line "✅ PASSED:" should not appear in quiet mode
        lines = captured.out.split("\n")
        passed_header_lines = [l for l in lines if l.strip() == "✅ PASSED:"]
        assert len(passed_header_lines) == 0

    def test_print_summary_with_fix_suggestion(self, capsys):
        """Test printing summary shows fix suggestions for failures."""
        results = [
            CheckResult(
                "check1",
                CheckStatus.FAILED,
                1.0,
                error="Error",
                fix_suggestion="Run fix command",
            ),
        ]
        summary = ExecutionSummary.from_results(results, 1.0)
        reporter = ConsoleReporter()

        reporter.print_summary(summary)

        captured = capsys.readouterr()
        assert "Run fix command" in captured.out

    def test_status_emoji_mapping(self):
        """Test status emoji mapping is complete."""
        reporter = ConsoleReporter()
        for status in CheckStatus:
            assert status in reporter.STATUS_EMOJI

    def test_print_failure_details_long_output(self, capsys):
        """Test that long output is truncated."""
        reporter = ConsoleReporter()
        long_output = "\n".join([f"Line {i}" for i in range(30)])
        result = CheckResult(
            name="test-check",
            status=CheckStatus.FAILED,
            duration=1.0,
            output=long_output,
        )

        reporter.on_check_complete(result)

        captured = capsys.readouterr()
        assert "truncated" in captured.out
