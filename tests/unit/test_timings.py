"""Tests for timing persistence module."""

import json
import math
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
        """Single sample has std_dev of 0."""
        stats = _compute_stats([2.0])
        assert stats.mean == 2.0
        assert stats.std_dev == 0.0
        assert stats.sample_count == 1

    def test_compute_stats_multiple_samples(self) -> None:
        """Mean and population std dev are computed correctly."""
        samples = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        stats = _compute_stats(samples)
        assert stats.mean == 5.0
        assert stats.std_dev == round(math.sqrt(4.0), 3)  # 2.0
        assert stats.sample_count == 8

    def test_compute_stats_rounds_to_3_decimals(self) -> None:
        """Mean and std_dev are rounded to 3 decimal places."""
        stats = _compute_stats([1.11111, 2.22222, 3.33333])
        # Mean = 2.22222, std_dev = ~0.8607
        assert stats.mean == round(sum([1.11111, 2.22222, 3.33333]) / 3, 3)

    def test_sigma_over_below_mean(self) -> None:
        """sigma_over returns 0 when elapsed <= mean."""
        stats = TimingStats(mean=5.0, std_dev=1.0, sample_count=10)
        assert stats.sigma_over(3.0) == 0.0
        assert stats.sigma_over(5.0) == 0.0

    def test_sigma_over_above_mean(self) -> None:
        """sigma_over returns correct number of std devs."""
        stats = TimingStats(mean=5.0, std_dev=1.0, sample_count=10)
        assert stats.sigma_over(6.0) == 1.0
        assert stats.sigma_over(7.5) == 2.5

    def test_sigma_over_tiny_std_dev(self) -> None:
        """sigma_over returns 0 when std_dev is negligible (< 0.01)."""
        stats = TimingStats(mean=1.0, std_dev=0.005, sample_count=10)
        assert stats.sigma_over(1.5) == 0.0


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
                    "overconfidence:py-tests": {
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

        assert "overconfidence:py-tests" in result
        assert "python:lint" in result
        assert result["overconfidence:py-tests"].mean == 3.5
        assert result["overconfidence:py-tests"].sample_count == 2
        assert result["python:lint"].mean == 0.8

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
        # Migrated avg becomes a single sample → mean equals the avg
        assert result["check:legacy"].mean == 2.5
        assert result["check:legacy"].sample_count == 1
        assert result["check:legacy"].std_dev == 0.0

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
            str(tmp_path), {"overconfidence:py-tests": 2.5, "python:lint": 0.6}
        )

        path = tmp_path / TIMINGS_DIR / TIMINGS_FILE
        assert path.exists()

        data = json.loads(path.read_text())
        assert data["overconfidence:py-tests"]["samples"] == [2.5]
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
        assert result["new_check"].mean == 2.0
