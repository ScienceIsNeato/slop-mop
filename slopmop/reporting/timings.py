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
import statistics
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

# Cached or otherwise short-circuited runs should not be recorded as timing
# samples, but older versions or interrupted runs may have already polluted
# timing history. If a new real run is dramatically slower than every stored
# sample, the old history is more harmful than helpful for ETA/budgeting.
#
# Detection uses a single dimensionless ratio — no absolute-second thresholds.
# A new duration that is at least _CACHE_POISON_RATIO times the historical
# maximum implies the two populations differ by at least one order of magnitude,
# which under a log-normal timing model is a statistically sound criterion for
# concluding they were drawn from fundamentally different processes.
_CACHE_POISON_RATIO = 10.0  # new_duration / max(history) must meet this threshold

TIMINGS_DIR = ".slopmop"
TIMINGS_FILE = "timings.json"


# Unicode block characters for sparkline rendering (8 levels).
_SPARK_BLOCKS = "▁▂▃▄▅▆▇█"

# Placeholder character for empty sparkline slots (missing data points).
_SPARK_PLACEHOLDER = "⸱"

# Dot character for result trendline.
_RESULT_DOT = "●"

# Map check-status values to ANSI color codes for result dots.
# Uses the same palette as STATUS_COLORS in colors.py but avoids
# importing the display layer (timings is lower-level).
_RESULT_STATUS_COLORS: Dict[str, str] = {
    "passed": "\033[32m",  # green
    "failed": "\033[31m",  # red
    "warned": "\033[33m",  # yellow
    "error": "\033[91m",  # bright red
    "skipped": "\033[90m",  # gray
    "not_applicable": "\033[90m",  # gray
}


