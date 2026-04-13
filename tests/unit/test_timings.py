"""Tests for timing persistence module."""

import json
import time
from pathlib import Path

from slopmop.reporting.timings import (
    MAX_AGE_DAYS,
    MAX_ENTRIES,
    MAX_SAMPLES,
    TIMINGS_DIR,
    TIMINGS_FILE,
    TimingStats,
    _compute_stats,
    _prune_timings,
    clear_timings,
    load_timing_averages,
    load_timings,
    save_timings,
)


class TestTimingStats:
    """Tests for TimingStats dataclass and helpers."""

    def test_compute_stats_single_sample(self) -> None:
        """Single sample has IQR of 0."""
        stats = _compute_stats([2.0])
        assert stats.median == 2.0
        assert stats.iqr == 0.0
        assert stats.q1 == 2.0
        assert stats.q3 == 2.0
        assert stats.historical_max == 2.0
        assert stats.sample_count == 1

    def test_compute_stats_multiple_samples(self) -> None:
        """Median and IQR are computed correctly."""
        samples = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        stats = _compute_stats(samples)
        # Sorted: [2, 4, 4, 4, 5, 5, 7, 9]
        # n=8, mid=4, lower=[2,4,4,4], upper=[5,5,7,9]
        # median = (4+5)/2 = 4.5
        # Q1 = median([2,4,4,4]) = 4.0
        # Q3 = median([5,5,7,9]) = 6.0
        assert stats.median == 4.5
        assert stats.q1 == 4.0
        assert stats.q3 == 6.0
        assert stats.iqr == 2.0
        assert stats.historical_max == 9.0
        assert stats.sample_count == 8

    def test_compute_stats_rounds_to_3_decimals(self) -> None:
        """Median and quartiles are rounded to 3 decimal places."""
        stats = _compute_stats([1.11111, 2.22222, 3.33333])
        # Sorted: [1.11111, 2.22222, 3.33333], median = 2.22222
        assert stats.median == 2.222

    def test_iqr_over_within_fence(self) -> None:
        """iqr_over returns 0 when elapsed is within the Tukey fence."""
        # Q3=6, IQR=2 => fence = 6 + 1.5*2 = 9.0
        stats = TimingStats(
            median=4.5,
            q1=4.0,
            q3=6.0,
            iqr=2.0,
            historical_max=9.0,
            sample_count=10,
        )
        assert stats.iqr_over(3.0) == 0.0
        assert stats.iqr_over(9.0) == 0.0  # exactly at fence

    def test_iqr_over_above_fence(self) -> None:
        """iqr_over returns correct IQR distance above the fence."""
        # Q3=6, IQR=2 => fence = 9.0
        stats = TimingStats(
            median=4.5,
            q1=4.0,
            q3=6.0,
            iqr=2.0,
            historical_max=9.0,
            sample_count=10,
        )
        assert stats.iqr_over(11.0) == 1.0  # (11-9)/2 = 1.0
        assert stats.iqr_over(14.0) == 2.5  # (14-9)/2 = 2.5

    def test_iqr_over_tiny_iqr(self) -> None:
        """iqr_over returns 0 when IQR is negligible (< 0.01)."""
        stats = TimingStats(
            median=1.0,
            q1=1.0,
            q3=1.005,
            iqr=0.005,
            historical_max=1.1,
            sample_count=10,
        )
        assert stats.iqr_over(1.5) == 0.0

    def test_compute_stats_stores_samples_tuple(self) -> None:
        """_compute_stats stores samples as a rounded tuple."""
        stats = _compute_stats([1.1111, 2.2222, 3.3333])
        assert isinstance(stats.samples, tuple)
        assert stats.samples == (1.111, 2.222, 3.333)

    def test_sparkline_returns_empty_for_single_sample(self) -> None:
        """sparkline needs at least 2 samples."""
        stats = TimingStats(
            median=1.0,
            q1=1.0,
            q3=1.0,
            iqr=0.0,
            historical_max=1.0,
            sample_count=1,
            samples=(1.0,),
        )
        assert stats.sparkline() == ""

    def test_sparkline_renders_block_chars(self) -> None:
        """sparkline maps values to 8-level block characters with padding."""
        stats = TimingStats(
            median=5.0,
            q1=3.0,
            q3=7.0,
            iqr=4.0,
            historical_max=9.0,
            sample_count=5,
            samples=(1.0, 3.0, 5.0, 7.0, 9.0),
        )
        spark = stats.sparkline(max_width=8)
        # Always exactly max_width chars: 3 placeholders + 5 data bars
        assert len(spark) == 8
        # Leading placeholders
        assert spark[:3] == "⸱⸱⸱"
        # Absolute scaling 0→9.0: 1.0→low, 9.0→highest
        assert spark[3] == "▁"
        assert spark[-1] == "█"

    def test_sparkline_flat_line(self) -> None:
        """sparkline renders flat line with placeholder padding."""
        stats = TimingStats(
            median=2.0,
            q1=2.0,
            q3=2.0,
            iqr=0.0,
            historical_max=2.0,
            sample_count=3,
            samples=(2.0, 2.0, 2.0),
        )
        spark = stats.sparkline(max_width=6)
        # 3 placeholders + 3 identical bars = 6 chars
        assert len(spark) == 6
        assert spark[:3] == "⸱⸱⸱"
        # Data portion: all same block char
        assert len(set(spark[3:])) == 1

    def test_sparkline_respects_max_width(self) -> None:
        """sparkline truncates to last max_width samples."""
        samples = tuple(float(i) for i in range(20))
        stats = TimingStats(
            median=9.5,
            q1=4.5,
            q3=14.5,
            iqr=10.0,
            historical_max=19.0,
            sample_count=20,
            samples=samples,
        )
        spark = stats.sparkline(max_width=5)
        assert len(spark) == 5

    def test_format_delta_positive(self) -> None:
        """format_delta shows +Xs (+X%) for overruns."""
        stats = TimingStats(
            median=2.0,
            q1=1.8,
            q3=2.2,
            iqr=0.4,
            historical_max=3.0,
            sample_count=10,
        )
        delta = stats.format_delta(2.4)
        assert "+0.4s" in delta
        assert "+20%" in delta

    def test_format_delta_negative(self) -> None:
        """format_delta shows -Xs (-X%) for underruns."""
        stats = TimingStats(
            median=2.0,
            q1=1.8,
            q3=2.2,
            iqr=0.4,
            historical_max=3.0,
            sample_count=10,
        )
        delta = stats.format_delta(1.6)
        assert "-0.4s" in delta
        assert "-20%" in delta

    def test_format_delta_zero_median(self) -> None:
        """format_delta returns empty string when median is ~0."""
        stats = TimingStats(
            median=0.0,
            q1=0.0,
            q3=0.0,
            iqr=0.0,
            historical_max=0.0,
            sample_count=1,
        )
        assert stats.format_delta(1.0) == ""


