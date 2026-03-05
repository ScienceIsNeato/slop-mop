"""Tests for DynamicDisplay timing persistence (save/load historical timings)."""

import json
import time as time_mod

from slopmop.core.result import CheckResult, CheckStatus
from slopmop.reporting.dynamic import CheckDisplayInfo, DisplayState, DynamicDisplay


class TestDisplayTimingPersistence:
    """Tests for save/load historical timing data."""

    def test_save_historical_timings_saves_completed_checks(self, tmp_path) -> None:
        """Test save_historical_timings saves durations of completed checks."""
        display = DynamicDisplay(quiet=True)
        display._overall_start_time = time_mod.time()

        display.on_check_start("test:check")
        display.on_check_complete(
            CheckResult(name="test:check", status=CheckStatus.PASSED, duration=2.5)
        )

        display.save_historical_timings(str(tmp_path))

        timings_file = tmp_path / ".slopmop" / "timings.json"
        assert timings_file.exists()

    def test_save_historical_timings_skips_zero_duration(self, tmp_path) -> None:
        """Test save_historical_timings doesn't save zero-duration checks."""
        display = DynamicDisplay(quiet=True)

        display._checks["test:check"] = CheckDisplayInfo(
            name="test:check",
            state=DisplayState.COMPLETED,
            duration=0.0,
        )

        display.save_historical_timings(str(tmp_path))

        timings_file = tmp_path / ".slopmop" / "timings.json"
        assert not timings_file.exists()

    def test_load_historical_timings(self, tmp_path) -> None:
        """Test load_historical_timings loads timing data."""
        timings_dir = tmp_path / ".slopmop"
        timings_dir.mkdir(parents=True)
        timings_file = timings_dir / "timings.json"

        timings_file.write_text(
            json.dumps(
                {
                    "test:check": {
                        "samples": [3.0, 4.0],
                        "last_updated": time_mod.time(),
                    }
                }
            )
        )

        display = DynamicDisplay(quiet=True)
        display.load_historical_timings(str(tmp_path))

        assert "test:check" in display._historical_timings
        assert display._historical_timings["test:check"].median == 3.5
        assert display._historical_timings["test:check"].sample_count == 2