@dataclass(frozen=True)
class TimingStats:
    """Statistical summary of historical check timings.

    Computed from the last N raw samples stored on disk.
    Uses median and IQR (interquartile range) for robust anomaly
    detection that is insensitive to outliers and skewed tails.
    """

    median: float  # Median duration in seconds
    q1: float  # First quartile (25th percentile)
    q3: float  # Third quartile (75th percentile)
    iqr: float  # Interquartile range (q3 - q1)
    historical_max: float  # Maximum observed duration across all samples
    sample_count: int  # Number of samples behind these stats
    samples: tuple[float, ...] = ()  # Raw durations (chronological, newest last)
    results: tuple[str, ...] = ()  # Check outcomes ("passed", "failed", etc.)

    def iqr_over(self, elapsed: float) -> float:
        """How far *elapsed* exceeds the upper Tukey fence, in IQR units.

        The upper fence is Q3 + 1.5 × IQR — the textbook threshold for
        statistical outliers.  Returns 0.0 when elapsed is within the
        fence, or when IQR is too small to be meaningful (< 0.01s).

        A return value of 1.0 means elapsed is at Q3 + 2.5 × IQR;
        2.5 means Q3 + 4.0 × IQR (extreme outlier).

        Args:
            elapsed: Observed duration in seconds.

        Returns:
            IQR units above the Tukey fence (>= 0.0).
        """
        fence = self.q3 + 1.5 * self.iqr
        if elapsed <= fence or self.iqr < 0.01:
            return 0.0
        return (elapsed - fence) / self.iqr

    def sparkline(
        self,
        max_width: int = 10,
        colors_enabled: bool = False,
        override_latest: Optional[str] = None,
    ) -> str:
        """Render recent samples as a constant-width Unicode sparkline.

        Always produces exactly *max_width* visible characters.  Actual
        data points are rendered as block characters (▁▂▃▄▅▆▇█) scaled
        absolutely from 0 to historical_max, and any remaining slots
        are filled with a dim placeholder (⸱) so the column never shifts.

        When *colors_enabled* is True and ``self.results`` is populated,
        each bar is colored by the corresponding result status (green for
        passed, red for failed, etc.), merging timing + outcome into one
        visual.

        *override_latest* lets the caller supply the most recent result
        when it may not yet be recorded in ``self.results`` (e.g. the
        last run was stored in ``last_swab.json`` but timing history
        hasn't been flushed yet).  When set, the rightmost bar is
        re-colored to match *override_latest* regardless of what
        ``self.results[-1]`` says.

        Args:
            max_width: Exact number of visible characters to produce.
                       Uses the last *max_width* samples; pads with
                       placeholders if fewer samples exist.
            colors_enabled: Whether to color bars by result status.
            override_latest: Optional result string ("passed", "failed",
                             etc.) to force onto the rightmost bar.

        Returns:
            Sparkline string of exactly *max_width* display characters,
            or empty string if < 2 samples.
        """
        if len(self.samples) < 2:
            return ""
        window = self.samples[-max_width:]
        # Absolute scaling: 0 → historical_max (floor 0.1s to avoid
        # division-by-zero on sub-100ms checks).
        lo = 0.0
        hi = max(self.historical_max, 0.1)
        span = hi - lo
        if span < 0.001:
            bar = _SPARK_BLOCKS[3]
            bars = [bar] * len(window)
        else:
            bars = [_SPARK_BLOCKS[min(int((v - lo) / span * 7), 7)] for v in window]

        # Pad with placeholders so output is always max_width chars
        pad_count = max_width - len(bars)

        # Apply per-bar result coloring when available
        if colors_enabled and (self.results or override_latest):
            result_window = self.results[-max_width:]
            # Align: results may be shorter than samples (legacy data)
            offset = len(bars) - len(result_window)
            reset = "\033[0m"
            dim = "\033[90m"  # dim gray for placeholders
            colored: list[str] = []
            # Leading placeholders (dim)
            for _ in range(pad_count):
                colored.append(f"{dim}{_SPARK_PLACEHOLDER}{reset}")
            for i, bar in enumerate(bars):
                ri = i - offset
                if ri >= 0 and ri < len(result_window):
                    color = _RESULT_STATUS_COLORS.get(result_window[ri], "")
                    if color:
                        colored.append(f"{color}{bar}{reset}")
                    else:
                        colored.append(bar)
                else:
                    colored.append(bar)
            # If the caller knows the true latest result (e.g. from
            # last_swab.json, which may be newer than timing history),
            # override the rightmost bar so it always matches the
            # displayed "last: <result>" text.
            if override_latest and bars:
                override_color = _RESULT_STATUS_COLORS.get(override_latest, "")
                if override_color:
                    colored[-1] = f"{override_color}{bars[-1]}{reset}"
            return "".join(colored)

        # No coloring — plain text with placeholders
        padding = _SPARK_PLACEHOLDER * pad_count
        return padding + "".join(bars)

    def format_delta(self, elapsed: float) -> str:
        """Format delta from median as '+/-Xs (+/-X%)'.

        Args:
            elapsed: Observed duration in seconds.

        Returns:
            Delta string like '+0.3s (+15%)' or '-0.2s (-10%)'.
            Empty string if median is ~0.
        """
        if self.median < 0.001:
            return ""
        delta = elapsed - self.median
        pct = (delta / self.median) * 100
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


