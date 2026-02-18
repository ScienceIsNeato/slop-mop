"""Tests for timing persistence module."""

import json
import time
from pathlib import Path

from slopmop.reporting.timings import (
    EMA_WEIGHT,
    MAX_AGE_DAYS,
    MAX_ENTRIES,
    TIMINGS_DIR,
    TIMINGS_FILE,
    _prune_timings,
    clear_timings,
    load_timings,
    save_timings,
)


class TestLoadTimings:
    """Tests for load_timings."""

    def test_no_file_returns_empty(self, tmp_path: Path) -> None:
        """Test returns empty dict when no timings file exists."""
        result = load_timings(str(tmp_path))
        assert result == {}

    def test_loads_valid_timings(self, tmp_path: Path) -> None:
        """Test loads timing data from valid file."""
        timings_dir = tmp_path / TIMINGS_DIR
        timings_dir.mkdir()
        timings_file = timings_dir / TIMINGS_FILE
        timings_file.write_text(
            json.dumps(
                {
                    "overconfidence:py-tests": {"avg": 3.5, "count": 5},
                    "python:lint": {"avg": 0.8, "count": 3},
                }
            )
        )

        result = load_timings(str(tmp_path))

        assert result == {"overconfidence:py-tests": 3.5, "python:lint": 0.8}

    def test_handles_corrupt_json(self, tmp_path: Path) -> None:
        """Test handles corrupt JSON gracefully."""
        timings_dir = tmp_path / TIMINGS_DIR
        timings_dir.mkdir()
        (timings_dir / TIMINGS_FILE).write_text("not json{{{")

        result = load_timings(str(tmp_path))
        assert result == {}

    def test_handles_invalid_structure(self, tmp_path: Path) -> None:
        """Test handles unexpected data structure."""
        timings_dir = tmp_path / TIMINGS_DIR
        timings_dir.mkdir()
        (timings_dir / TIMINGS_FILE).write_text(
            json.dumps({"check": "not_a_dict", "good": {"avg": 1.0, "count": 1}})
        )

        result = load_timings(str(tmp_path))
        assert result == {"good": 1.0}


class TestSaveTimings:
    """Tests for save_timings."""

    def test_saves_new_timings(self, tmp_path: Path) -> None:
        """Test saves timings to new file."""
        save_timings(
            str(tmp_path), {"overconfidence:py-tests": 2.5, "python:lint": 0.6}
        )

        path = tmp_path / TIMINGS_DIR / TIMINGS_FILE
        assert path.exists()

        data = json.loads(path.read_text())
        assert data["overconfidence:py-tests"]["avg"] == 2.5
        assert data["overconfidence:py-tests"]["count"] == 1
        assert data["python:lint"]["avg"] == 0.6

    def test_merges_with_existing_ema(self, tmp_path: Path) -> None:
        """Test merges new data with existing using EMA."""
        # Save initial data
        save_timings(str(tmp_path), {"overconfidence:py-tests": 10.0})

        # Save another run — EMA should blend
        save_timings(str(tmp_path), {"overconfidence:py-tests": 5.0})

        path = tmp_path / TIMINGS_DIR / TIMINGS_FILE
        data = json.loads(path.read_text())

        # EMA: 0.3 * 5.0 + 0.7 * 10.0 = 1.5 + 7.0 = 8.5
        expected = EMA_WEIGHT * 5.0 + (1 - EMA_WEIGHT) * 10.0
        assert abs(data["overconfidence:py-tests"]["avg"] - expected) < 0.01
        assert data["overconfidence:py-tests"]["count"] == 2

    def test_creates_directory(self, tmp_path: Path) -> None:
        """Test creates .slopmop directory if needed."""
        save_timings(str(tmp_path), {"check:a": 1.0})

        assert (tmp_path / TIMINGS_DIR).is_dir()

    def test_preserves_existing_checks(self, tmp_path: Path) -> None:
        """Test doesn't clobber timings for checks not in current run."""
        save_timings(str(tmp_path), {"check:a": 1.0})
        save_timings(str(tmp_path), {"check:b": 2.0})

        path = tmp_path / TIMINGS_DIR / TIMINGS_FILE
        data = json.loads(path.read_text())

        assert "check:a" in data
        assert "check:b" in data

    def test_rounds_to_three_decimals(self, tmp_path: Path) -> None:
        """Test durations are rounded to 3 decimal places."""
        save_timings(str(tmp_path), {"check:a": 1.23456789})

        path = tmp_path / TIMINGS_DIR / TIMINGS_FILE
        data = json.loads(path.read_text())

        assert data["check:a"]["avg"] == 1.235


