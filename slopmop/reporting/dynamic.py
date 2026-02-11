"""Dynamic terminal display for quality gate execution.

Provides brew-style live updating display with spinners for running checks
and real-time progress updates.
"""

import os
import sys
import threading
import time
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

    def start(self) -> None:
        """Start the display and animation thread."""
        if self.quiet:
            return

        self._started = True
        self._stop_event.clear()

        if self._is_tty:
            # Start animation thread
            self._animation_thread = threading.Thread(
                target=self._animation_loop, daemon=True
            )
            self._animation_thread.start()

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
        pass

    def _animation_loop(self) -> None:
        """Background thread for spinner animation."""
        while not self._stop_event.is_set():
            with self._lock:
                self._spinner_idx = (self._spinner_idx + 1) % len(self.SPINNER_FRAMES)

            self._draw()

            # ~10 FPS for smooth animation
            time.sleep(0.1)

    def _draw(self) -> None:
        """Draw the current state to terminal."""
        if self.quiet or not self._is_tty:
            return

        with self._lock:
            lines = self._build_display()

        # Move cursor up to overwrite previous output
        if self._lines_drawn > 0:
            sys.stdout.write(f"\033[{self._lines_drawn}A")  # Move up
            sys.stdout.write("\033[J")  # Clear from cursor to end

        # Print new output
        output = "\n".join(lines)
        sys.stdout.write(output + "\n")
        sys.stdout.flush()

        self._lines_drawn = len(lines)

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
        total = len(self._checks)

        # Progress bar (only if we have checks)
        if total > 0:
            pct = completed / total
            bar_width = 30
            filled = int(pct * bar_width)
            bar = "█" * filled + "░" * (bar_width - filled)
            lines.append(f"Progress: [{bar}] {completed}/{total}")
            lines.append("")

        # Each check
        for name in self._check_order:
            if name not in self._checks:
                continue

            info = self._checks[name]
            line = self._format_check_line(info)
            lines.append(line)

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

    def _format_check_line(self, info: CheckDisplayInfo) -> str:
        """Format a single check line.

        Args:
            info: Check display info

        Returns:
            Formatted line string
        """
        if info.state == DisplayState.COMPLETED and info.result:
            icon = self.RESULT_ICONS.get(info.result.status, "❓")
            duration = f"({info.duration:.2f}s)"
            return f"{icon} {info.name}: {info.result.status.value} {duration}"

        elif info.state == DisplayState.RUNNING:
            spinner = self.SPINNER_FRAMES[self._spinner_idx]
            elapsed = time.time() - info.start_time
            return f"{spinner} {info.name}: running ({elapsed:.1f}s)"

        else:  # PENDING
            return f"○ {info.name}: pending"

    @property
    def completed_count(self) -> int:
        """Get count of completed checks."""
        return self._completed_count

    @property
    def all_completed(self) -> bool:
        """Check if all checks are completed."""
        return all(c.state == DisplayState.COMPLETED for c in self._checks.values())
