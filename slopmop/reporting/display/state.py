"""Display state types.

Defines the state tracking structures for individual checks
in the dynamic display.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from slopmop.core.result import CheckResult


class DisplayState(Enum):
    """State of a check in the display."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"


@dataclass
class CheckDisplayInfo:
    """Display information for a single check.

    Tracks the visual state and timing data for one check in
    the dynamic display.
    """

    name: str
    state: DisplayState = DisplayState.PENDING
    result: Optional[CheckResult] = None
    start_time: float = 0.0
    duration: float = 0.0
    expected_duration: Optional[float] = None  # From prior runs, None = no data
    completion_order: int = 0  # Order in which check completed (0 = not yet)
