"""Tests for console reporter."""

import pytest  # noqa: F401  # Required for fixtures

from slopmop.constants import STATUS_EMOJI
from slopmop.core.result import CheckResult, CheckStatus
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
        """Test reporting a failed check shows one-line status only.

        Failure details are deferred to the end-of-run summary to
        avoid double-printing.
        """
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
        # Details are NOT shown inline — deferred to end-of-run summary
        assert "Something went wrong" not in captured.out

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
        """Test reporting a check with error status shows one-line only.

        Error details are deferred to the end-of-run summary.
        """
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
        # Details are NOT shown inline — deferred to end-of-run summary
        assert "Exception occurred" not in captured.out

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
        """Test that fix suggestions are NOT shown inline.

        Fix suggestions are deferred to the end-of-run summary where
        they appear alongside the compact failure section.
        """
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
        assert "test-check" in captured.out
        assert "failed" in captured.out.lower()
        # Fix suggestion deferred to end-of-run summary
        assert "Run: black . to fix formatting" not in captured.out

    def test_on_check_complete_warned(self, capsys):
        """Test on_check_complete for warned status shows one-line only.

        Warning details are deferred to the end-of-run summary.
        """
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
        assert "check1" in captured.out
        # Details deferred to end-of-run summary
        assert "tool not found" not in captured.out

    def test_status_emoji_mapping(self):
        """Test status emoji mapping is complete."""
        for status in CheckStatus:
            assert status in STATUS_EMOJI
