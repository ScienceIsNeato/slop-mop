"""Display rendering utilities.

Static helper functions for formatting and measuring terminal output.
"""

import re
import shutil
import unicodedata
from typing import List, Optional

from slopmop.reporting.display import config

# Regex to match ANSI escape sequences (colors, cursor movement, etc.)
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def get_terminal_width() -> int:
    """Get current terminal width, with fallback.

    Returns:
        Terminal width in columns.
    """
    try:
        return shutil.get_terminal_size().columns
    except (ValueError, OSError):
        return config.DEFAULT_TERMINAL_WIDTH


def display_width(text: str) -> int:
    """Calculate terminal display width of a string.

    Wide characters (emoji, CJK) take 2 columns.  ANSI escape sequences
    are stripped before measuring so they don't inflate the count.

    Args:
        text: String to measure

    Returns:
        Number of terminal columns the text occupies
    """
    stripped = _ANSI_RE.sub("", text)
    width = 0
    for ch in stripped:
        cat = unicodedata.east_asian_width(ch)
        if cat in ("W", "F"):
            width += 2
        else:
            width += 1
    return width


def strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences from text.

    Args:
        text: Text possibly containing ANSI codes

    Returns:
        Clean text with no ANSI sequences.
    """
    return _ANSI_RE.sub("", text)


def truncate_to_width(text: str, max_width: int) -> str:
    """Truncate a string to fit within *max_width* visible columns.

    ANSI escape sequences are preserved but don't count toward the
    width budget, so color codes are never cut in half.  A trailing
    reset (``\\033[0m``) is appended when the string contains any
    ANSI code to guarantee no color leaks.

    Args:
        text: Text to truncate (may contain ANSI codes)
        max_width: Maximum display columns allowed

    Returns:
        Truncated string that fits in *max_width* columns.
    """
    result: List[str] = []
    col = 0
    i = 0
    has_ansi = False

    while i < len(text):
        # Check for ANSI escape at current position
        m = _ANSI_RE.match(text, i)
        if m:
            result.append(m.group())
            has_ansi = True
            i = m.end()
            continue

        ch = text[i]
        cat = unicodedata.east_asian_width(ch)
        w = 2 if cat in ("W", "F") else 1

        if col + w > max_width:
            break

        result.append(ch)
        col += w
        i += 1

    out = "".join(result)
    # Ensure we reset color at the end to prevent bleed
    if has_ansi:
        out += "\033[0m"
    return out


def format_time(seconds: float) -> str:
    """Format seconds as human-readable time.

    Args:
        seconds: Time in seconds

    Returns:
        Formatted string like "5.2s", "1m 30s", or "1h 23m 12s"
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}m {secs:.1f}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}h {mins}m {secs:.1f}s"


def align_columns(time_str: str, eta_str: str) -> str:
    """Right-align time and ETA into fixed-width columns.

    Args:
        time_str: Elapsed/duration string
        eta_str: ETA string

    Returns:
        Combined right-side string with consistent column widths
    """
    return (
        f"{time_str:>{config.TIME_COLUMN_WIDTH}}  "
        f"{eta_str:>{config.ETA_COLUMN_WIDTH}}"
    )


def right_justify(left: str, right: str, term_width: Optional[int] = None) -> str:
    """Right-justify a line with left and right parts.

    Uses display width (accounting for wide/emoji characters) to
    calculate padding correctly.

    Args:
        left: Left-aligned content
        right: Right-aligned content
        term_width: Terminal width (auto-detected if None)

    Returns:
        Formatted line with proper padding
    """
    if term_width is None:
        term_width = get_terminal_width()
    left_w = display_width(left)
    right_w = display_width(right)
    padding = max(1, term_width - left_w - right_w)
    return left + (" " * padding) + right


def build_dot_leader(
    left: str,
    right: str,
    term_width: int,
    animation_tick: int,
) -> str:
    """Build a line with an animated dot leader between left and right.

    A subtle pulse (brighter dot) travels through the dot leader to
    indicate activity, giving visual feedback even when no timing
    data is available.

    Args:
        left: Left-aligned content
        right: Right-aligned content
        term_width: Terminal width in columns
        animation_tick: Monotonic counter for pulse position

    Returns:
        Formatted line with animated dot leader
    """
    left_w = display_width(left)
    right_w = display_width(right)
    gap = term_width - left_w - right_w - 2  # 1 space padding each side

    if gap <= 0:
        return right_justify(left, right, term_width)

    # Build dot leader with traveling pulse
    dots = list(config.DOT_CHAR * gap)
    # Pulse travels the full width using monotonic tick counter
    pulse_pos = (animation_tick * 2) % max(gap, 1)
    for i in range(config.PULSE_WIDTH):
        idx = (pulse_pos + i) % gap
        dots[idx] = config.PULSE_CHAR

    leader = "".join(dots)
    return f"{left} {leader} {right}"