class TestLoadTimings:
    """Tests for load_timings."""

    def test_no_file_returns_empty(self, tmp_path: Path) -> None:
        """Returns empty dict when no timings file exists."""
        result = load_timings(str(tmp_path))
        assert result == {}

    def test_loads_v2_samples(self, tmp_path: Path) -> None:
        """Loads sample-based (v2) timing data."""
        timings_dir = tmp_path / TIMINGS_DIR
        timings_dir.mkdir()
        (timings_dir / TIMINGS_FILE).write_text(
            json.dumps(
                {
                    "overconfidence:untested-code.py": {
                        "samples": [3.0, 4.0],
                        "last_updated": time.time(),
                    },
                    "python:lint": {
                        "samples": [0.8],
                        "last_updated": time.time(),
                    },
                }
            )
        )

        result = load_timings(str(tmp_path))

        assert "overconfidence:untested-code.py" in result
        assert "python:lint" in result
        assert result["overconfidence:untested-code.py"].median == 3.5
        assert result["overconfidence:untested-code.py"].sample_count == 2
        assert result["python:lint"].median == 0.8

    def test_auto_migrates_v1_ema_format(self, tmp_path: Path) -> None:
        """Legacy v1 (EMA) entries are auto-migrated on load."""
        timings_dir = tmp_path / TIMINGS_DIR
        timings_dir.mkdir()
        (timings_dir / TIMINGS_FILE).write_text(
            json.dumps(
                {
                    "check:legacy": {
                        "avg": 2.5,
                        "count": 10,
                        "last_updated": time.time(),
                    }
                }
            )
        )

        result = load_timings(str(tmp_path))

        assert "check:legacy" in result
        # Migrated avg becomes a single sample → median equals the avg
        assert result["check:legacy"].median == 2.5
        assert result["check:legacy"].sample_count == 1
        assert result["check:legacy"].iqr == 0.0

    def test_handles_corrupt_json(self, tmp_path: Path) -> None:
        """Handles corrupt JSON gracefully."""
        timings_dir = tmp_path / TIMINGS_DIR
        timings_dir.mkdir()
        (timings_dir / TIMINGS_FILE).write_text("not json{{{")

        result = load_timings(str(tmp_path))
        assert result == {}

    def test_handles_invalid_structure(self, tmp_path: Path) -> None:
        """Handles unexpected data structure."""
        timings_dir = tmp_path / TIMINGS_DIR
        timings_dir.mkdir()
        (timings_dir / TIMINGS_FILE).write_text(
            json.dumps(
                {
                    "check": "not_a_dict",
                    "good": {"samples": [1.0], "last_updated": time.time()},
                }
            )
        )

        result = load_timings(str(tmp_path))
        assert "good" in result
        assert "check" not in result

    def test_skips_empty_samples_list(self, tmp_path: Path) -> None:
        """Entries with empty samples are skipped."""
        timings_dir = tmp_path / TIMINGS_DIR
        timings_dir.mkdir()
        (timings_dir / TIMINGS_FILE).write_text(
            json.dumps({"bad": {"samples": [], "last_updated": time.time()}})
        )
        result = load_timings(str(tmp_path))
        assert result == {}


