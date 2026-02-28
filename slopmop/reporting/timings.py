"""Timing persistence for quality gate execution.

Stores historical check durations so ETAs can be estimated on subsequent runs.
Data is stored per-project in `.slopmop/timings.json`.

Storage format (v2 — sample-based):
  {
    "check_name": {
      "samples": [1.2, 1.1, 1.3, ...],   # last N raw durations (FIFO)
      "last_updated": 1709123456.789
    }
  }

Legacy format (v1 — EMA) is auto-migrated on first save:
  {
    "check_name": {
      "avg": 1.2,
      "count": 5,
      "last_updated": 1709123456.789
    }
  }
"""

import json
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

logger = logging.getLogger(__name__)

# Maximum number of recent samples to keep per check.
# 50 gives stable statistics while adapting to gradual drift
# (e.g., growing test suites).
MAX_SAMPLES = 50

# Maximum number of check entries to store. Oldest entries (by last_updated)
# are pruned when this limit is exceeded.
MAX_ENTRIES = 100

# Maximum age in days before an entry is considered stale and pruned.
# Checks that haven't run in this many days are removed to keep the
# timing file from accumulating obsolete data.
MAX_AGE_DAYS = 30

TIMINGS_DIR = ".slopmop"
TIMINGS_FILE = "timings.json"


# Unicode block characters for sparkline rendering (8 levels).
_SPARK_BLOCKS = "▁▂▃▄▅▆▇█"


@dataclass(frozen=True)
class TimingStats:
    """Statistical summary of historical check timings.

    Computed from the last N raw samples stored on disk.
    Used by the display layer to compute ETA progress bars
    and standard-deviation-based overrun thresholds.
    """

    mean: float  # Average duration in seconds
    std_dev: float  # Population standard deviation
    sample_count: int  # Number of samples behind these stats
    samples: tuple[float, ...] = ()  # Raw durations (chronological, newest last)

    def sigma_over(self, elapsed: float) -> float:
        """How many standard deviations *elapsed* is above the mean.

        Returns 0.0 when elapsed <= mean, or when std_dev is too
        small to be meaningful (< 0.01s — sub-10ms jitter).

        Args:
            elapsed: Observed duration in seconds.

        Returns:
            Number of std deviations above the mean (>= 0.0).
        """
        if elapsed <= self.mean or self.std_dev < 0.01:
            return 0.0
        return (elapsed - self.mean) / self.std_dev

    def sparkline(self, max_width: int = 10) -> str:
        """Render recent samples as a Unicode sparkline.

        Maps each value to one of 8 block characters (▁▂▃▄▅▆▇█)
        scaled between the min and max of the displayed window.
        The newest sample is on the right.

        Args:
            max_width: Maximum number of characters to render.
                       Uses the last *max_width* samples.

        Returns:
            Sparkline string, or empty string if < 2 samples.
        """
        if len(self.samples) < 2:
            return ""
        window = self.samples[-max_width:]
        lo = min(window)
        hi = max(window)
        span = hi - lo
        if span < 0.001:
            # All values are effectively identical — flat line
            return _SPARK_BLOCKS[3] * len(window)
        return "".join(_SPARK_BLOCKS[min(int((v - lo) / span * 7), 7)] for v in window)

    def format_delta(self, elapsed: float) -> str:
        """Format delta from mean as '+/-Xs (+/-X%)'.

        Args:
            elapsed: Observed duration in seconds.

        Returns:
            Delta string like '+0.3s (+15%)' or '-0.2s (-10%)'.
            Empty string if mean is 0.
        """
        if self.mean < 0.001:
            return ""
        delta = elapsed - self.mean
        pct = (delta / self.mean) * 100
        sign = "+" if delta >= 0 else ""

        # Format the delta value compactly
        if abs(delta) < 0.05:
            delta_str = f"{sign}{delta:.2f}s"
        elif abs(delta) < 10:
            delta_str = f"{sign}{delta:.1f}s"
        else:
            delta_str = f"{sign}{delta:.0f}s"

        return f"{delta_str} ({sign}{pct:.0f}%)"


def _timings_path(project_root: str) -> Path:
    """Get the path to the timings file for a project."""
    return Path(project_root) / TIMINGS_DIR / TIMINGS_FILE


def _compute_stats(samples: List[float]) -> TimingStats:
    """Compute mean and population std dev from a list of durations.

    Args:
        samples: List of duration values (must not be empty).

    Returns:
        TimingStats with mean, std_dev, and sample_count.
    """
    n = len(samples)
    mean = sum(samples) / n
    variance = sum((s - mean) ** 2 for s in samples) / n
    return TimingStats(
        mean=round(mean, 3),
        std_dev=round(math.sqrt(variance), 3),
        sample_count=n,
        samples=tuple(round(s, 3) for s in samples),
    )


def _is_v1_entry(entry: Dict[str, Any]) -> bool:
    """Return True if *entry* uses the legacy EMA format (v1)."""
    return "avg" in entry and "samples" not in entry


