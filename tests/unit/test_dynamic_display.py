"""Tests for dynamic display module."""

import threading
import time
from unittest.mock import MagicMock, patch

from slopmop.core.result import CheckResult, CheckStatus
from slopmop.reporting.dynamic import CheckDisplayInfo, DisplayState, DynamicDisplay


class TestCheckDisplayInfo:
    """Tests for CheckDisplayInfo dataclass."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        info = CheckDisplayInfo(name="test:check")

        assert info.name == "test:check"
        assert info.state == DisplayState.PENDING
        assert info.result is None
        assert info.start_time == 0.0
        assert info.duration == 0.0

    def test_custom_values(self) -> None:
        """Test custom values are preserved."""
        result = CheckResult(
            name="test:check",
            status=CheckStatus.PASSED,
            duration=1.5,
        )
        info = CheckDisplayInfo(
            name="test:check",
            state=DisplayState.COMPLETED,
            result=result,
            start_time=100.0,
            duration=1.5,
        )

        assert info.state == DisplayState.COMPLETED
        assert info.result == result
        assert info.start_time == 100.0
        assert info.duration == 1.5


class TestDisplayState:
    """Tests for DisplayState enum."""

    def test_states_exist(self) -> None:
        """Test all expected states exist."""
        assert DisplayState.PENDING.value == "pending"
        assert DisplayState.RUNNING.value == "running"
        assert DisplayState.COMPLETED.value == "completed"


class TestDynamicDisplay:
    """Tests for DynamicDisplay class."""

    def test_init_quiet(self) -> None:
        """Test quiet mode suppresses output."""
        display = DynamicDisplay(quiet=True)

        assert display.quiet is True
        assert display._is_tty is True or display._is_tty is False  # Depends on env

    def test_init_empty_checks(self) -> None:
        """Test display starts with no checks."""
        display = DynamicDisplay()

        assert len(display._checks) == 0
        assert len(display._check_order) == 0
        assert display.completed_count == 0

    def test_on_check_start_adds_check(self) -> None:
        """Test on_check_start adds check and marks as running."""
        display = DynamicDisplay(quiet=True)

        display.on_check_start("test:check")

        assert "test:check" in display._checks
        assert display._checks["test:check"].state == DisplayState.RUNNING
        assert display._checks["test:check"].start_time > 0

    def test_on_check_start_updates_existing(self) -> None:
        """Test on_check_start updates existing check."""
        display = DynamicDisplay(quiet=True)

        # Start check twice
        display.on_check_start("test:check")
        first_start = display._checks["test:check"].start_time
        time.sleep(0.01)
        display.on_check_start("test:check")
        second_start = display._checks["test:check"].start_time

        # Should update start time
        assert second_start > first_start

    def test_on_check_complete_sets_completed(self) -> None:
        """Test on_check_complete marks check as completed."""
        display = DynamicDisplay(quiet=True)
        result = CheckResult(
            name="test:check",
            status=CheckStatus.PASSED,
            duration=1.0,
        )

        display.on_check_start("test:check")
        display.on_check_complete(result)

        info = display._checks["test:check"]
        assert info.state == DisplayState.COMPLETED
        assert info.result == result
        assert info.duration == 1.0

    def test_on_check_complete_unknown_check(self) -> None:
        """Test on_check_complete handles check that wasn't started."""
        display = DynamicDisplay(quiet=True)
        result = CheckResult(
            name="test:check",
            status=CheckStatus.SKIPPED,
            duration=0.0,
            output="Skipped",
        )

        # Complete without starting
        display.on_check_complete(result)

        assert "test:check" in display._checks
        assert display._checks["test:check"].state == DisplayState.COMPLETED

    def test_completed_count(self) -> None:
        """Test completed_count property."""
        display = DynamicDisplay(quiet=True)

        assert display.completed_count == 0

        # Add and complete checks
        for i in range(3):
            result = CheckResult(
                name=f"test:check{i}",
                status=CheckStatus.PASSED,
                duration=0.1,
            )
            display.on_check_start(f"test:check{i}")
            display.on_check_complete(result)

        assert display.completed_count == 3

    def test_all_completed_empty(self) -> None:
        """Test all_completed with no checks."""
        display = DynamicDisplay(quiet=True)

        # Empty display is considered "all completed"
        assert display.all_completed is True

    def test_all_completed_false(self) -> None:
        """Test all_completed when checks still running."""
        display = DynamicDisplay(quiet=True)

        display.on_check_start("test:check1")
        display.on_check_start("test:check2")
        display.on_check_complete(
            CheckResult(name="test:check1", status=CheckStatus.PASSED, duration=0.1)
        )

        assert display.all_completed is False

    def test_all_completed_true(self) -> None:
        """Test all_completed when all checks done."""
        display = DynamicDisplay(quiet=True)

        for i in range(2):
            display.on_check_start(f"test:check{i}")
            display.on_check_complete(
                CheckResult(
                    name=f"test:check{i}",
                    status=CheckStatus.PASSED,
                    duration=0.1,
                )
            )

        assert display.all_completed is True

    def test_format_check_line_pending(self) -> None:
        """Test formatting pending check line."""
        display = DynamicDisplay(quiet=True)
        info = CheckDisplayInfo(name="test:check")

        line = display._format_check_line(info)

        assert "○" in line
        assert "test:check" in line
        assert "pending" in line

    def test_format_check_line_running(self) -> None:
        """Test formatting running check line."""
        display = DynamicDisplay(quiet=True)
        info = CheckDisplayInfo(
            name="test:check",
            state=DisplayState.RUNNING,
            start_time=time.time() - 1.5,
        )

        line = display._format_check_line(info)

        assert "test:check" in line
        assert "running" in line
        # Should show elapsed time
        assert "1." in line or "2." in line

    def test_format_check_line_completed_passed(self) -> None:
        """Test formatting completed (passed) check line."""
        display = DynamicDisplay(quiet=True)
        info = CheckDisplayInfo(
            name="test:check",
            state=DisplayState.COMPLETED,
            result=CheckResult(
                name="test:check",
                status=CheckStatus.PASSED,
                duration=1.23,
            ),
            duration=1.23,
        )

        line = display._format_check_line(info)

        assert "✅" in line
        assert "test:check" in line
        assert "passed" in line
        assert "1.23" in line

    def test_format_check_line_completed_failed(self) -> None:
        """Test formatting completed (failed) check line."""
        display = DynamicDisplay(quiet=True)
        info = CheckDisplayInfo(
            name="test:check",
            state=DisplayState.COMPLETED,
            result=CheckResult(
                name="test:check",
                status=CheckStatus.FAILED,
                duration=0.5,
            ),
            duration=0.5,
        )

        line = display._format_check_line(info)

        assert "❌" in line
        assert "test:check" in line
        assert "failed" in line

    def test_build_display_empty(self) -> None:
        """Test build_display with no checks."""
        display = DynamicDisplay(quiet=True)

        lines = display._build_display()

        assert lines == []

    def test_build_display_with_checks(self) -> None:
        """Test build_display with checks."""
        display = DynamicDisplay(quiet=True)

        display.on_check_start("test:check1")
        display.on_check_complete(
            CheckResult(name="test:check1", status=CheckStatus.PASSED, duration=0.5)
        )
        display.on_check_start("test:check2")

        lines = display._build_display()

        # Should have progress bar, checks, summary
        assert any("Progress" in line for line in lines)
        assert any("test:check1" in line for line in lines)
        assert any("test:check2" in line for line in lines)

    def test_start_stop_quiet(self) -> None:
        """Test start/stop in quiet mode does nothing."""
        display = DynamicDisplay(quiet=True)

        # Should not raise
        display.start()
        display.stop()

        assert display._animation_thread is None

    @patch("sys.stdout.isatty", return_value=False)
    def test_start_non_tty(self, mock_isatty: MagicMock) -> None:
        """Test start in non-TTY mode doesn't start animation."""
        display = DynamicDisplay(quiet=False)
        display._is_tty = False

        display.start()
        display.stop()

        # Animation thread should not be started for non-TTY
        assert display._animation_thread is None

    def test_stop_idempotent(self) -> None:
        """Test stop can be called multiple times safely."""
        display = DynamicDisplay(quiet=True)
        display.start()

        # Stop multiple times should not raise
        display.stop()
        display.stop()
        display.stop()

        assert display._stopped is True

    def test_result_icons_mapping(self) -> None:
        """Test RESULT_ICONS has all statuses."""
        display = DynamicDisplay(quiet=True)

        assert CheckStatus.PASSED in display.RESULT_ICONS
        assert CheckStatus.FAILED in display.RESULT_ICONS
        assert CheckStatus.WARNED in display.RESULT_ICONS
        assert CheckStatus.SKIPPED in display.RESULT_ICONS
        assert CheckStatus.NOT_APPLICABLE in display.RESULT_ICONS
        assert CheckStatus.ERROR in display.RESULT_ICONS

    def test_spinner_frames_not_empty(self) -> None:
        """Test SPINNER_FRAMES has animation frames."""
        display = DynamicDisplay(quiet=True)

        assert len(display.SPINNER_FRAMES) > 0
        assert all(isinstance(f, str) for f in display.SPINNER_FRAMES)

    def test_check_order_preserved(self) -> None:
        """Test checks appear in order they were started."""
        display = DynamicDisplay(quiet=True)

        names = ["test:a", "test:b", "test:c"]
        for name in names:
            display.on_check_start(name)

        assert display._check_order == names

    def test_on_check_disabled_does_nothing(self) -> None:
        """Test on_check_disabled does nothing (logger handles it)."""
        display = DynamicDisplay(quiet=False)

        with patch("builtins.print") as mock_print:
            display.on_check_disabled("test:check")
            # Should not print - executor logger handles disabled messages
            mock_print.assert_not_called()

    def test_on_check_disabled_quiet(self) -> None:
        """Test on_check_disabled silent in quiet mode."""
        display = DynamicDisplay(quiet=True)

        with patch("builtins.print") as mock_print:
            display.on_check_disabled("test:check")
            mock_print.assert_not_called()

    def test_thread_safety(self) -> None:
        """Test display is thread safe."""
        display = DynamicDisplay(quiet=True)
        errors: list[Exception] = []

        def worker(name: str) -> None:
            try:
                display.on_check_start(name)
                time.sleep(0.01)
                display.on_check_complete(
                    CheckResult(name=name, status=CheckStatus.PASSED, duration=0.01)
                )
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(f"test:check{i}",)) for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert display.completed_count == 10
