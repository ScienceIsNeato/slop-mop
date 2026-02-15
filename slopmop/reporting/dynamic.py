"""Dynamic terminal display for quality gate execution.

Provides brew-style live updating display with spinners for running checks
and real-time progress updates.
"""

import os
import shutil
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from slopmop.core.result import CheckResult, CheckStatus
from slopmop.reporting.timings import load_timings, save_timings


class DisplayState(Enum):
    """State of a check in the display."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"


@dataclass
class CheckDisplayInfo:
    """Display information for a single check."""

    name: str
    state: DisplayState = DisplayState.PENDING
    result: Optional[CheckResult] = None
    start_time: float = 0.0
    duration: float = 0.0
    expected_duration: Optional[float] = None  # From prior runs, None = no data
    completion_order: int = 0  # Order in which check completed (0 = not yet)


class DynamicDisplay:
    """Dynamic terminal display with live updates.

    Features:
    - Shows checks with current status as they are discovered
    - Animated spinners for running checks
    - In-place terminal updates using ANSI escape codes
    - Progress tracking for overall completion
    - Falls back gracefully for non-TTY environments
    """

    # Spinner frames (Braille dots pattern - smooth animation)
    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    # Width for right-justified columns — sized to fit header labels
    TIME_COLUMN_WIDTH = 12  # "Time Elapsed"
    ETA_COLUMN_WIDTH = 14  # "Est. Time Rem."

    # Dot leader characters for animated fill on running checks.
    # The "pulse" is a brighter dot that travels through the leader.
    DOT_CHAR = "·"
    PULSE_CHAR = "•"
    PULSE_WIDTH = 3  # How many chars wide the bright pulse is

    # Progress bar characters for checks with timing estimates
    PROGRESS_FILL = "█"
    PROGRESS_EMPTY = "░"

    RESULT_ICONS = {
        CheckStatus.PASSED: "✅",
        CheckStatus.FAILED: "❌",
        CheckStatus.WARNED: "⚠️",
        CheckStatus.SKIPPED: "⏭️",
        CheckStatus.NOT_APPLICABLE: "⊘",
        CheckStatus.ERROR: "💥",
    }

    def __init__(self, quiet: bool = False):
        """Initialize dynamic display.

        Args:
            quiet: Suppress output
        """
        self.quiet = quiet
        self._is_tty = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

        # Check display state - starts empty, checks added dynamically
        self._checks: Dict[str, CheckDisplayInfo] = {}
        self._check_order: List[str] = []
        self._completed_count = 0
        self._disabled_names: List[str] = []

        # Animation state
        self._spinner_idx = 0
        self._animation_tick = 0  # Monotonic counter for dot leader traversal
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._animation_thread: Optional[threading.Thread] = None

        # Track lines for redraw
        self._lines_drawn = 0
        self._started = False
        self._stopped = False

        # Timing for ETA calculation
        self._overall_start_time: Optional[float] = None
        self._total_checks_expected: int = 0  # Set via set_total_checks()
        self._completion_counter: int = 0  # Tracks order of completion

        # Historical timing data for ETAs
        self._historical_timings: Dict[str, float] = {}

    def load_historical_timings(self, project_root: str) -> None:
        """Load historical timing data from disk.

        Args:
            project_root: Project root directory
        """
        self._historical_timings = load_timings(project_root)

    def save_historical_timings(self, project_root: str) -> None:
        """Save current run's timings to disk for future ETAs.

        Args:
            project_root: Project root directory
        """
        durations = {
            name: info.duration
            for name, info in self._checks.items()
            if info.state == DisplayState.COMPLETED and info.duration > 0
        }
        if durations:
            save_timings(project_root, durations)

    def start(self) -> None:
        """Start the display and animation thread."""
        if self.quiet:
            return

        self._started = True
        self._stop_event.clear()
        self._overall_start_time = time.time()

        if self._is_tty:
            # Start animation thread
            self._animation_thread = threading.Thread(
                target=self._animation_loop, daemon=True
            )
            self._animation_thread.start()

    def set_total_checks(self, total: int) -> None:
        """Set expected total number of checks for accurate progress.

        Args:
            total: Total number of checks that will run
        """
        with self._lock:
            self._total_checks_expected = total

    def stop(self) -> None:
        """Stop the display and animation thread."""
        if self._stopped:
            return
        self._stopped = True

        self._stop_event.set()
        if self._animation_thread and self._animation_thread.is_alive():
            self._animation_thread.join(timeout=0.5)

        # Final redraw to ensure clean state
        if self._started and self._is_tty:
            self._draw()
            # Print a newline to separate from summary
            print()

    def on_check_start(self, name: str) -> None:
        """Called when a check starts running.

        Args:
            name: Check name
        """
        with self._lock:
            if name not in self._checks:
                self._checks[name] = CheckDisplayInfo(name=name)
                self._check_order.append(name)

            self._checks[name].state = DisplayState.RUNNING
            self._checks[name].start_time = time.time()

            # Populate expected duration from historical data
            if name in self._historical_timings:
                self._checks[name].expected_duration = self._historical_timings[name]

        if not self._is_tty and not self.quiet:
            # Static mode: print start message
            print(f"  ◐ {name}: running...")

    def on_check_complete(self, result: CheckResult) -> None:
        """Called when a check completes.

        Args:
            result: Check result
        """
        with self._lock:
            if result.name not in self._checks:
                # Check wasn't started (e.g., skipped due to dependency)
                self._checks[result.name] = CheckDisplayInfo(name=result.name)
                self._check_order.append(result.name)

            info = self._checks[result.name]
            info.state = DisplayState.COMPLETED
            info.result = result
            info.duration = result.duration
            self._completed_count += 1
            self._completion_counter += 1
            info.completion_order = self._completion_counter

        if not self._is_tty and not self.quiet:
            # Static mode: print completion
            icon = self.RESULT_ICONS.get(result.status, "❓")
            print(
                f"{icon} {result.name}: {result.status.value} ({result.duration:.2f}s)"
            )

    def on_check_disabled(self, name: str) -> None:
        """Called when a check is disabled and won't run.

        Args:
            name: Check name
        """
        with self._lock:
            self._disabled_names.append(name)

    def _animation_loop(self) -> None:
        """Background thread for spinner animation."""
        while not self._stop_event.is_set():
            with self._lock:
                self._spinner_idx = (self._spinner_idx + 1) % len(self.SPINNER_FRAMES)
                self._animation_tick += 1

            self._draw()

            # ~10 FPS for smooth animation
            time.sleep(0.1)

    def _draw(self) -> None:
        """Draw the current state to terminal.

        All cursor movement and writing is done under the lock to prevent
        interleaving. Lines are truncated to terminal width to prevent
        wrapping, which would desync the cursor-up line count.
        """
        if self.quiet or not self._is_tty:
            return

        with self._lock:
            lines = self._build_display()

            try:
                term_width = shutil.get_terminal_size().columns
            except (ValueError, OSError):
                term_width = 80

            # Move cursor up to overwrite previous output
            if self._lines_drawn > 0:
                sys.stdout.write(f"\033[{self._lines_drawn}A")  # Move up
                sys.stdout.write("\033[J")  # Clear from cursor to end

            # Truncate lines to prevent wrapping (which breaks cursor math)
            truncated = [line[:term_width] for line in lines]

            output = "\n".join(truncated)
            sys.stdout.write(output + "\n")
            sys.stdout.flush()

            self._lines_drawn = len(truncated)

    def _build_display(self) -> List[str]:
        """Build the display lines.

        Returns:
            List of lines to display
        """
        lines: List[str] = []

        # Count stats
        completed = sum(
            1 for c in self._checks.values() if c.state == DisplayState.COMPLETED
        )
        running = sum(
            1 for c in self._checks.values() if c.state == DisplayState.RUNNING
        )
        # Use expected total if set, otherwise use discovered checks
        total = (
            self._total_checks_expected
            if self._total_checks_expected > 0
            else len(self._checks)
        )

        # Progress bar (only if we have checks)
        if total > 0:
            lines.append(self._build_progress_line(completed, total))

        # Sort checks: completed first (by completion order),
        # then active (running+pending) sorted by timing estimate
        completed_checks: List[CheckDisplayInfo] = []
        active_checks: List[CheckDisplayInfo] = []

        for name in self._check_order:
            if name not in self._checks:
                continue
            info = self._checks[name]
            if info.state == DisplayState.COMPLETED:
                completed_checks.append(info)
            else:
                active_checks.append(info)

        # Sort completed by completion order
        completed_checks.sort(key=lambda c: c.completion_order)

        # Sort active: checks with estimates first (longest first for
        # visual stability — they stay at top longest as shorter checks
        # complete and move to the completed section above).
        # Checks without estimates go last, sorted alphabetically.
        active_checks.sort(
            key=lambda c: (
                0 if c.expected_duration is not None else 1,
                -(c.expected_duration or 0),
                c.name,
            )
        )

        # Display in order: completed, then sorted active
        for info in completed_checks:
            lines.append(self._format_check_line(info))
        for info in active_checks:
            lines.append(self._format_check_line(info))

        # Disabled summary (shown after checks, before status)
        if self._disabled_names:
            disabled_str = ", ".join(self._disabled_names)
            lines.append(f"Disabled: {disabled_str}")

        # Status summary - only show when checks are still running
        if running > 0:
            lines.append("")
            lines.append(f"🔄 {running} running · ✓ {completed} done")

        return lines

    def _build_progress_line(self, completed: int, total: int) -> str:
        """Build the progress line with bar and stats (no ETA).

        Args:
            completed: Number of completed checks
            total: Total number of checks

        Returns:
            Formatted progress line
        """
        try:
            term_width = shutil.get_terminal_size().columns
        except (ValueError, OSError):
            term_width = 80

        # Calculate elapsed time
        elapsed = 0.0
        if self._overall_start_time:
            elapsed = time.time() - self._overall_start_time

        # Right side: count + elapsed
        elapsed_str = self._format_time(elapsed)
        right_side = f"{completed}/{total} · {elapsed_str} elapsed"

        # Calculate bar width from remaining space
        # "Progress: [" + bar + "]  " + right_side
        chrome_len = len("Progress: []  ") + len(right_side)
        bar_width = max(10, term_width - chrome_len)

        pct = completed / total if total > 0 else 0
        filled = int(pct * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)

        left_side = f"Progress: [{bar}]"
        return self._right_justify(left_side, right_side)

    def _format_time(self, seconds: float) -> str:
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

    def _format_check_line(self, info: CheckDisplayInfo) -> str:
        """Format a single check line with aligned columns.

        Layout: icon name <dot_leader_or_space> elapsed_col  eta_col

        Args:
            info: Check display info

        Returns:
            Formatted line string
        """
        try:
            term_width = shutil.get_terminal_size().columns
        except (ValueError, OSError):
            term_width = 80

        if info.state == DisplayState.COMPLETED and info.result:
            icon = self.RESULT_ICONS.get(info.result.status, "❓")
            left = f"{icon} {info.name}: {info.result.status.value}"
            time_str = self._format_time(info.duration)
            right = self._align_columns(time_str, "")
            return self._right_justify(left, right)

        elif info.state == DisplayState.RUNNING:
            spinner = self.SPINNER_FRAMES[self._spinner_idx]
            elapsed = time.time() - info.start_time
            left = f"{spinner} {info.name}"
            time_str = self._format_time(elapsed)
            if info.expected_duration is not None and info.expected_duration > 0:
                remaining = max(0.0, info.expected_duration - elapsed)
                eta_str = self._format_time(remaining)
                pct = min(elapsed / info.expected_duration, 0.99)
                right = self._align_columns(time_str, eta_str)
                # Show progress bar for checks with timing estimates
                return self._progress_bar_line(left, right, term_width, pct)
            else:
                eta_str = "N/A"
                right = self._align_columns(time_str, eta_str)
                # Fill gap with animated dot leader for unknown checks
                return self._dot_leader_line(left, right, term_width)

        else:  # PENDING
            left = f"○ {info.name}"
            time_str = ""
            if info.expected_duration is not None:
                eta_str = self._format_time(info.expected_duration)
            else:
                eta_str = "N/A"
            right = self._align_columns(time_str, eta_str)
            return self._right_justify(left, right)

    def _align_columns(self, time_str: str, eta_str: str) -> str:
        """Right-align the time and ETA into fixed-width columns.

        Args:
            time_str: Elapsed/duration string
            eta_str: ETA string

        Returns:
            Combined right-side string with consistent column widths
        """
        return (
            f"{time_str:>{self.TIME_COLUMN_WIDTH}}  {eta_str:>{self.ETA_COLUMN_WIDTH}}"
        )

    def _progress_bar_line(
        self, left: str, right: str, term_width: int, pct: float
    ) -> str:
        """Build a line with a progress bar between left and right.

        Replaces the dot leader animation for checks that have timing
        estimates, showing actual completion percentage.

        Args:
            left: Left-aligned content (spinner + name)
            right: Right-aligned content (time columns)
            term_width: Terminal width in columns
            pct: Completion percentage (0.0 to 1.0)

        Returns:
            Formatted line with progress bar
        """
        left_w = self._display_width(left)
        right_w = self._display_width(right)
        gap = term_width - left_w - right_w - 2  # 1 space padding each side

        if gap < 12:
            return self._right_justify(left, right)

        pct_label = f"{int(pct * 100):>3}%"
        bar_width = gap - len(pct_label) - 3  # [] + space before pct
        if bar_width < 5:
            return self._right_justify(left, right)

        filled = int(pct * bar_width)
        bar = self.PROGRESS_FILL * filled + self.PROGRESS_EMPTY * (bar_width - filled)
        middle = f"[{bar}] {pct_label}"

        return f"{left} {middle} {right}"

    def _dot_leader_line(self, left: str, right: str, term_width: int) -> str:
        """Build a line with an animated dot leader between left and right.

        A subtle pulse (brighter dot) travels through the dot leader to
        indicate activity, giving visual feedback even when no timing
        data is available.

        Args:
            left: Left-aligned content
            right: Right-aligned content
            term_width: Terminal width in columns

        Returns:
            Formatted line with animated dot leader
        """
        left_w = self._display_width(left)
        right_w = self._display_width(right)
        gap = term_width - left_w - right_w - 2  # 1 space padding each side

        if gap <= 0:
            return self._right_justify(left, right)

        # Build dot leader with traveling pulse
        dots = list(self.DOT_CHAR * gap)
        # Pulse travels the full width using monotonic tick counter
        pulse_pos = (self._animation_tick * 2) % max(gap, 1)
        for i in range(self.PULSE_WIDTH):
            idx = (pulse_pos + i) % gap
            dots[idx] = self.PULSE_CHAR

        leader = "".join(dots)
        return f"{left} {leader} {right}"

    def _right_justify(self, left: str, right: str) -> str:
        """Right-justify a line with left and right parts.

        Uses display width (accounting for wide/emoji characters) to
        calculate padding correctly.

        Args:
            left: Left-aligned content
            right: Right-aligned content

        Returns:
            Formatted line with proper padding
        """
        try:
            term_width = shutil.get_terminal_size().columns
        except (ValueError, OSError):
            term_width = 80
        left_width = self._display_width(left)
        right_width = self._display_width(right)
        padding = max(1, term_width - left_width - right_width)
        return left + (" " * padding) + right

    @staticmethod
    def _display_width(text: str) -> int:
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

    @property
    def completed_count(self) -> int:
        """Get count of completed checks."""
        return self._completed_count

    @property
    def all_completed(self) -> bool:
        """Check if all checks are completed."""
        return all(c.state == DisplayState.COMPLETED for c in self._checks.values())
