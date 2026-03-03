"""Tests for dynamic display rendering — completed line formatting and column layout."""

import json
import time

from slopmop.core.result import CheckResult, CheckStatus, ScopeInfo
from slopmop.reporting.display.renderer import strip_ansi
from slopmop.reporting.dynamic import CheckDisplayInfo, DisplayState, DynamicDisplay
from slopmop.reporting.timings import TimingStats


class TestCompletedLineRendering:
    """Tests for completed-check line formatting and column layout."""

    def test_completed_line_shows_done_for_all_statuses(self) -> None:
        """All completed checks show 'done' regardless of status."""
        display = DynamicDisplay(quiet=True)

        for status in (CheckStatus.PASSED, CheckStatus.FAILED, CheckStatus.WARNED):
            info = CheckDisplayInfo(
                name="test:check",
                state=DisplayState.COMPLETED,
                result=CheckResult(name="test:check", status=status, duration=1.0),
                duration=1.0,
            )
            line = display._format_check_line(info)
            assert "done" in line

    def test_completed_line_omits_scope_from_row(self) -> None:
        """Per-check scope info is NOT shown in row (moved to final summary)."""
        display = DynamicDisplay(quiet=True)

        info = CheckDisplayInfo(
            name="test:check",
            state=DisplayState.COMPLETED,
            result=CheckResult(
                name="test:check",
                status=CheckStatus.PASSED,
                duration=1.0,
                scope=ScopeInfo(files=47, lines=3200),
            ),
            duration=1.0,
        )
        line = display._format_check_line(info)
        plain = strip_ansi(line)
        # Scope columns (files, LOC) should NOT appear per-row
        assert "│" not in plain  # old scope separator
        assert "3,200" not in plain

    def test_completed_line_colors_sparkline_by_result(self) -> None:
        """Sparkline bars are colored by result status (replaces separate dots)."""
        display = DynamicDisplay(quiet=True)

        info = CheckDisplayInfo(
            name="test:check",
            state=DisplayState.COMPLETED,
            result=CheckResult(
                name="test:check", status=CheckStatus.PASSED, duration=1.0
            ),
            duration=1.0,
            timing_stats=TimingStats(
                median=1.0,
                q1=0.9,
                q3=1.1,
                iqr=0.2,
                historical_max=1.1,
                sample_count=3,
                samples=(1.0, 1.1, 0.9),
                results=("passed", "failed", "passed"),
            ),
        )
        line = display._format_check_line(info)
        # Should NOT have separate ● dots
        assert "●" not in line
        # Should have sparkline bar characters
        assert any(c in line for c in "▁▂▃▄▅▆▇█")

    def test_timing_columns_show_avg_and_time(self) -> None:
        """Average time, actual time appear in columnar layout (no Δ%)."""
        display = DynamicDisplay(quiet=True)

        info = CheckDisplayInfo(
            name="test:check",
            state=DisplayState.COMPLETED,
            result=CheckResult(
                name="test:check", status=CheckStatus.PASSED, duration=1.5
            ),
            duration=1.5,
            timing_stats=TimingStats(
                median=1.0,
                q1=0.9,
                q3=1.1,
                iqr=0.2,
                historical_max=1.5,
                sample_count=5,
                samples=(1.0, 1.0, 1.0, 1.0, 1.5),
            ),
        )
        line = display._format_check_line(info)
        plain = strip_ansi(line)
        # Should show avg (1.0s) and actual time (1.5s) as separate columns
        assert "1.0s" in plain
        assert "1.5s" in plain
        # Δ% column should NOT appear
        assert "+50%" not in plain

    def test_save_historical_timings_includes_results(self, tmp_path) -> None:
        """save_historical_timings persists result status alongside duration."""
        display = DynamicDisplay(quiet=True)
        display._overall_start_time = time.time()

        display.on_check_start("test:check")
        display.on_check_complete(
            CheckResult(name="test:check", status=CheckStatus.PASSED, duration=2.5)
        )

        display.save_historical_timings(str(tmp_path))

        # Verify result was saved
        timings_file = tmp_path / ".slopmop" / "timings.json"
        data = json.loads(timings_file.read_text())
        assert "test:check" in data
        assert data["test:check"].get("results") == ["passed"]
