"""Display package for dynamic terminal output.

This package provides brew-style live updating display with spinners
for running checks and real-time progress updates.
"""

from slopmop.reporting.display.dynamic import DynamicDisplay
from slopmop.reporting.display.state import CheckDisplayInfo, DisplayState

__all__ = ["DynamicDisplay", "DisplayState", "CheckDisplayInfo"]