def _compute_stats(
    samples: List[float],
    results: Optional[List[str]] = None,
) -> TimingStats:
    """Compute median, quartiles, and IQR from a list of durations.

    Uses the lower/upper-half median-split method for quartiles,
    which works well for small sample sizes (N ≤ 50).  This avoids
    numpy dependencies and interpolation quirks in statistics.quantiles().

    Args:
        samples: List of duration values (must not be empty).
        results: Optional parallel list of status strings.

    Returns:
        TimingStats with median, q1, q3, iqr, historical_max, etc.
    """
    n = len(samples)
    sorted_s = sorted(samples)
    med = statistics.median(sorted_s)

    if n < 2:
        q1_val = med
        q3_val = med
    else:
        mid = n // 2
        lower = sorted_s[:mid]
        upper = sorted_s[mid:] if n % 2 == 0 else sorted_s[mid + 1 :]
        q1_val = statistics.median(lower) if lower else med
        q3_val = statistics.median(upper) if upper else med

    iqr_val = q3_val - q1_val
    hist_max = max(samples)

    return TimingStats(
        median=round(med, 3),
        q1=round(q1_val, 3),
        q3=round(q3_val, 3),
        iqr=round(iqr_val, 3),
        historical_max=round(hist_max, 3),
        sample_count=n,
        samples=tuple(round(s, 3) for s in samples),
        results=tuple(results) if results else (),
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


def _should_reset_implausibly_fast_history(
    samples: List[float],
    new_duration: float,
) -> bool:
    """Return True when existing samples appear to be cached/short-circuit timings.

    Uses a single scale-invariant criterion: ``new_duration / max(samples)``
    must reach *_CACHE_POISON_RATIO* (default 10×).  No absolute-second
    thresholds are used, so the check is equally effective for sub-second
    checks and multi-minute checks.

    Rationale: timing samples from real runs and from cache-hit short-circuits
    follow different log-normal distributions.  Requiring the new sample to
    exceed the empirical upper bound of the stored history by a full order of
    magnitude makes it statistically implausible that both populations share
    the same underlying process — the stored history is almost certainly
    from the faster (cached) distribution and should be discarded.

    At least two existing samples are required so a single noisy data point
    cannot trigger a spurious reset.
    """
    if len(samples) < 2:
        return False

    historical_max = max(samples)
    if historical_max <= 0:
        return False

    return new_duration / historical_max >= _CACHE_POISON_RATIO


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

            # Load result history (parallel to samples, may be absent)
            raw_results: object = checked.get("results")
            typed_results: Optional[List[str]] = None
            if isinstance(raw_results, list):
                typed_results = [str(r) for r in cast(List[object], raw_results)]

            result[name] = _compute_stats(typed_samples, typed_results)
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
    return {name: ts.median for name, ts in stats.items()}


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
    results: Optional[Dict[str, str]] = None,
) -> None:
    """Save check timings to disk, appending to sample history.

    Each new duration is appended to the check's sample list (FIFO,
    capped at MAX_SAMPLES).  Legacy v1 entries are auto-migrated.
    Entries older than MAX_AGE_DAYS or beyond MAX_ENTRIES are pruned.

    Args:
        project_root: Project root directory
        durations: Dict mapping check name to duration from this run
        existing: Pre-loaded raw timings data (if None, loads from disk)
        results: Dict mapping check name to status string from this run
                 (e.g. "passed", "failed"). Stored alongside durations
                 to support result-history trendlines.
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
        result_status = results.get(name) if results else None

        if name in raw and isinstance(raw[name], dict):
            entry = raw[name]

            # Auto-migrate v1 → v2
            if _is_v1_entry(entry):
                entry = _migrate_v1_entry(entry)

            samples: List[float] = entry.get("samples", [])
            if not isinstance(samples, list):
                samples = []
            samples = [float(sample) for sample in samples]

            # If old history is clearly made of cached/short-circuit timings,
            # restart from the real sample instead of letting bad medians linger.
            # Applied at most once per entry — marked so it never fires again.
            cache_poison_reset_applied = bool(entry.get("cache_poison_reset_applied"))
            if (
                not cache_poison_reset_applied
                and _should_reset_implausibly_fast_history(samples, rounded)
            ):
                logger.debug(
                    "Resetting implausibly fast timing history for %s: "
                    "max=%s new=%s",
                    name,
                    max(samples),
                    rounded,
                )
                cache_poison_reset_applied = True
                samples = []
                entry["results"] = []
            samples.append(rounded)

            # Result history — kept in sync with samples
            result_list: List[str] = entry.get("results", [])
            if not isinstance(result_list, list):
                result_list = []
            if result_status:
                result_list.append(result_status)

            # FIFO cap — keep only the most recent MAX_SAMPLES
            if len(samples) > MAX_SAMPLES:
                samples = samples[-MAX_SAMPLES:]
            if len(result_list) > MAX_SAMPLES:
                result_list = result_list[-MAX_SAMPLES:]

            entry_data: Dict[str, Any] = {
                "samples": samples,
                "last_updated": now,
            }
            if result_list:
                entry_data["results"] = result_list
            if cache_poison_reset_applied:
                entry_data["cache_poison_reset_applied"] = True
            raw[name] = entry_data
        else:
            entry_data = {
                "samples": [rounded],
                "last_updated": now,
            }
            if result_status:
                entry_data["results"] = [result_status]
            raw[name] = entry_data

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