class TestLoadTimingAverages:
    """Tests for load_timing_averages convenience function."""

    def test_returns_float_dict(self, tmp_path: Path) -> None:
        """Returns Dict[str, float] compatible with executor time budget."""
        timings_dir = tmp_path / TIMINGS_DIR
        timings_dir.mkdir()
        (timings_dir / TIMINGS_FILE).write_text(
            json.dumps(
                {
                    "check:a": {"samples": [1.0, 3.0], "last_updated": time.time()},
                    "check:b": {"samples": [5.0], "last_updated": time.time()},
                }
            )
        )

        result = load_timing_averages(str(tmp_path))

        assert result == {"check:a": 2.0, "check:b": 5.0}

    def test_empty_when_no_file(self, tmp_path: Path) -> None:
        """Returns empty dict when no file exists."""
        assert load_timing_averages(str(tmp_path)) == {}


class TestSaveTimings:
    """Tests for save_timings."""

    def test_saves_new_timings(self, tmp_path: Path) -> None:
        """Saves timings to new file with sample-based format."""
        save_timings(
            str(tmp_path), {"overconfidence:untested-code.py": 2.5, "python:lint": 0.6}
        )

        path = tmp_path / TIMINGS_DIR / TIMINGS_FILE
        assert path.exists()

        data = json.loads(path.read_text())
        assert data["overconfidence:untested-code.py"]["samples"] == [2.5]
        assert data["python:lint"]["samples"] == [0.6]

    def test_appends_to_existing_samples(self, tmp_path: Path) -> None:
        """New durations are appended to the sample list."""
        save_timings(str(tmp_path), {"check:a": 10.0})
        save_timings(str(tmp_path), {"check:a": 5.0})

        path = tmp_path / TIMINGS_DIR / TIMINGS_FILE
        data = json.loads(path.read_text())

        assert data["check:a"]["samples"] == [10.0, 5.0]

    def test_fifo_cap_at_max_samples(self, tmp_path: Path) -> None:
        """Sample list is capped at MAX_SAMPLES (oldest dropped)."""
        # Write MAX_SAMPLES samples
        for i in range(MAX_SAMPLES):
            save_timings(str(tmp_path), {"check:a": float(i)})

        # One more should evict the oldest
        save_timings(str(tmp_path), {"check:a": 999.0})

        path = tmp_path / TIMINGS_DIR / TIMINGS_FILE
        data = json.loads(path.read_text())

        samples = data["check:a"]["samples"]
        assert len(samples) == MAX_SAMPLES
        # Oldest (0.0) should be gone, newest (999.0) present
        assert samples[0] == 1.0
        assert samples[-1] == 999.0

    def test_creates_directory(self, tmp_path: Path) -> None:
        """Creates .slopmop directory if needed."""
        save_timings(str(tmp_path), {"check:a": 1.0})
        assert (tmp_path / TIMINGS_DIR).is_dir()

    def test_preserves_existing_checks(self, tmp_path: Path) -> None:
        """Doesn't clobber timings for checks not in current run."""
        save_timings(str(tmp_path), {"check:a": 1.0})
        save_timings(str(tmp_path), {"check:b": 2.0})

        path = tmp_path / TIMINGS_DIR / TIMINGS_FILE
        data = json.loads(path.read_text())

        assert "check:a" in data
        assert "check:b" in data

    def test_rounds_to_three_decimals(self, tmp_path: Path) -> None:
        """Durations are rounded to 3 decimal places."""
        save_timings(str(tmp_path), {"check:a": 1.23456789})

        path = tmp_path / TIMINGS_DIR / TIMINGS_FILE
        data = json.loads(path.read_text())

        assert data["check:a"]["samples"] == [1.235]

    def test_migrates_v1_entry_on_save(self, tmp_path: Path) -> None:
        """Legacy v1 entries are migrated to v2 when saving."""
        timings_dir = tmp_path / TIMINGS_DIR
        timings_dir.mkdir()
        (timings_dir / TIMINGS_FILE).write_text(
            json.dumps(
                {"check:old": {"avg": 3.0, "count": 5, "last_updated": time.time()}}
            )
        )

        save_timings(str(tmp_path), {"check:old": 4.0})

        path = tmp_path / TIMINGS_DIR / TIMINGS_FILE
        data = json.loads(path.read_text())

        # Old avg should be migrated as a single sample, new duration appended
        assert data["check:old"]["samples"] == [3.0, 4.0]
        assert "avg" not in data["check:old"]


