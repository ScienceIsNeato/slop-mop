"""Tests for timing persistence module."""

import json
from pathlib import Path

from slopmop.reporting.timings import (
    EMA_WEIGHT,
    TIMINGS_DIR,
    TIMINGS_FILE,
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
                    "python:tests": {"avg": 3.5, "count": 5},
                    "python:lint": {"avg": 0.8, "count": 3},
                }
            )
        )

        result = load_timings(str(tmp_path))

        assert result == {"python:tests": 3.5, "python:lint": 0.8}

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
        save_timings(str(tmp_path), {"python:tests": 2.5, "python:lint": 0.6})

        path = tmp_path / TIMINGS_DIR / TIMINGS_FILE
        assert path.exists()

        data = json.loads(path.read_text())
        assert data["python:tests"]["avg"] == 2.5
        assert data["python:tests"]["count"] == 1
        assert data["python:lint"]["avg"] == 0.6

    def test_merges_with_existing_ema(self, tmp_path: Path) -> None:
        """Test merges new data with existing using EMA."""
        # Save initial data
        save_timings(str(tmp_path), {"python:tests": 10.0})

        # Save another run — EMA should blend
        save_timings(str(tmp_path), {"python:tests": 5.0})

        path = tmp_path / TIMINGS_DIR / TIMINGS_FILE
        data = json.loads(path.read_text())

        # EMA: 0.3 * 5.0 + 0.7 * 10.0 = 1.5 + 7.0 = 8.5
        expected = EMA_WEIGHT * 5.0 + (1 - EMA_WEIGHT) * 10.0
        assert abs(data["python:tests"]["avg"] - expected) < 0.01
        assert data["python:tests"]["count"] == 2

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
