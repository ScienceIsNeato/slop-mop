"""Display rendering utilities.

Static helper functions for formatting and measuring terminal output.
"""

import shutil
import unicodedata
from typing import List, Optional

from slopmop.reporting.display import config


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

    Wide characters (emoji, CJK) take 2 columns. This prevents
    lines from overflowing and breaking cursor-based redraw.

    Args:
        text: String to measure

    Returns:
        Number of terminal columns the text occupies
    """
    width = 0
    for ch in text:
        cat = unicodedata.east_asian_width(ch)
        if cat in ("W", "F"):
            width += 2
        else:
            width += 1
    return width


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
) -> str:
    """Build a line with a progress bar between left and right.

    Used for checks with timing estimates to show completion percentage.

    Args:
        left: Left-aligned content (spinner + name)
        right: Right-aligned content (time columns)
        term_width: Terminal width in columns
        pct: Completion percentage (0.0 to 1.0)

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
    bar = config.PROGRESS_FILL * filled + config.PROGRESS_EMPTY * (bar_width - filled)
    middle = f"[{bar}] {pct_label}"

    return f"{left} {middle} {right}"


def build_overall_progress(
    completed: int,
    total: int,
    elapsed: float,
    term_width: Optional[int] = None,
) -> str:
    """Build the overall progress line with bar and stats.

    Args:
        completed: Number of completed checks
        total: Total number of checks
        elapsed: Elapsed time in seconds
        term_width: Terminal width (auto-detected if None)

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
    bar = config.PROGRESS_FILL * filled + config.PROGRESS_EMPTY * (bar_width - filled)

    left_side = f"Progress: [{bar}]"
    return right_justify(left_side, right_side, term_width)


def build_sparkline(current: float, historical: list[float], width: int = 7) -> str:
    """Build a sparkline showing current timing vs historical.

    Shows how current run compares to past runs (#8).

    Args:
        current: Current run duration
        historical: List of past durations (most recent first)
        width: Number of characters in sparkline

    Returns:
        Sparkline string like "▁▂▄▆█"
    """
    if not historical:
        return ""

    # Include current + up to (width-1) historical values
    values = [current] + historical[: width - 1]
    if not values:
        return ""

    min_val = min(values)
    max_val = max(values)
    range_val = max_val - min_val

    if range_val == 0:
        # All same value - show middle bars
        return config.SPARKLINE_CHARS[4] * len(values)

    # Map values to sparkline characters
    chars = config.SPARKLINE_CHARS
    result: List[str] = []
    for val in values:
        normalized = (val - min_val) / range_val
        idx = int(normalized * (len(chars) - 1))
        result.append(chars[idx])

    return "".join(result)


def build_category_header(
    category: str,
    emoji: str,
    display_name: str,
    stats: tuple[int, int],  # (completed, total)
    term_width: Optional[int] = None,
) -> str:
    """Build a category header line with box drawing.

    Args:
        category: Category key
        emoji: Category emoji
        display_name: Human-readable name
        stats: (completed, total) for this category
        term_width: Terminal width (auto-detected if None)

    Returns:
        Formatted header line like "┌──🐍 Python [2/3] ───────────────┐"
    """
    if term_width is None:
        term_width = get_terminal_width()

    completed, total = stats
    # Build the label: emoji + name + progress
    progress = f"[{completed}/{total}]"
    label = f" {emoji} {display_name} {progress} "

    # Calculate padding on each side
    label_width = display_width(label)
    available = term_width - label_width - 2  # For corner chars
    left_pad = 2  # Minimum left padding
    right_pad = max(1, available - left_pad)

    left_line = config.HEADER_HORIZONTAL * left_pad
    right_line = config.HEADER_HORIZONTAL * right_pad

    return f"{config.HEADER_LEFT}{left_line}{label}{right_line}{config.HEADER_RIGHT}"


def build_check_connector(is_last: bool = False) -> str:
    """Build the connector character for a check under a category.

    Args:
        is_last: Whether this is the last check in the category

    Returns:
        Connector string like "├─" or "└─"
    """
    if is_last:
        return f"{config.CONNECTOR_END}{config.HEADER_HORIZONTAL}"
    return f"{config.CONNECTOR_TEE}{config.HEADER_HORIZONTAL}"


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