class TestClearTimings:
    """Tests for clear_timings."""

    def test_clears_existing_timings(self, tmp_path: Path) -> None:
        """Clears timings file when it exists."""
        save_timings(str(tmp_path), {"check:a": 1.0})
        path = tmp_path / TIMINGS_DIR / TIMINGS_FILE
        assert path.exists()

        result = clear_timings(str(tmp_path))

        assert result is True
        assert not path.exists()

    def test_returns_false_when_no_history(self, tmp_path: Path) -> None:
        """Returns False when no timings file exists."""
        result = clear_timings(str(tmp_path))
        assert result is False

    def test_load_returns_empty_after_clear(self, tmp_path: Path) -> None:
        """load_timings returns empty dict after clearing."""
        save_timings(str(tmp_path), {"check:a": 5.0, "check:b": 3.0})
        clear_timings(str(tmp_path))

        result = load_timings(str(tmp_path))
        assert result == {}


class TestPruneTimings:
    """Tests for timing data pruning."""

    def test_removes_old_entries(self) -> None:
        """Entries older than MAX_AGE_DAYS are removed."""
        now = time.time()
        old_timestamp = now - (MAX_AGE_DAYS + 1) * 86400

        raw = {
            "old_check": {"samples": [1.0], "last_updated": old_timestamp},
            "new_check": {"samples": [2.0], "last_updated": now},
        }

        result = _prune_timings(raw)

        assert "old_check" not in result
        assert "new_check" in result

    def test_keeps_recent_entries(self) -> None:
        """Entries within MAX_AGE_DAYS are kept."""
        now = time.time()
        recent_timestamp = now - (MAX_AGE_DAYS - 1) * 86400

        raw = {"recent_check": {"samples": [1.0], "last_updated": recent_timestamp}}

        result = _prune_timings(raw)

        assert "recent_check" in result

    def test_pruning_by_max_entries(self) -> None:
        """Oldest entries removed when exceeding MAX_ENTRIES."""
        now = time.time()
        raw = {}

        for i in range(MAX_ENTRIES + 10):
            raw[f"check_{i}"] = {
                "samples": [float(i)],
                "last_updated": now - i * 60,
            }

        result = _prune_timings(raw)

        assert len(result) == MAX_ENTRIES
        assert "check_0" in result
        assert "check_1" in result
        assert f"check_{MAX_ENTRIES + 9}" not in result

    def test_preserves_legacy_entries_without_timestamp(self) -> None:
        """Entries without last_updated are kept (migrated) but vulnerable."""
        now = time.time()
        raw = {
            "legacy_check": {"avg": 1.0, "count": 5},
            "new_check": {"samples": [2.0], "last_updated": now},
        }

        result = _prune_timings(raw)

        # Legacy entry should be migrated to v2 format and still present
        assert "legacy_check" in result
        assert "samples" in result["legacy_check"]
        assert "new_check" in result

    def test_migrates_v1_entries_during_pruning(self) -> None:
        """V1 entries are converted to v2 format during pruning."""
        now = time.time()
        raw = {
            "v1_check": {"avg": 5.0, "count": 10, "last_updated": now},
        }

        result = _prune_timings(raw)

        assert result["v1_check"]["samples"] == [5.0]
        assert "avg" not in result["v1_check"]


