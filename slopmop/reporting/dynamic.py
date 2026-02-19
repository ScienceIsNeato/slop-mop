"""Dynamic terminal display for quality gate execution.

This module re-exports from the display package for backwards compatibility.
The implementation has been split into modular components:
- display/config.py: Display constants
- display/state.py: DisplayState enum and CheckDisplayInfo dataclass
- display/renderer.py: Static formatting utilities
- display/dynamic.py: DynamicDisplay class
"""

# Re-export all public symbols from the display package
from slopmop.reporting.display import (
    CheckDisplayInfo,
    DisplayState,
    DynamicDisplay,
)

__all__ = [
    "CheckDisplayInfo",
    "DisplayState",
    "DynamicDisplay",
]