def _migrate_v1_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a v1 (EMA) entry to v2 (sample-based).

    Since we only have the average, we seed the sample list with a
    single value — the EMA avg.  Statistics will broaden naturally
    as real samples accumulate.

    Args:
        entry: Legacy entry dict with "avg", "count", "last_updated".

    Returns:
        New entry dict with "samples" and "last_updated".
    """
    avg = float(entry.get("avg", 0))
    return {
        "samples": [round(avg, 3)],
        "last_updated": entry.get("last_updated", 0),
    }


def load_timings(project_root: str) -> Dict[str, TimingStats]:
    """Load historical check timings from disk.

    Auto-migrates legacy v1 (EMA) entries on read.  Entries older than
    MAX_AGE_DAYS are silently skipped (pruned on next save).

    Args:
        project_root: Project root directory

    Returns:
        Dict mapping check name to TimingStats.
        Empty dict if no history exists.
    """
    path = _timings_path(project_root)
    if not path.exists():
        return {}

    try:
        data: Dict[str, Any] = json.loads(path.read_text())
        result: Dict[str, TimingStats] = {}
        cutoff = time.time() - (MAX_AGE_DAYS * 86400)

        for name, entry in data.items():
            if not isinstance(entry, dict):
                continue

            checked: Dict[str, Any] = cast(Dict[str, Any], entry)

            # Auto-migrate v1 → v2 in memory (disk updated on next save)
            if _is_v1_entry(checked):
                checked = _migrate_v1_entry(checked)

            raw_samples: object = checked.get("samples")
            if not isinstance(raw_samples, list) or not raw_samples:
                continue

            last_updated: float = float(checked.get("last_updated", 0))
            if 0 < last_updated < cutoff:
                continue

            typed_samples: List[float] = [
                float(cast(float, s)) for s in cast(List[object], raw_samples)
            ]
            result[name] = _compute_stats(typed_samples)
        return result
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        logger.debug(f"Could not load timings from {path}: {exc}")
        return {}


def load_timing_averages(project_root: str) -> Dict[str, float]:
    """Load historical check timings as simple averages.

    Convenience wrapper used by the executor's time-budget feature,
    which only needs a single float per check.

    Args:
        project_root: Project root directory

    Returns:
        Dict mapping check name to mean duration in seconds.
        Empty dict if no history exists.
    """
    stats = load_timings(project_root)
    return {name: ts.mean for name, ts in stats.items()}


def _prune_timings(raw: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Prune stale and excess entries from timing data.

    Removes:
    - Entries older than MAX_AGE_DAYS
    - Oldest entries beyond MAX_ENTRIES limit

    Args:
        raw: Raw timing data dict

    Returns:
        Pruned timing data dict
    """
    now = time.time()
    cutoff = now - (MAX_AGE_DAYS * 86400)

    # First pass: remove entries older than MAX_AGE_DAYS
    # Also build list of (name, last_updated) for sorting
    entries: List[Tuple[str, float]] = []
    for name, entry in list(raw.items()):
        if not isinstance(entry, dict):
            del raw[name]
            continue

        # Auto-migrate v1 → v2 on disk
        if _is_v1_entry(entry):
            raw[name] = entry = _migrate_v1_entry(entry)

        last_updated = entry.get("last_updated", 0)
        # If no last_updated field, keep it (legacy data) but assign old timestamp
        if last_updated == 0:
            last_updated = cutoff + 1  # Just inside cutoff, will be pruned eventually
        if last_updated < cutoff:
            del raw[name]
        else:
            entries.append((name, last_updated))

    # Second pass: if still over MAX_ENTRIES, remove oldest
    if len(entries) > MAX_ENTRIES:
        # Sort by last_updated (oldest first)
        entries.sort(key=lambda x: x[1])
        # Remove oldest entries to get down to MAX_ENTRIES
        to_remove = len(entries) - MAX_ENTRIES
        for name, _ in entries[:to_remove]:
            del raw[name]

    return raw


def save_timings(
    project_root: str,
    durations: Dict[str, float],
    existing: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    """Save check timings to disk, appending to sample history.

    Each new duration is appended to the check's sample list (FIFO,
    capped at MAX_SAMPLES).  Legacy v1 entries are auto-migrated.
    Entries older than MAX_AGE_DAYS or beyond MAX_ENTRIES are pruned.

    Args:
        project_root: Project root directory
        durations: Dict mapping check name to duration from this run
        existing: Pre-loaded raw timings data (if None, loads from disk)
    """
    path = _timings_path(project_root)
    now = time.time()

    # Load existing raw data
    raw: Dict[str, Dict[str, Any]] = {}
    if existing is not None:
        raw = existing
    elif path.exists():
        try:
            raw = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            raw = {}

    # Merge new durations — append to sample list
    for name, duration in durations.items():
        rounded = round(duration, 3)

        if name in raw and isinstance(raw[name], dict):
            entry = raw[name]

            # Auto-migrate v1 → v2
            if _is_v1_entry(entry):
                entry = _migrate_v1_entry(entry)

            samples: List[float] = entry.get("samples", [])
            if not isinstance(samples, list):
                samples = []
            samples.append(rounded)

            # FIFO cap — keep only the most recent MAX_SAMPLES
            if len(samples) > MAX_SAMPLES:
                samples = samples[-MAX_SAMPLES:]

            raw[name] = {
                "samples": samples,
                "last_updated": now,
            }
        else:
            raw[name] = {
                "samples": [rounded],
                "last_updated": now,
            }

    # Prune old/excess entries
    raw = _prune_timings(raw)

    # Write atomically-ish
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n")
    except OSError as exc:
        logger.debug(f"Could not save timings to {path}: {exc}")


def clear_timings(project_root: str) -> bool:
    """Delete all stored timing history for a project.

    Args:
        project_root: Project root directory

    Returns:
        True if timings were cleared, False if no history existed.
    """
    path = _timings_path(project_root)
    if path.exists():
        try:
            path.unlink()
            logger.debug(f"Cleared timing history at {path}")
            return True
        except OSError as exc:
            logger.debug(f"Could not clear timings at {path}: {exc}")
            return False
    return False
