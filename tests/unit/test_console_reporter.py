"""Tests for console reporter."""

import pytest  # noqa: F401  # Required for fixtures

from slopmop.core.result import CheckResult, CheckStatus, ExecutionSummary
from slopmop.reporting.console import ConsoleReporter


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
        # Clean success output with slopmop branding
        assert "NO SLOP DETECTED" in captured.out
        assert "2 checks passed" in captured.out
        assert "3.0s" in captured.out
        # Success output is minimal - no individual check list
        assert "   ✅ check1" not in captured.out
        assert "   ✅ check2" not in captured.out

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
        # Compact counts on header line
        assert "1 passed" in captured.out
        assert "1 failed" in captured.out
        # Failure details inline
        assert "check2" in captured.out
        assert "Something broke" in captured.out

    def test_print_summary_with_errors(self, capsys):
        """Test printing summary with errors."""
        results = [
            CheckResult("check1", CheckStatus.ERROR, 1.0, error="Exception!"),
        ]
        summary = ExecutionSummary.from_results(results, 1.0)
        reporter = ConsoleReporter()

        reporter.print_summary(summary)

        captured = capsys.readouterr()
        # Compact counts format
        assert "1 errored" in captured.out
        # Error details inline
        assert "💥" in captured.out
        assert "Exception!" in captured.out

    def test_print_summary_with_warnings(self, capsys):
        """Test printing summary with warnings (non-blocking)."""
        results = [
            CheckResult("check1", CheckStatus.PASSED, 1.0),
            CheckResult(
                "check2",
                CheckStatus.WARNED,
                0.5,
                error="vulture not available",
                fix_suggestion="Install vulture: pip install vulture",
            ),
        ]
        summary = ExecutionSummary.from_results(results, 1.5)
        reporter = ConsoleReporter()

        reporter.print_summary(summary)

        captured = capsys.readouterr()
        # Warnings are non-blocking — still passes
        assert "NO SLOP DETECTED" in captured.out
        assert "1 warned" in captured.out
        # Warning details shown
        assert "WARNINGS" in captured.out
        assert "vulture not available" in captured.out
        assert "pip install vulture" in captured.out

    def test_on_check_complete_warned(self, capsys):
        """Test on_check_complete for warned status."""
        reporter = ConsoleReporter()
        result = CheckResult(
            "check1",
            CheckStatus.WARNED,
            0.5,
            error="tool not found",
            fix_suggestion="Install tool",
        )
        reporter.on_check_complete(result)

        captured = capsys.readouterr()
        assert "⚠️" in captured.out
        assert "tool not found" in captured.out

    def test_print_summary_with_skipped(self, capsys):
        """Test printing summary shows skipped in counts."""
        results = [
            CheckResult("check1", CheckStatus.PASSED, 1.0),
            CheckResult("check2", CheckStatus.SKIPPED, 0.0),
        ]
        summary = ExecutionSummary.from_results(results, 1.0)
        reporter = ConsoleReporter()

        reporter.print_summary(summary)

        captured = capsys.readouterr()
        # All passed with skipped — still passes
        assert "NO SLOP DETECTED" in captured.out
        assert "1 checks passed" in captured.out

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
        # Success message should appear
        assert "NO SLOP DETECTED" in captured.out
        # But individual check names should not be listed in quiet mode
        assert "   ✅ check1" not in captured.out
        assert "   ✅ check2" not in captured.out

    def test_print_summary_with_fix_suggestion(self, capsys):
        """Test fix_suggestion goes to log, not compact summary output."""
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
        # Without project_root, no log is written and fix_suggestion
        # is not shown in the compact summary
        reporter = ConsoleReporter()

        reporter.print_summary(summary)

        captured = capsys.readouterr()
        # Fix suggestion should NOT appear in compact summary
        assert "Run fix command" not in captured.out
        # Error detail should still appear
        assert "Error" in captured.out

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

    def test_failure_log_written_when_project_root(self, capsys, tmp_path):
        """Test failure log is written and path cited in output."""
        results = [
            CheckResult(
                "python:lint-format",
                CheckStatus.FAILED,
                1.0,
                output="Black: Formatting OK\nIsort: Import order issues\nFlake8: OK",
                error="1 issue(s) found",
                fix_suggestion="Run: black . && isort .",
            ),
        ]
        summary = ExecutionSummary.from_results(results, 1.0)
        reporter = ConsoleReporter(project_root=str(tmp_path))

        reporter.print_summary(summary)

        captured = capsys.readouterr()
        # Log path shown in output
        assert ".slopmop/logs/python_lint-format.log" in captured.out
        # Output preview shown
        assert "Black: Formatting OK" in captured.out
        assert "Isort: Import order issues" in captured.out
        # Fix suggestion NOT shown in compact summary
        assert "Run: black" not in captured.out
        # Log file actually created with full content
        log_file = tmp_path / ".slopmop" / "logs" / "python_lint-format.log"
        assert log_file.exists()
        log_content = log_file.read_text()
        assert "Run: black . && isort ." in log_content
        assert "Isort: Import order issues" in log_content

    def test_failure_log_output_truncated_in_terminal(self, capsys, tmp_path):
        """Test long output is truncated in terminal but full in log."""
        long_output = "\n".join([f"Error line {i}" for i in range(20)])
        results = [
            CheckResult(
                "python:tests",
                CheckStatus.FAILED,
                5.0,
                output=long_output,
                error="Tests failed",
            ),
        ]
        summary = ExecutionSummary.from_results(results, 5.0)
        reporter = ConsoleReporter(project_root=str(tmp_path))

        reporter.print_summary(summary)

        captured = capsys.readouterr()
        # First 10 lines shown in terminal
        assert "Error line 0" in captured.out
        assert "Error line 9" in captured.out
        # Lines beyond 10 NOT in terminal
        assert "Error line 10" not in captured.out
        # Overflow indicator shown
        assert "more lines in log" in captured.out
        # Full output in log file
        log_file = tmp_path / ".slopmop" / "logs" / "python_tests.log"
        log_content = log_file.read_text()
        assert "Error line 19" in log_content

    def test_skip_reason_code_fail_fast(self):
        """Test _skip_reason_code returns 'ff' for fail-fast skips."""
        result = CheckResult(
            "check1", CheckStatus.SKIPPED, 0.0, output="Skipped: fail-fast triggered"
        )
        assert ConsoleReporter._skip_reason_code(result) == "ff"

    def test_skip_reason_code_dependency(self):
        """Test _skip_reason_code returns 'dep' for dependency skips."""
        result = CheckResult(
            "check1", CheckStatus.SKIPPED, 0.0, output="Skipped: disabled by config"
        )
        assert ConsoleReporter._skip_reason_code(result) == "dep"

    def test_skip_reason_code_default(self):
        """Test _skip_reason_code returns 'skip' for unknown reasons."""
        result = CheckResult(
            "check1", CheckStatus.SKIPPED, 0.0, output="Some other reason"
        )
        assert ConsoleReporter._skip_reason_code(result) == "skip"

    def test_format_skipped_line_empty(self):
        """Test _format_skipped_line returns empty string for empty list."""
        assert ConsoleReporter._format_skipped_line([]) == ""

    def test_format_skipped_line_single_reason(self):
        """Test _format_skipped_line with single reason code."""
        results = [
            CheckResult("c1", CheckStatus.SKIPPED, 0.0, output="fail-fast"),
            CheckResult("c2", CheckStatus.SKIPPED, 0.0, output="fail fast"),
        ]
        line = ConsoleReporter._format_skipped_line(results)
        assert "2 skipped (ff)" in line

    def test_format_skipped_line_mixed_reasons(self):
        """Test _format_skipped_line with multiple reason codes."""
        results = [
            CheckResult("c1", CheckStatus.SKIPPED, 0.0, output="fail-fast"),
            CheckResult("c2", CheckStatus.SKIPPED, 0.0, output="disabled"),
            CheckResult("c3", CheckStatus.SKIPPED, 0.0, output="something else"),
        ]
        line = ConsoleReporter._format_skipped_line(results)
        assert "1 skipped (ff)" in line
        assert "1 skipped (dep)" in line
        assert "1 skipped (skip)" in line

    def test_print_summary_errors_with_output_and_logs(self, capsys, tmp_path):
        """Test error output is shown with log file path."""
        results = [
            CheckResult(
                "check1",
                CheckStatus.ERROR,
                1.0,
                output="Traceback:\n  File foo.py, line 42\nValueError: bad",
                error="Check crashed",
            ),
        ]
        summary = ExecutionSummary.from_results(results, 1.0)
        reporter = ConsoleReporter(project_root=str(tmp_path))

        reporter.print_summary(summary)

        captured = capsys.readouterr()
        # Error emoji and details
        assert "💥" in captured.out
        assert "check1" in captured.out
        assert "Check crashed" in captured.out
        # Output lines shown
        assert "Traceback:" in captured.out
        assert "ValueError: bad" in captured.out
        # Log file path shown
        assert ".slopmop/logs/check1.log" in captured.out

    def test_print_summary_static_fallback_no_project_root(self, capsys):
        """Test failure/error output without project_root (static fallback)."""
        results = [
            CheckResult(
                "check1",
                CheckStatus.FAILED,
                1.0,
                output="Error line 1\nError line 2",
                error="Failed",
            ),
            CheckResult(
                "check2",
                CheckStatus.ERROR,
                0.5,
                output="Exception occurred",
                error="Crashed",
            ),
        ]
        summary = ExecutionSummary.from_results(results, 1.5)
        # No project_root - uses static fallback
        reporter = ConsoleReporter()

        reporter.print_summary(summary)

        captured = capsys.readouterr()
        # Failure details shown
        assert "❌" in captured.out
        assert "Error line 1" in captured.out
        # Error details shown
        assert "💥" in captured.out
        assert "Exception occurred" in captured.out
        # NO log file path (no project_root)
        assert ".slopmop/logs" not in captured.out

    def test_next_steps_from_errors_when_no_failures(self, capsys, tmp_path):
        """Test next steps uses errors when no failures exist."""
        results = [
            CheckResult(
                "python:lint-format",
                CheckStatus.ERROR,
                1.0,
                error="Tool crashed",
            ),
        ]
        summary = ExecutionSummary.from_results(results, 1.0)
        reporter = ConsoleReporter(project_root=str(tmp_path))

        reporter.print_summary(summary)

        captured = capsys.readouterr()
        # Next step points to the error check
        assert "Next: ./sm validate python:lint-format --verbose" in captured.out

    def test_error_output_filters_passing_lines(self, capsys, tmp_path):
        """Test error output filters out ✅ lines like failures do."""
        results = [
            CheckResult(
                "check1",
                CheckStatus.ERROR,
                1.0,
                output="✅ Passed step\nActual error here\n✅ Another pass",
                error="Check crashed",
            ),
        ]
        summary = ExecutionSummary.from_results(results, 1.0)
        reporter = ConsoleReporter(project_root=str(tmp_path))

        reporter.print_summary(summary)

        captured = capsys.readouterr()
        # Only error-relevant line shown
        assert "Actual error here" in captured.out
        # Passing lines filtered out
        assert "Passed step" not in captured.out
        assert "Another pass" not in captured.out

    def test_error_output_truncated_in_terminal(self, capsys, tmp_path):
        """Test long error output is truncated like failure output."""
        long_output = "\n".join([f"Error line {i}" for i in range(15)])
        results = [
            CheckResult(
                "check1",
                CheckStatus.ERROR,
                1.0,
                output=long_output,
                error="Check crashed",
            ),
        ]
        summary = ExecutionSummary.from_results(results, 1.0)
        reporter = ConsoleReporter(project_root=str(tmp_path))

        reporter.print_summary(summary)

        captured = capsys.readouterr()
        # First 10 lines shown
        assert "Error line 0" in captured.out
        assert "Error line 9" in captured.out
        # Lines beyond 10 NOT in terminal
        assert "Error line 10" not in captured.out
        # Overflow indicator
        assert "more lines in log" in captured.out

    def test_print_summary_skipped_in_slop_detected(self, capsys):
        """Test skipped checks appear in counts when SLOP DETECTED."""
        results = [
            CheckResult("check1", CheckStatus.FAILED, 1.0, error="Failed"),
            CheckResult(
                "check2", CheckStatus.SKIPPED, 0.0, output="fail-fast triggered"
            ),
        ]
        summary = ExecutionSummary.from_results(results, 1.0)
        reporter = ConsoleReporter()

        reporter.print_summary(summary)

        captured = capsys.readouterr()
        assert "SLOP DETECTED" in captured.out
        # Skipped shown in counts
        assert "skipped (ff)" in captured.out

    def test_print_summary_warned_in_slop_detected(self, capsys):
        """Test warned checks appear in counts when SLOP DETECTED."""
        results = [
            CheckResult("check1", CheckStatus.FAILED, 1.0, error="Failed"),
            CheckResult(
                "check2",
                CheckStatus.WARNED,
                0.5,
                error="tool missing",
            ),
        ]
        summary = ExecutionSummary.from_results(results, 1.5)
        reporter = ConsoleReporter()

        reporter.print_summary(summary)

        captured = capsys.readouterr()
        assert "SLOP DETECTED" in captured.out
        # Warned shown in counts
        assert "1 warned" in captured.out

    def test_write_failure_log_returns_none_without_project_root(self):
        """Test _write_failure_log returns None without project_root."""
        reporter = ConsoleReporter()  # No project_root
        result = CheckResult("check1", CheckStatus.FAILED, 1.0, output="error")

        log_path = reporter._write_failure_log(result)

        assert log_path is None
