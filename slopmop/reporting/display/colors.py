"""Terminal color utilities.

Provides ANSI color codes for status differentiation in the display.
Colors are only applied when the terminal supports them (isatty and no NO_COLOR).

Color tiers:
  Tier 1 (16-color ANSI): Always available. Used as fallback everywhere.
  Tier 2 (true-color 24-bit): Available when COLORTERM=truecolor|24bit. Used for
    category headers via ansi_rgb(), which falls back to Tier 1 automatically.
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


def supports_truecolor() -> bool:
    """Check if the terminal supports 24-bit true color.

    Reads the de-facto standard COLORTERM env var set by terminals like iTerm2,
    kitty, Alacritty, Windows Terminal, GNOME Terminal 3.36+, etc.

    Returns:
        True if 24-bit RGB escape codes are safe to emit, False otherwise.
        Always returns False when supports_color() is False.
    """
    if not supports_color():
        return False
    return os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")


def ansi_rgb(hex_color: str, fallback: "Color") -> str:
    """Return an ANSI escape sequence for the given hex color.

    Emits a 24-bit true-color sequence when the terminal supports it;
    falls back to the provided named Color value on lesser terminals.

    Args:
        hex_color: CSS-style hex string, e.g. "#6366F1" or "6366F1".
        fallback: Color enum value to use when true-color is unavailable.

    Returns:
        ANSI escape code string (no trailing reset).
    """
    if supports_truecolor():
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"\033[38;2;{r};{g};{b}m"
    return fallback.value


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

    Emits 24-bit true-color sequences on terminals that support them
    (COLORTERM=truecolor|24bit), with automatic fallback to 16-color ANSI
    on everything else.  This is the single source of truth for the brand
    palette — the progress bar inherits this via dynamic.py.

    Palette (A1 – Vivid):
      overconfidence  #6366F1  indigo    / fallback BRIGHT_BLUE
      deceptiveness   #913364  raspberry / fallback BRIGHT_MAGENTA
      laziness        #22D3EE  sky-cyan  / fallback BRIGHT_CYAN
      myopia          #10B981  emerald   / fallback BRIGHT_GREEN
      pr              #22D3EE  sky-cyan  / fallback CYAN
      general         (legacy) BLUE

    Args:
        category: Category key (overconfidence, deceptiveness, laziness, …)
        colors_enabled: Override color detection (for testing)

    Returns:
        ANSI color code prefix if colors enabled, empty string otherwise.
    """
    if colors_enabled is None:
        colors_enabled = supports_color()

    if not colors_enabled:
        return ""

    # True-color hex + 16-color ANSI fallback pairs
    category_palette: dict[str, tuple[str, Color]] = {
        "overconfidence": ("#6366F1", Color.BRIGHT_BLUE),
        "deceptiveness": ("#913364", Color.BRIGHT_MAGENTA),
        "laziness": ("#22D3EE", Color.BRIGHT_CYAN),
        "myopia": ("#10B981", Color.BRIGHT_GREEN),
        "pr": ("#22D3EE", Color.CYAN),
        "general": ("#6366F1", Color.BLUE),  # legacy
    }

    if category in category_palette:
        hex_val, fallback = category_palette[category]
        return ansi_rgb(hex_val, fallback)

    return Color.WHITE.value
