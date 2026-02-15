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
        # Shows N/A for estimated time remaining (no prior data)
        assert "N/A" in line

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
        # Shows elapsed time
        assert "1." in line or "2." in line
        # Shows N/A for estimated time remaining (no prior data)
        assert "N/A" in line

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
        assert "1.2s" in line

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
        """Test build_display with no checks shows empty."""
        display = DynamicDisplay(quiet=True)

        lines = display._build_display()

        # No checks = empty display
        assert len(lines) == 0

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

    def test_on_check_disabled_collects_names(self) -> None:
        """Test on_check_disabled collects disabled check names."""
        display = DynamicDisplay(quiet=False)

        display.on_check_disabled("javascript:lint-format")
        display.on_check_disabled("javascript:types")

        assert display._disabled_names == [
            "javascript:lint-format",
            "javascript:types",
        ]

    def test_on_check_disabled_quiet(self) -> None:
        """Test on_check_disabled still collects in quiet mode."""
        display = DynamicDisplay(quiet=True)

        display.on_check_disabled("test:check")
        assert display._disabled_names == ["test:check"]

    def test_disabled_shown_in_display(self) -> None:
        """Test disabled summary line appears in build_display output."""
        display = DynamicDisplay(quiet=False)
        display.on_check_disabled("javascript:lint-format")
        display.on_check_disabled("security:local")

        lines = display._build_display()
        disabled_lines = [line for line in lines if line.startswith("Disabled:")]
        assert len(disabled_lines) == 1
        assert "javascript:lint-format" in disabled_lines[0]
        assert "security:local" in disabled_lines[0]

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

    def test_set_total_checks(self) -> None:
        """Test set_total_checks sets expected total."""
        display = DynamicDisplay(quiet=True)

        display.set_total_checks(15)

        assert display._total_checks_expected == 15

    def test_format_time_seconds(self) -> None:
        """Test _format_time formats seconds correctly."""
        display = DynamicDisplay(quiet=True)

        assert display._format_time(5.2) == "5.2s"
        assert display._format_time(0.0) == "0.0s"
        assert display._format_time(59.9) == "59.9s"

    def test_format_time_minutes(self) -> None:
        """Test _format_time formats minutes correctly."""
        display = DynamicDisplay(quiet=True)

        assert display._format_time(60.0) == "1m 0.0s"
        assert display._format_time(90.0) == "1m 30.0s"
        assert display._format_time(125.0) == "2m 5.0s"

    def test_build_progress_line_no_eta(self) -> None:
        """Test progress line shows count and elapsed but no ETA."""
        display = DynamicDisplay(quiet=True)
        display._overall_start_time = time.time() - 5.0  # 5s elapsed

        # Add completed check with known duration
        display.on_check_start("test:a")
        display.on_check_complete(
            CheckResult(name="test:a", status=CheckStatus.PASSED, duration=2.0)
        )

        # Build progress line for 1 completed of 3 total
        display.set_total_checks(3)
        line = display._build_progress_line(1, 3)

        assert "1/3" in line
        assert "elapsed" in line
        # Progress bar should NOT show ETA
        assert "ETA" not in line

    def test_build_progress_line_done(self) -> None:
        """Test progress line when all complete."""
        display = DynamicDisplay(quiet=True)
        display._overall_start_time = time.time() - 5.0

        line = display._build_progress_line(5, 5)

        assert "5/5" in line
        assert "elapsed" in line

    def test_progress_uses_expected_total(self) -> None:
        """Test progress bar uses expected total when set."""
        display = DynamicDisplay(quiet=True)
        display._overall_start_time = time.time()
        display.set_total_checks(10)

        # Only 2 checks discovered but total is 10
        display.on_check_start("test:a")
        display.on_check_start("test:b")
        display.on_check_complete(
            CheckResult(name="test:a", status=CheckStatus.PASSED, duration=0.1)
        )

        lines = display._build_display()
        # First line might be disabled summary; find progress line
        progress_lines = [line for line in lines if "Progress" in line]
        assert len(progress_lines) == 1

        # Should show 1/10 (expected total) not 1/2 (discovered)
        assert "1/10" in progress_lines[0]

    def test_completion_order_tracked(self) -> None:
        """Test that completion order is tracked correctly."""
        display = DynamicDisplay(quiet=True)

        display.on_check_start("test:a")
        display.on_check_start("test:b")
        display.on_check_start("test:c")

        # Complete in different order: b, c, a
        display.on_check_complete(
            CheckResult(name="test:b", status=CheckStatus.PASSED, duration=0.1)
        )
        display.on_check_complete(
            CheckResult(name="test:c", status=CheckStatus.PASSED, duration=0.2)
        )
        display.on_check_complete(
            CheckResult(name="test:a", status=CheckStatus.PASSED, duration=0.3)
        )

        assert display._checks["test:b"].completion_order == 1
        assert display._checks["test:c"].completion_order == 2
        assert display._checks["test:a"].completion_order == 3

    def test_completed_checks_shown_first(self) -> None:
        """Test that completed checks appear at top of display."""
        display = DynamicDisplay(quiet=True)
        display._overall_start_time = time.time()
        display.set_total_checks(3)

        # Start all, complete one
        display.on_check_start("test:a")
        display.on_check_start("test:b")
        display.on_check_start("test:c")
        display.on_check_complete(
            CheckResult(name="test:b", status=CheckStatus.PASSED, duration=0.1)
        )

        lines = display._build_display()

        # Find the check lines (skip progress bar and empty line)
        check_lines = [line for line in lines if "test:" in line]

        # Completed check (test:b) should be first
        assert "test:b" in check_lines[0]
        assert "passed" in check_lines[0]

    def test_no_prior_data_shows_na(self) -> None:
        """Test that checks with no prior run data show N/A for ETA."""
        display = DynamicDisplay(quiet=True)

        display.on_check_start("test:new-check")

        # No expected_duration set (None = no prior data)
        assert display._checks["test:new-check"].expected_duration is None

    def test_historical_timing_populates_expected_duration(self) -> None:
        """Test that loading historical timings populates expected_duration."""
        display = DynamicDisplay(quiet=True)
        display._historical_timings = {"test:check": 2.5}

        display.on_check_start("test:check")

        assert display._checks["test:check"].expected_duration == 2.5

    def test_running_check_with_eta_shows_remaining(self) -> None:
        """Test running check with historical data shows time remaining."""
        display = DynamicDisplay(quiet=True)
        info = CheckDisplayInfo(
            name="test:check",
            state=DisplayState.RUNNING,
            start_time=time.time() - 1.0,
            expected_duration=3.5,
        )

        line = display._format_check_line(info)

        assert "test:check" in line
        # Should show remaining time (3.5 - 1.0 = ~2.5s)
        assert "2." in line or "3." in line

    def test_running_check_has_dot_leader(self) -> None:
        """Test running check line has animated dot leader characters."""
        display = DynamicDisplay(quiet=True)
        info = CheckDisplayInfo(
            name="test:check",
            state=DisplayState.RUNNING,
            start_time=time.time() - 1.0,
        )

        line = display._format_check_line(info)

        # Should contain dot leader characters (· or •)
        assert display.DOT_CHAR in line or display.PULSE_CHAR in line

    def test_completed_check_shows_duration(self) -> None:
        """Test completed check shows just the elapsed duration."""
        display = DynamicDisplay(quiet=True)
        info = CheckDisplayInfo(
            name="test:check",
            state=DisplayState.COMPLETED,
            result=CheckResult(
                name="test:check",
                status=CheckStatus.PASSED,
                duration=2.0,
            ),
            duration=2.0,
            expected_duration=2.5,
        )

        line = display._format_check_line(info)

        assert "2.0s" in line
        # Completed checks don't show estimate comparison — just duration
        assert "est " not in line  # "est " with space (avoid matching "test")

    def test_check_line_right_justified(self) -> None:
        """Test that ETA column is right-justified."""
        display = DynamicDisplay(quiet=True)
        info = CheckDisplayInfo(
            name="test:check",
            state=DisplayState.RUNNING,
            start_time=time.time() - 2.0,
        )

        line = display._format_check_line(info)

        # Line should contain padding spaces between name and ETA
        # The exact spacing depends on terminal width, but there should be some
        assert "  " in line  # At least some padding

    def test_running_check_with_eta_shows_progress_bar(self) -> None:
        """Test running check with ETA shows progress bar instead of dot leader."""
        display = DynamicDisplay(quiet=True)
        info = CheckDisplayInfo(
            name="test:check",
            state=DisplayState.RUNNING,
            start_time=time.time() - 1.5,
            expected_duration=3.0,
        )

        line = display._format_check_line(info)

        assert "test:check" in line
        # Should show progress bar characters, not dot leader
        assert display.PROGRESS_FILL in line or display.PROGRESS_EMPTY in line
        # Should show percentage
        assert "%" in line
        # Should NOT contain dot leader characters
        assert display.DOT_CHAR not in line

    def test_running_check_without_eta_shows_dot_leader(self) -> None:
        """Test running check without ETA shows dot leader animation."""
        display = DynamicDisplay(quiet=True)
        info = CheckDisplayInfo(
            name="test:check",
            state=DisplayState.RUNNING,
            start_time=time.time() - 1.0,
            expected_duration=None,
        )

        line = display._format_check_line(info)

        assert "test:check" in line
        # Should contain dot leader
        assert display.DOT_CHAR in line or display.PULSE_CHAR in line
        # Should NOT contain progress bar
        assert "%" not in line

    def test_progress_bar_percentage_caps_at_99(self) -> None:
        """Test progress bar caps at 99% even when over estimate."""
        display = DynamicDisplay(quiet=True)
        # Elapsed 5s but estimated 2s — running overtime
        info = CheckDisplayInfo(
            name="test:check",
            state=DisplayState.RUNNING,
            start_time=time.time() - 5.0,
            expected_duration=2.0,
        )

        line = display._format_check_line(info)

        assert "99%" in line
        # Should not show 100% or >100%
        assert "100%" not in line

    def test_active_checks_sorted_by_estimate(self) -> None:
        """Test running checks sorted: estimated DESC first, then unknown alpha."""
        display = DynamicDisplay(quiet=True)
        display._overall_start_time = time.time()
        display.set_total_checks(4)

        # Start checks with mixed estimates
        display._historical_timings = {
            "test:short": 1.0,
            "test:long": 10.0,
            "test:medium": 5.0,
        }

        display.on_check_start("test:short")
        display.on_check_start("test:zebra")
        display.on_check_start("test:long")
        display.on_check_start("test:alpha")
        display.on_check_start("test:medium")

        lines = display._build_display()

        # Find only the check lines (contain "test:")
        check_lines = [line for line in lines if "test:" in line]

        # Expected order: long (10s), medium (5s), short (1s), alpha, zebra
        assert "test:long" in check_lines[0]
        assert "test:medium" in check_lines[1]
        assert "test:short" in check_lines[2]
        # Unknown checks at bottom, alphabetically
        assert "test:alpha" in check_lines[3]
        assert "test:zebra" in check_lines[4]

    def test_completed_checks_before_active_in_sorted_display(self) -> None:
        """Test completed checks still appear before active checks."""
        display = DynamicDisplay(quiet=True)
        display._overall_start_time = time.time()
        display.set_total_checks(3)
        display._historical_timings = {"test:b": 5.0}

        display.on_check_start("test:a")
        display.on_check_start("test:b")
        display.on_check_start("test:c")

        # Complete test:a
        display.on_check_complete(
            CheckResult(name="test:a", status=CheckStatus.PASSED, duration=0.1)
        )

        lines = display._build_display()
        check_lines = [line for line in lines if "test:" in line]

        # Completed check (test:a) should be first
        assert "test:a" in check_lines[0]
        assert "passed" in check_lines[0]

    def test_save_historical_timings_saves_completed_checks(self, tmp_path) -> None:
        """Test save_historical_timings saves durations of completed checks."""
        display = DynamicDisplay(quiet=True)
        display._overall_start_time = time.time()

        # Start and complete a check
        display.on_check_start("test:check")
        display.on_check_complete(
            CheckResult(name="test:check", status=CheckStatus.PASSED, duration=2.5)
        )

        # Save timings
        display.save_historical_timings(str(tmp_path))

        # Verify file was created
        timings_file = tmp_path / ".slopmop" / "timings.json"
        assert timings_file.exists()

    def test_save_historical_timings_skips_zero_duration(self, tmp_path) -> None:
        """Test save_historical_timings doesn't save zero-duration checks."""
        display = DynamicDisplay(quiet=True)

        # Add a completed check with zero duration
        display._checks["test:check"] = CheckDisplayInfo(
            name="test:check",
            state=DisplayState.COMPLETED,
            duration=0.0,
        )

        # Save timings - should not create file since no valid durations
        display.save_historical_timings(str(tmp_path))

        # File should not be created (no valid durations to save)
        timings_file = tmp_path / ".slopmop" / "timings.json"
        assert not timings_file.exists()

    def test_already_stopped_display_no_double_stop(self) -> None:
        """Test stop() is idempotent - can be called multiple times."""
        display = DynamicDisplay(quiet=True)
        display._started = True
        display._stopped = False

        # First stop should work
        display.stop()
        assert display._stopped is True

        # Second stop should be no-op
        display.stop()
        assert display._stopped is True

    def test_on_check_complete_disabled_check(self) -> None:
        """Test disabled checks are properly handled."""
        display = DynamicDisplay(quiet=True)

        # Complete a disabled check (never started)
        result = CheckResult(
            name="test:disabled",
            status=CheckStatus.SKIPPED,
            duration=0.0,
            output="Disabled by config",
        )
        display.on_check_complete(result)

        assert "test:disabled" in display._checks
        assert display._checks["test:disabled"].state == DisplayState.COMPLETED

    def test_on_check_disabled_callback(self) -> None:
        """Test on_check_disabled adds to disabled names list."""
        display = DynamicDisplay(quiet=True)

        display.on_check_disabled("test:javascript")

        # Check is added to disabled names list
        assert "test:javascript" in display._disabled_names

    def test_load_historical_timings(self, tmp_path) -> None:
        """Test load_historical_timings loads timing data."""
        # Create a timings file with correct format: {"name": {"avg": float, "count": int}}
        timings_dir = tmp_path / ".slopmop"
        timings_dir.mkdir(parents=True)
        timings_file = timings_dir / "timings.json"
        timings_file.write_text('{"test:check": {"avg": 3.5, "count": 5}}')

        display = DynamicDisplay(quiet=True)
        display.load_historical_timings(str(tmp_path))

        assert display._historical_timings == {"test:check": 3.5}