class TestClearTimings:
    """Tests for clear_timings."""

    def test_clears_existing_timings(self, tmp_path: Path) -> None:
        """Test clears timings file when it exists."""
        save_timings(str(tmp_path), {"check:a": 1.0})
        path = tmp_path / TIMINGS_DIR / TIMINGS_FILE
        assert path.exists()

        result = clear_timings(str(tmp_path))

        assert result is True
        assert not path.exists()

    def test_returns_false_when_no_history(self, tmp_path: Path) -> None:
        """Test returns False when no timings file exists."""
        result = clear_timings(str(tmp_path))
        assert result is False

    def test_load_returns_empty_after_clear(self, tmp_path: Path) -> None:
        """Test load_timings returns empty dict after clearing."""
        save_timings(str(tmp_path), {"check:a": 5.0, "check:b": 3.0})
        clear_timings(str(tmp_path))

        result = load_timings(str(tmp_path))
        assert result == {}


class TestPruneTimings:
    """Tests for timing data pruning."""

    def test_removes_old_entries(self) -> None:
        """Test entries older than MAX_AGE_DAYS are removed."""
        now = time.time()
        old_timestamp = now - (MAX_AGE_DAYS + 1) * 86400  # 1 day past cutoff

        raw = {
            "old_check": {"avg": 1.0, "count": 1, "last_updated": old_timestamp},
            "new_check": {"avg": 2.0, "count": 1, "last_updated": now},
        }

        result = _prune_timings(raw)

        assert "old_check" not in result
        assert "new_check" in result

    def test_keeps_recent_entries(self) -> None:
        """Test entries within MAX_AGE_DAYS are kept."""
        now = time.time()
        recent_timestamp = now - (MAX_AGE_DAYS - 1) * 86400  # 1 day before cutoff

        raw = {
            "recent_check": {"avg": 1.0, "count": 1, "last_updated": recent_timestamp}
        }

        result = _prune_timings(raw)

        assert "recent_check" in result

    def test_pruning_by_max_entries(self) -> None:
        """Test oldest entries removed when exceeding MAX_ENTRIES."""
        now = time.time()
        raw = {}

        # Create more entries than MAX_ENTRIES
        for i in range(MAX_ENTRIES + 10):
            raw[f"check_{i}"] = {
                "avg": float(i),
                "count": 1,
                "last_updated": now - i * 60,  # Older = higher i
            }

        result = _prune_timings(raw)

        # Should have exactly MAX_ENTRIES
        assert len(result) == MAX_ENTRIES
        # The newest entries (lowest i) should remain
        assert "check_0" in result
        assert "check_1" in result
        # The oldest entries should be gone
        assert f"check_{MAX_ENTRIES + 9}" not in result

    def test_preserves_legacy_entries_without_timestamp(self) -> None:
        """Test entries without last_updated are kept but vulnerable to pruning."""
        now = time.time()
        raw = {
            "legacy_check": {"avg": 1.0, "count": 5},  # No last_updated
            "new_check": {"avg": 2.0, "count": 1, "last_updated": now},
        }

        result = _prune_timings(raw)

        # Legacy entry should still be present (assigned timestamp just inside cutoff)
        assert "legacy_check" in result
        assert "new_check" in result


class TestSaveTimingsWithPruning:
    """Tests for save_timings pruning behavior."""

    def test_saves_with_last_updated(self, tmp_path: Path) -> None:
        """Test saved entries include last_updated timestamp."""
        save_timings(str(tmp_path), {"check:a": 1.0})

        path = tmp_path / TIMINGS_DIR / TIMINGS_FILE
        data = json.loads(path.read_text())

        assert "last_updated" in data["check:a"]
        # Should be recent (within last minute)
        assert time.time() - data["check:a"]["last_updated"] < 60

    def test_prunes_old_on_save(self, tmp_path: Path) -> None:
        """Test old entries are pruned when saving new data."""
        timings_dir = tmp_path / TIMINGS_DIR
        timings_dir.mkdir()
        timings_file = timings_dir / TIMINGS_FILE

        # Manually create an old entry
        old_timestamp = time.time() - (MAX_AGE_DAYS + 1) * 86400
        timings_file.write_text(
            json.dumps(
                {
                    "old_check": {
                        "avg": 1.0,
                        "count": 5,
                        "last_updated": old_timestamp,
                    },
                }
            )
        )

        # Save new data - should trigger pruning
        save_timings(str(tmp_path), {"new_check": 2.0})

        data = json.loads(timings_file.read_text())
        assert "old_check" not in data
        assert "new_check" in data


class TestLoadTimingsWithAge:
    """Tests for load_timings with age filtering."""

    def test_skips_old_entries_on_load(self, tmp_path: Path) -> None:
        """Test old entries are not returned from load_timings."""
        timings_dir = tmp_path / TIMINGS_DIR
        timings_dir.mkdir()
        timings_file = timings_dir / TIMINGS_FILE

        now = time.time()
        old_timestamp = now - (MAX_AGE_DAYS + 1) * 86400

        timings_file.write_text(
            json.dumps(
                {
                    "old_check": {
                        "avg": 1.0,
                        "count": 5,
                        "last_updated": old_timestamp,
                    },
                    "new_check": {"avg": 2.0, "count": 1, "last_updated": now},
                }
            )
        )

        result = load_timings(str(tmp_path))

        assert "old_check" not in result
        assert "new_check" in result
        assert result["new_check"] == 2.0