def build_progress_bar(
    left: str,
    right: str,
    term_width: int,
    pct: float,
    colors_enabled: Optional[bool] = None,
    bar_color: Optional[str] = None,
) -> str:
    """Build a line with a progress bar between left and right.

    Used for checks with timing estimates to show completion percentage.

    Args:
        left: Left-aligned content (spinner + name)
        right: Right-aligned content (time columns)
        term_width: Terminal width in columns
        pct: Completion percentage (0.0 to 1.0)
        colors_enabled: Whether to colorize the filled portion
        bar_color: ANSI color code to use for the filled portion (e.g. "\033[32m").
            Defaults to cyan if None.

    Returns:
        Formatted line with progress bar
    """
    left_w = display_width(left)
    right_w = display_width(right)
    gap = term_width - left_w - right_w - 2  # 1 space padding each side

    if gap < config.MIN_PROGRESS_BAR_WIDTH:
        return right_justify(left, right, term_width)

    pct_label = f"{int(pct * 100):>3}%"
    bar_width = gap - len(pct_label) - 3  # [] + space before pct
    if bar_width < config.MIN_BAR_CONTENT_WIDTH:
        return right_justify(left, right, term_width)

    filled = int(pct * bar_width)
    filled_str = config.PROGRESS_FILL * filled
    empty_str = config.PROGRESS_EMPTY * (bar_width - filled)

    # Colorize the filled portion in the category color when colors are enabled
    if colors_enabled is None:
        from slopmop.reporting.display.colors import supports_color

        colors_enabled = supports_color()
    if colors_enabled and filled > 0:
        color_code = bar_color if bar_color else "\033[36m"  # default cyan
        filled_str = f"{color_code}{filled_str}\033[0m"

    middle = f"[{filled_str}{empty_str}] {pct_label}"

    return f"{left} {middle} {right}"


def build_overall_progress(
    completed: int,
    total: int,
    elapsed: float,
    term_width: Optional[int] = None,
    colors_enabled: Optional[bool] = None,
) -> str:
    """Build the overall progress line with bar and stats.

    Args:
        completed: Number of completed checks
        total: Total number of checks
        elapsed: Elapsed time in seconds
        term_width: Terminal width (auto-detected if None)
        colors_enabled: Whether to colorize the filled portion

    Returns:
        Formatted progress line
    """
    if term_width is None:
        term_width = get_terminal_width()

    # Right side: count + elapsed
    elapsed_str = format_time(elapsed)
    right_side = f"{completed}/{total} · {elapsed_str} elapsed"

    # Calculate bar width from remaining space
    # "Progress: [" + bar + "]  " + right_side
    chrome_len = len("Progress: []  ") + len(right_side)
    bar_width = max(10, term_width - chrome_len)

    pct = completed / total if total > 0 else 0
    filled = int(pct * bar_width)
    filled_str = config.PROGRESS_FILL * filled
    empty_str = config.PROGRESS_EMPTY * (bar_width - filled)

    # Colorize filled portion in green when colors are enabled
    if colors_enabled is None:
        from slopmop.reporting.display.colors import supports_color

        colors_enabled = supports_color()
    if colors_enabled and filled > 0:
        filled_str = f"\033[32m{filled_str}\033[0m"  # green

    left_side = f"Progress: [{filled_str}{empty_str}]"
    return right_justify(left_side, right_side, term_width)


def truncate_for_inline(text: str, max_width: int) -> str:
    """Truncate text for inline failure preview.

    Args:
        text: Text to truncate
        max_width: Maximum display width

    Returns:
        Truncated text with ellipsis if needed
    """
    if not text:
        return ""

    # Get first non-empty line
    lines = text.strip().split("\n")
    first_line = ""
    for line in lines:
        stripped = line.strip()
        if stripped:
            first_line = stripped
            break

    if not first_line:
        return ""

    # Truncate if needed
    if display_width(first_line) <= max_width:
        return first_line

    # Truncate to fit with ellipsis
    result: List[str] = []
    width = 0
    for char in first_line:
        char_width = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if width + char_width + 1 > max_width:  # +1 for ellipsis
            break
        result.append(char)
        width += char_width

    return "".join(result) + "…"


def build_category_header(
    label: str,
    completed: int,
    total: int,
    term_width: Optional[int] = None,
) -> str:
    """Build a minimal category header line.

    Produces a line like: ── Python [3/6] ──────────────────

    Args:
        label: Category display label (e.g. "🐍 Python")
        completed: Completed checks in this category
        total: Total checks in this category
        term_width: Terminal width (auto-detected if None)

    Returns:
        Formatted header line
    """
    if term_width is None:
        term_width = get_terminal_width()

    dash = config.HEADER_DASH
    progress = f"[{completed}/{total}]"
    inner = f" {label} {progress} "

    # Calculate remaining dashes to fill the line
    inner_width = display_width(inner)
    prefix_width = 2  # "── " leading dashes
    remaining = max(0, term_width - prefix_width - inner_width)

    return f"{dash * prefix_width}{inner}{dash * remaining}"


def strip_category_prefix(check_name: str) -> str:
    """Strip the category prefix from a check name.

    'laziness:py-lint' → 'lint-format'
    'myopia:loc-lock'    → 'loc-lock'
    'some-check'         → 'some-check' (no prefix)

    Args:
        check_name: Full check name (possibly with category prefix)

    Returns:
        Check name without category prefix
    """
    if ":" in check_name:
        return check_name.split(":", 1)[1]
    return check_name
