"""Terminal color utilities.

Provides ANSI color codes for status differentiation in the display.
Colors are only applied when the terminal supports them (isatty and no NO_COLOR).
"""

import os
import sys
from enum import Enum
from typing import Optional

from slopmop.core.result import CheckStatus


class Color(Enum):
    """ANSI color codes for terminal output."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"

    # Foreground colors
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"

    # Bright variants
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"


# Map check statuses to colors
STATUS_COLORS = {
    CheckStatus.PASSED: Color.GREEN,
    CheckStatus.FAILED: Color.RED,
    CheckStatus.WARNED: Color.YELLOW,
    CheckStatus.SKIPPED: Color.GRAY,
    CheckStatus.NOT_APPLICABLE: Color.GRAY,
    CheckStatus.ERROR: Color.BRIGHT_RED,
}


def supports_color() -> bool:
    """Check if the terminal supports ANSI colors.

    Returns:
        True if colors should be used, False otherwise.
    """
    # NO_COLOR environment variable disables colors
    if os.environ.get("NO_COLOR"):
        return False

    # Must be a TTY
    if not sys.stdout.isatty():
        return False

    # Check TERM for basic support
    term = os.environ.get("TERM", "")
    if term in ("dumb", "unknown"):
        return False

    return True


def colorize(text: str, color: Color, colors_enabled: Optional[bool] = None) -> str:
    """Apply ANSI color to text if colors are enabled.

    Args:
        text: Text to colorize
        color: Color to apply
        colors_enabled: Override color detection (for testing)

    Returns:
        Colored text if colors enabled, original text otherwise.
    """
    if colors_enabled is None:
        colors_enabled = supports_color()

    if not colors_enabled:
        return text

    return f"{color.value}{text}{Color.RESET.value}"


def status_color(status: CheckStatus, colors_enabled: Optional[bool] = None) -> str:
    """Get the ANSI color prefix for a check status.

    Args:
        status: Check status to colorize
        colors_enabled: Override color detection (for testing)

    Returns:
        ANSI color code prefix if colors enabled, empty string otherwise.
    """
    if colors_enabled is None:
        colors_enabled = supports_color()

    if not colors_enabled:
        return ""

    color = STATUS_COLORS.get(status, Color.WHITE)
    return color.value


def reset_color(colors_enabled: Optional[bool] = None) -> str:
    """Get the ANSI reset code if colors are enabled.

    Args:
        colors_enabled: Override color detection (for testing)

    Returns:
        ANSI reset code if colors enabled, empty string otherwise.
    """
    if colors_enabled is None:
        colors_enabled = supports_color()

    if not colors_enabled:
        return ""

    return Color.RESET.value


def dim(text: str, colors_enabled: Optional[bool] = None) -> str:
    """Apply dim styling to text.

    Used for completed checks to reduce visual emphasis (#2).

    Args:
        text: Text to dim
        colors_enabled: Override color detection (for testing)

    Returns:
        Dimmed text if colors enabled, original text otherwise.
    """
    return colorize(text, Color.DIM, colors_enabled)


def bold(text: str, colors_enabled: Optional[bool] = None) -> str:
    """Apply bold styling to text.

    Used for running checks to increase visual emphasis (#2).

    Args:
        text: Text to make bold
        colors_enabled: Override color detection (for testing)

    Returns:
        Bold text if colors enabled, original text otherwise.
    """
    return colorize(text, Color.BOLD, colors_enabled)


def category_header_color(category: str, colors_enabled: Optional[bool] = None) -> str:
    """Get ANSI color code for a category header.

    Args:
        category: Category key (python, quality, security, etc.)
        colors_enabled: Override color detection (for testing)

    Returns:
        ANSI color code prefix if colors enabled, empty string otherwise.
    """
    if colors_enabled is None:
        colors_enabled = supports_color()

    if not colors_enabled:
        return ""

    # Map categories to colors for visual grouping
    # Keep colors visually distinct — avoid pairing similar hues (e.g., two purples)
    category_colors = {
        "overconfidence": Color.BRIGHT_CYAN,  # bold teal/blue
        "deceptiveness": Color.BRIGHT_MAGENTA,  # bold pink/purple
        "laziness": Color.BRIGHT_YELLOW,  # bold yellow (was MAGENTA — too close to deceptiveness)
        "myopia": Color.BRIGHT_GREEN,  # bold green
        "general": Color.BLUE,
        "pr": Color.CYAN,
    }
    color = category_colors.get(category, Color.WHITE)
    return color.value
