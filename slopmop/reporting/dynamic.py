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

    # Width for right-justified ETA column
    ETA_COLUMN_WIDTH = 15

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

        # Animation state
        self._spinner_idx = 0
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

        Note: We don't print here - the executor logger already prints disabled messages.
        """
        # Intentionally empty - avoid duplicate messages

    def _animation_loop(self) -> None:
        """Background thread for spinner animation."""
        while not self._stop_event.is_set():
            with self._lock:
                self._spinner_idx = (self._spinner_idx + 1) % len(self.SPINNER_FRAMES)

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

        # Progress bar with ETA (only if we have checks)
        if total > 0:
            lines.append(self._build_progress_line(completed, total))
            lines.append("")

        # Sort checks: completed first (by completion order), then running, then pending
        completed_checks: List[CheckDisplayInfo] = []
        running_checks: List[CheckDisplayInfo] = []
        pending_checks: List[CheckDisplayInfo] = []

        for name in self._check_order:
            if name not in self._checks:
                continue
            info = self._checks[name]
            if info.state == DisplayState.COMPLETED:
                completed_checks.append(info)
            elif info.state == DisplayState.RUNNING:
                running_checks.append(info)
            else:
                pending_checks.append(info)

        # Sort completed by completion order
        completed_checks.sort(key=lambda c: c.completion_order)

        # Display in order: completed, running, pending
        for info in completed_checks:
            lines.append(self._format_check_line(info))
        for info in running_checks:
            lines.append(self._format_check_line(info))
        for info in pending_checks:
            lines.append(self._format_check_line(info))

        # Status summary
        if total > 0:
            lines.append("")
            status_parts: List[str] = []
            if running > 0:
                status_parts.append(f"🔄 {running} running")
            if completed > 0:
                status_parts.append(f"✓ {completed} done")

            if status_parts:
                lines.append(" · ".join(status_parts))

        return lines

    def _build_progress_line(self, completed: int, total: int) -> str:
        """Build the progress line with bar, stats, and ETA.

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

        # Calculate times
        elapsed = 0.0
        if self._overall_start_time:
            elapsed = time.time() - self._overall_start_time

        # Calculate ETA based on average completion time
        eta_str = ""
        if completed > 0 and completed < total:
            total_duration = sum(
                c.duration
                for c in self._checks.values()
                if c.state == DisplayState.COMPLETED
            )
            avg_time = total_duration / completed
            remaining = total - completed
            eta = avg_time * remaining
            eta_str = f"ETA: {self._format_time(eta)}"
        elif completed == total:
            eta_str = "done"

        # Right side
        elapsed_str = self._format_time(elapsed)
        right_side = (
            f"{elapsed_str} elapsed · {eta_str}"
            if eta_str
            else f"{elapsed_str} elapsed"
        )

        # Calculate bar width from remaining space
        count_str = f"{completed}/{total}"
        # "Progress: [" + bar + "] " + count + padding(min 2) + right_side
        chrome_len = len("Progress: [] ") + len(count_str) + 2 + len(right_side)
        bar_width = max(10, term_width - chrome_len)

        pct = completed / total if total > 0 else 0
        filled = int(pct * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)

        left_side = f"Progress: [{bar}] {count_str}"
        return self._right_justify(left_side, right_side)

    def _format_time(self, seconds: float) -> str:
        """Format seconds as human-readable time.

        Args:
            seconds: Time in seconds

        Returns:
            Formatted string like "5.2s" or "1m 23s"
        """
        if seconds < 60:
            return f"{seconds:.1f}s"
        else:
            mins = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{mins}m {secs}s"

    def _format_check_line(self, info: CheckDisplayInfo) -> str:
        """Format a single check line.

        Args:
            info: Check display info

        Returns:
            Formatted line string
        """
        if info.state == DisplayState.COMPLETED and info.result:
            icon = self.RESULT_ICONS.get(info.result.status, "❓")
            left = f"{icon} {info.name}: {info.result.status.value}"
            right = f"({info.duration:.2f}s)"
            return self._right_justify(left, right)

        elif info.state == DisplayState.RUNNING:
            spinner = self.SPINNER_FRAMES[self._spinner_idx]
            elapsed = time.time() - info.start_time
            left = f"{spinner} {info.name}"
            right = f"{elapsed:.1f}s   ETA: N/A"
            return self._right_justify(left, right)

        else:  # PENDING
            left = f"○ {info.name}"
            right = "ETA: N/A"
            return self._right_justify(left, right)

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