class TestSaveTimingsWithPruning:
    """Tests for save_timings pruning behavior."""

    def test_saves_with_last_updated(self, tmp_path: Path) -> None:
        """Saved entries include last_updated timestamp."""
        save_timings(str(tmp_path), {"check:a": 1.0})

        path = tmp_path / TIMINGS_DIR / TIMINGS_FILE
        data = json.loads(path.read_text())

        assert "last_updated" in data["check:a"]
        assert time.time() - data["check:a"]["last_updated"] < 60

    def test_prunes_old_on_save(self, tmp_path: Path) -> None:
        """Old entries are pruned when saving new data."""
        timings_dir = tmp_path / TIMINGS_DIR
        timings_dir.mkdir()
        timings_file = timings_dir / TIMINGS_FILE

        old_timestamp = time.time() - (MAX_AGE_DAYS + 1) * 86400
        timings_file.write_text(
            json.dumps(
                {
                    "old_check": {
                        "samples": [1.0],
                        "last_updated": old_timestamp,
                    },
                }
            )
        )

        save_timings(str(tmp_path), {"new_check": 2.0})

        data = json.loads(timings_file.read_text())
        assert "old_check" not in data
        assert "new_check" in data


class TestLoadTimingsWithAge:
    """Tests for load_timings with age filtering."""

    def test_skips_old_entries_on_load(self, tmp_path: Path) -> None:
        """Old entries are not returned from load_timings."""
        timings_dir = tmp_path / TIMINGS_DIR
        timings_dir.mkdir()
        timings_file = timings_dir / TIMINGS_FILE

        now = time.time()
        old_timestamp = now - (MAX_AGE_DAYS + 1) * 86400

        timings_file.write_text(
            json.dumps(
                {
                    "old_check": {
                        "samples": [1.0],
                        "last_updated": old_timestamp,
                    },
                    "new_check": {
                        "samples": [2.0],
                        "last_updated": now,
                    },
                }
            )
        )

        result = load_timings(str(tmp_path))

        assert "old_check" not in result
        assert "new_check" in result
        assert result["new_check"].median == 2.0


class TestSparklineWithColors:
    """Tests for sparkline with result-status coloring."""

    def test_sparkline_colors_bars_by_result(self) -> None:
        """When colors_enabled, bars get ANSI color from result status."""
        stats = TimingStats(
            median=1.0,
            q1=0.9,
            q3=1.1,
            iqr=0.2,
            historical_max=1.1,
            sample_count=3,
            samples=(1.0, 1.1, 0.9),
            results=("passed", "failed", "passed"),
        )
        spark = stats.sparkline(max_width=3, colors_enabled=True)
        assert "\033[32m" in spark  # green for passed
        assert "\033[31m" in spark  # red for failed

    def test_sparkline_no_color_when_disabled(self) -> None:
        """Without colors_enabled, bars are plain text."""
        stats = TimingStats(
            median=1.0,
            q1=0.9,
            q3=1.1,
            iqr=0.2,
            historical_max=1.1,
            sample_count=3,
            samples=(1.0, 1.1, 0.9),
            results=("passed", "failed", "passed"),
        )
        spark = stats.sparkline(max_width=3, colors_enabled=False)
        assert "\033[" not in spark

    def test_sparkline_fewer_results_than_samples(self) -> None:
        """When results shorter than samples, oldest bars are uncolored."""
        stats = TimingStats(
            median=1.0,
            q1=0.9,
            q3=1.1,
            iqr=0.2,
            historical_max=1.2,
            sample_count=5,
            samples=(1.0, 1.1, 0.9, 1.2, 0.8),
            results=("passed", "failed"),  # only last 2
        )
        spark = stats.sparkline(max_width=5, colors_enabled=True)
        # Should still produce 5 characters
        from slopmop.reporting.display.renderer import strip_ansi

        assert len(strip_ansi(spark)) == 5

    def test_sparkline_no_results_no_color(self) -> None:
        """Empty results tuple produces plain sparkline even with colors."""
        stats = TimingStats(
            median=1.0,
            q1=0.9,
            q3=1.1,
            iqr=0.2,
            historical_max=1.1,
            sample_count=3,
            samples=(1.0, 1.1, 0.9),
        )
        spark = stats.sparkline(max_width=3, colors_enabled=True)
        assert "\033[" not in spark

    def test_sparkline_colored_with_padding(self) -> None:
        """Colored sparkline pads to max_width with dim placeholders."""
        stats = TimingStats(
            median=1.0,
            q1=0.9,
            q3=1.1,
            iqr=0.2,
            historical_max=1.1,
            sample_count=3,
            samples=(1.0, 1.1, 0.9),
            results=("passed", "passed", "passed"),
        )
        from slopmop.reporting.display.renderer import strip_ansi

        spark = stats.sparkline(max_width=6, colors_enabled=True)
        # 3 dim placeholders + 3 colored bars = 6 visible chars
        assert len(strip_ansi(spark)) == 6
        # Should contain dim (gray) for placeholders
        assert "\033[90m" in spark


