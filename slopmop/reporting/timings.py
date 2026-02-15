"""Timing persistence for quality gate execution.

Stores historical check durations so ETAs can be estimated on subsequent runs.
Data is stored per-project in `.slopmop/timings.json`.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, cast

logger = logging.getLogger(__name__)

# Exponential moving average weight for new observations.
# 0.3 = 30% new value, 70% historical — smooths out outliers while
# still adapting to real changes (e.g., growing test suites).
EMA_WEIGHT = 0.3

TIMINGS_DIR = ".slopmop"
TIMINGS_FILE = "timings.json"


def _timings_path(project_root: str) -> Path:
    """Get the path to the timings file for a project."""
    return Path(project_root) / TIMINGS_DIR / TIMINGS_FILE


def load_timings(project_root: str) -> Dict[str, float]:
    """Load historical check timings from disk.

    Args:
        project_root: Project root directory

    Returns:
        Dict mapping check name to expected duration in seconds.
        Empty dict if no history exists.
    """
    path = _timings_path(project_root)
    if not path.exists():
        return {}

    try:
        data: Dict[str, Any] = json.loads(path.read_text())
        # Validate structure: {"check_name": {"avg": float, "count": int}}
        result: Dict[str, float] = {}
        for name, entry in data.items():
            if isinstance(entry, dict) and "avg" in entry:
                result[name] = float(cast(Dict[str, Any], entry)["avg"])
        return result
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        logger.debug(f"Could not load timings from {path}: {exc}")
        return {}


def save_timings(
    project_root: str,
    durations: Dict[str, float],
    existing: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    """Save check timings to disk, merging with historical data.

    Uses exponential moving average so estimates converge over runs
    without being thrown off by one-time spikes.

    Args:
        project_root: Project root directory
        durations: Dict mapping check name to duration from this run
        existing: Pre-loaded raw timings data (if None, loads from disk)
    """
    path = _timings_path(project_root)

    # Load existing raw data
    raw: Dict[str, Dict[str, Any]] = {}
    if existing is not None:
        raw = existing
    elif path.exists():
        try:
            raw = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            raw = {}

    # Merge new durations with EMA
    for name, duration in durations.items():
        if name in raw and isinstance(raw[name], dict):
            old_avg: float = float(raw[name].get("avg", duration))
            old_count: int = int(raw[name].get("count", 0))
            new_avg: float = (EMA_WEIGHT * duration) + ((1 - EMA_WEIGHT) * old_avg)
            raw[name] = {"avg": round(new_avg, 3), "count": old_count + 1}
        else:
            raw[name] = {"avg": round(duration, 3), "count": 1}

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