class TestComputeStatsWithResults:
    """Tests for _compute_stats with result history."""

    def test_compute_stats_stores_results(self) -> None:
        """Results are passed through to TimingStats."""
        from slopmop.reporting.timings import _compute_stats

        stats = _compute_stats(
            [1.0, 2.0, 3.0],
            results=["passed", "failed", "passed"],
        )
        assert stats.results == ("passed", "failed", "passed")

    def test_compute_stats_no_results_default_empty(self) -> None:
        """Without results param, results tuple is empty."""
        from slopmop.reporting.timings import _compute_stats

        stats = _compute_stats([1.0, 2.0])
        assert stats.results == ()


class TestSaveTimingsWithResults:
    """Tests for save_timings with result history persistence."""

    def test_save_and_load_results(self, tmp_path: Path) -> None:
        """Results are saved and loaded round-trip."""
        save_timings(
            str(tmp_path),
            {"check:a": 1.0},
            results={"check:a": "passed"},
        )
        save_timings(
            str(tmp_path),
            {"check:a": 2.0},
            results={"check:a": "failed"},
        )

        stats = load_timings(str(tmp_path))
        assert stats["check:a"].results == ("passed", "failed")

    def test_save_results_fifo_cap(self, tmp_path: Path) -> None:
        """Results are capped at MAX_SAMPLES along with durations."""
        for i in range(MAX_SAMPLES + 5):
            status = "passed" if i % 2 == 0 else "failed"
            save_timings(
                str(tmp_path),
                {"check:a": float(i)},
                results={"check:a": status},
            )

        stats = load_timings(str(tmp_path))
        assert len(stats["check:a"].results) == MAX_SAMPLES

    def test_save_without_results_backward_compat(self, tmp_path: Path) -> None:
        """Saving without results still works (backward compat)."""
        save_timings(str(tmp_path), {"check:a": 1.0})

        stats = load_timings(str(tmp_path))
        assert stats["check:a"].results == ()
        assert stats["check:a"].median == 1.0


class TestSparklineOverrideLatest:
    """``override_latest`` forces the rightmost sparkline bar to a specific color."""

    def _make_stats(self) -> TimingStats:
        return TimingStats(
            median=1.0,
            q1=0.9,
            q3=1.1,
            iqr=0.2,
            historical_max=1.1,
            sample_count=3,
            samples=(1.0, 1.1, 0.9),
            results=(),
        )

    def test_override_latest_colors_rightmost_bar(self) -> None:
        """With no stored results, override_latest still produces colored output."""
        from slopmop.reporting.timings import _RESULT_STATUS_COLORS

        stats = self._make_stats()
        spark = stats.sparkline(
            max_width=3, colors_enabled=True, override_latest="failed"
        )
        fail_color = _RESULT_STATUS_COLORS["failed"]
        assert fail_color in spark

    def test_override_latest_passed_color(self) -> None:
        from slopmop.reporting.timings import _RESULT_STATUS_COLORS

        stats = self._make_stats()
        spark = stats.sparkline(
            max_width=3, colors_enabled=True, override_latest="passed"
        )
        pass_color = _RESULT_STATUS_COLORS["passed"]
        assert pass_color in spark

    def test_override_latest_unknown_status_does_not_crash(self) -> None:
        """Unknown override_latest status produces a string without raising."""
        stats = self._make_stats()
        spark = stats.sparkline(
            max_width=3,
            colors_enabled=True,
            override_latest="totally_unknown_status",
        )
        assert isinstance(spark, str)

    def test_override_latest_ignored_when_fewer_than_two_samples(self) -> None:
        """With fewer than 2 samples, sparkline returns empty string."""
        stats = TimingStats(
            median=1.0,
            q1=0.9,
            q3=1.1,
            iqr=0.2,
            historical_max=1.1,
            sample_count=1,
            samples=(1.0,),
        )
        result = stats.sparkline(
            max_width=3, colors_enabled=True, override_latest="passed"
        )
        assert result == ""
