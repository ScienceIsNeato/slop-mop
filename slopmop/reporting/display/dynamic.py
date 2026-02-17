"""Dynamic terminal display for quality gate execution.

Provides brew-style live updating display with spinners for running checks
and real-time progress updates. Now with category grouping, visual hierarchy,
and inline failure previews.
"""

import os
import sys
import threading
import time
from collections import defaultdict
from typing import Dict, List, Optional

from slopmop.constants import STATUS_EMOJI
from slopmop.core.result import CheckResult, CheckStatus
from slopmop.reporting.display import config
from slopmop.reporting.display.colors import (
    bold,
    category_header_color,
    dim,
    reset_color,
    status_color,
    supports_color,
)
from slopmop.reporting.display.renderer import (
    align_columns,
    build_category_header,
    build_check_connector,
    build_dot_leader,
    build_overall_progress,
    build_progress_bar,
    display_width,
    format_time,
    get_terminal_width,
    right_justify,
    truncate_for_inline,
)
from slopmop.reporting.display.state import CheckDisplayInfo, DisplayState
from slopmop.reporting.timings import load_timings, save_timings


class DynamicDisplay:
    """Dynamic terminal display with live updates.

    Features:
    - Shows checks with current status as they are discovered
    - Animated spinners for running checks
    - In-place terminal updates using ANSI escape codes
    - Progress tracking for overall completion
    - Falls back gracefully for non-TTY environments
    """

    # Class-level aliases to config for backwards compatibility
    SPINNER_FRAMES = config.SPINNER_FRAMES
    TIME_COLUMN_WIDTH = config.TIME_COLUMN_WIDTH
    ETA_COLUMN_WIDTH = config.ETA_COLUMN_WIDTH
    DOT_CHAR = config.DOT_CHAR
    PULSE_CHAR = config.PULSE_CHAR
    PULSE_WIDTH = config.PULSE_WIDTH
    PROGRESS_FILL = config.PROGRESS_FILL
    PROGRESS_EMPTY = config.PROGRESS_EMPTY

    def __init__(self, quiet: bool = False):
        """Initialize dynamic display.

        Args:
            quiet: Suppress output
        """
        self.quiet = quiet
        self._is_tty = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        self._colors_enabled = supports_color()

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

        # Historical timing data for ETAs and sparklines
        self._historical_timings: Dict[str, float] = {}
        self._historical_timing_lists: Dict[str, List[float]] = {}  # For sparklines

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

    def on_check_start(self, name: str, category: Optional[str] = None) -> None:
        """Called when a check starts running.

        Args:
            name: Check name
            category: Category key (python, quality, security, etc.)
        """
        with self._lock:
            if name not in self._checks:
                self._checks[name] = CheckDisplayInfo(name=name, category=category)
                self._check_order.append(name)
            else:
                # Update category if not set
                if category and not self._checks[name].category:
                    self._checks[name].category = category

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
                self._checks[result.name] = CheckDisplayInfo(
                    name=result.name, category=result.category
                )
                self._check_order.append(result.name)

            info = self._checks[result.name]
            info.state = DisplayState.COMPLETED
            info.result = result
            info.duration = result.duration
            # Update category from result if not already set
            if result.category and not info.category:
                info.category = result.category
            self._completed_count += 1
            self._completion_counter += 1
            info.completion_order = self._completion_counter

        if not self._is_tty and not self.quiet:
            # Static mode: print completion
            icon = STATUS_EMOJI.get(result.status, "❓")
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
                self._spinner_idx = (self._spinner_idx + 1) % len(config.SPINNER_FRAMES)
                self._animation_tick += 1

            self._draw()

            # Sleep for refresh rate
            time.sleep(1.0 / config.REFRESH_RATE_HZ)

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
            term_width = get_terminal_width()

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

    def _group_checks_by_category(
        self,
    ) -> tuple[Dict[str, List[CheckDisplayInfo]], List[CheckDisplayInfo]]:
        """Group checks by category.

        Returns:
            Tuple of (by_category dict, uncategorized list)
        """
        by_category: Dict[str, List[CheckDisplayInfo]] = defaultdict(list)
        uncategorized: List[CheckDisplayInfo] = []

        for name in self._check_order:
            if name not in self._checks:
                continue
            info = self._checks[name]
            if info.category:
                by_category[info.category].append(info)
            else:
                uncategorized.append(info)

        return dict(by_category), uncategorized

    def _render_category_section(
        self,
        category: str,
        checks: List[CheckDisplayInfo],
        stats: tuple[int, int],
        term_width: int,
    ) -> List[str]:
        """Render a category header and its checks.

        Args:
            category: Category key
            checks: List of checks in this category
            stats: Tuple of (completed, total) for this category
            term_width: Terminal width

        Returns:
            List of lines for this category section
        """
        lines: List[str] = []

        # Get category info
        emoji, display_name = config.CATEGORY_INFO.get(
            category, ("❓", category.title())
        )

        # Add category header with box drawing
        header_color = category_header_color(category, self._colors_enabled)
        reset = reset_color(self._colors_enabled)
        header = build_category_header(category, emoji, display_name, stats, term_width)
        lines.append(f"{header_color}{header}{reset}")

        # Sort checks: running first, then by completion order
        checks.sort(
            key=lambda c: (
                0 if c.state == DisplayState.RUNNING else 1,
                c.completion_order if c.state == DisplayState.COMPLETED else 0,
            )
        )

        # Display checks under this category
        for i, info in enumerate(checks):
            is_last = i == len(checks) - 1
            connector = build_check_connector(is_last)
            line = self._format_check_line(info, connector)
            lines.append(line)

        return lines

    def _sort_uncategorized(
        self, checks: List[CheckDisplayInfo]
    ) -> List[CheckDisplayInfo]:
        """Sort uncategorized checks for display.

        Completed checks first (by completion order), then running checks
        sorted by estimate (longest first for visual stability).

        Args:
            checks: List of uncategorized checks

        Returns:
            Sorted list (modifies in place and returns same list)
        """
        checks.sort(
            key=lambda c: (
                # Primary: completed (0) before running/pending (1)
                0 if c.state == DisplayState.COMPLETED else 1,
                # Secondary (for completed): completion order
                c.completion_order if c.state == DisplayState.COMPLETED else 0,
                # Secondary (for running): with estimate before without
                0 if c.expected_duration is not None else 1,
                # Tertiary (for running): longest estimate first (negative)
                -(c.expected_duration or 0),
                # Fallback: alphabetical
                c.name,
            )
        )
        return checks

    def _build_display(self) -> List[str]:
        """Build the display lines.

        Groups checks by category with headers for visual organization.

        Returns:
            List of lines to display
        """
        lines: List[str] = []
        term_width = get_terminal_width()

        # Count overall stats
        completed = sum(
            1 for c in self._checks.values() if c.state == DisplayState.COMPLETED
        )
        running = sum(
            1 for c in self._checks.values() if c.state == DisplayState.RUNNING
        )
        total = (
            self._total_checks_expected
            if self._total_checks_expected > 0
            else len(self._checks)
        )

        # Progress bar (only if we have checks)
        if total > 0:
            elapsed = (
                time.time() - self._overall_start_time
                if self._overall_start_time
                else 0.0
            )
            lines.append(build_overall_progress(completed, total, elapsed))
            lines.append("")

        # Group and compute stats
        by_category, uncategorized = self._group_checks_by_category()
        category_stats = {
            cat: (
                sum(1 for c in checks if c.state == DisplayState.COMPLETED),
                len(checks),
            )
            for cat, checks in by_category.items()
        }

        # Render categories in defined order
        for category in config.CATEGORY_ORDER:
            if category not in by_category or not by_category[category]:
                continue
            stats = category_stats.get(category, (0, len(by_category[category])))
            lines.extend(
                self._render_category_section(
                    category, by_category[category], stats, term_width
                )
            )

        # Render uncategorized checks
        if uncategorized:
            if by_category:
                lines.append("")
            for info in self._sort_uncategorized(uncategorized):
                lines.append(self._format_check_line(info))

        # Disabled summary
        if self._disabled_names:
            lines.append("")
            lines.append(f"Disabled: {', '.join(self._disabled_names)}")

        # Status summary - only when checks still running
        if running > 0:
            lines.append("")
            lines.append(f"🔄 {running} running · ✓ {completed} done")

        return lines

    def _format_completed_line(self, info: CheckDisplayInfo, width: int) -> str:
        """Format a completed check line.

        Args:
            info: Check display info (must be completed with result)
            width: Available width for the line

        Returns:
            Formatted line (without connector)
        """
        assert info.result is not None

        icon = STATUS_EMOJI.get(info.result.status, "❓")
        color_prefix = status_color(info.result.status, self._colors_enabled)
        color_suffix = reset_color(self._colors_enabled)
        status_text = f"{color_prefix}{info.result.status.value}{color_suffix}"
        left = f"{icon} {info.name}: {status_text}"

        # Inline failure preview for failed/error checks
        preview = ""
        if info.result.status in (CheckStatus.FAILED, CheckStatus.ERROR):
            preview_text = info.result.error or info.result.output
            if preview_text:
                preview = truncate_for_inline(preview_text, config.MAX_PREVIEW_WIDTH)
                if preview:
                    preview = f" — {preview}"

        # Timing comparison indicator
        sparkline = ""
        if info.expected_duration and info.expected_duration > 0 and info.duration > 0:
            ratio = info.duration / info.expected_duration
            if ratio < 0.8:
                sparkline = " ⚡"
            elif ratio > 1.2:
                sparkline = " 🐢"

        time_str = format_time(info.duration) + sparkline
        right = align_columns(time_str, "")
        line = right_justify(left + preview, right, width)
        return dim(line, self._colors_enabled)

    def _format_running_line(self, info: CheckDisplayInfo, width: int) -> str:
        """Format a running check line with spinner and progress.

        Args:
            info: Check display info (must be running)
            width: Available width for the line

        Returns:
            Formatted line (without connector)
        """
        # Category-specific spinner
        if info.category and info.category in config.CATEGORY_SPINNERS:
            frames = config.CATEGORY_SPINNERS[info.category]
            spinner = frames[self._spinner_idx % len(frames)]
        else:
            spinner = config.SPINNER_FRAMES[self._spinner_idx]

        elapsed = time.time() - info.start_time
        left = f"{spinner} {info.name}"
        time_str = format_time(elapsed)

        if info.expected_duration and info.expected_duration > 0:
            remaining = max(0.0, info.expected_duration - elapsed)
            eta_str = format_time(remaining)
            pct = min(elapsed / info.expected_duration, 0.99)
            right = align_columns(time_str, eta_str)
            line = build_progress_bar(left, right, width, pct)
        else:
            right = align_columns(time_str, "N/A")
            line = build_dot_leader(left, right, width, self._animation_tick)

        return bold(line, self._colors_enabled)

    def _format_pending_line(self, info: CheckDisplayInfo, width: int) -> str:
        """Format a pending check line.

        Args:
            info: Check display info (pending state)
            width: Available width for the line

        Returns:
            Formatted line (without connector)
        """
        left = f"○ {info.name}"
        eta_str = (
            format_time(info.expected_duration) if info.expected_duration else "N/A"
        )
        right = align_columns("", eta_str)
        return right_justify(left, right, width)

    def _format_check_line(self, info: CheckDisplayInfo, connector: str = "") -> str:
        """Format a single check line with aligned columns.

        Dispatches to state-specific formatters based on check state.

        Args:
            info: Check display info
            connector: Optional box-drawing connector prefix

        Returns:
            Formatted line string
        """
        available_width = get_terminal_width() - display_width(connector)

        if info.state == DisplayState.COMPLETED and info.result:
            line = self._format_completed_line(info, available_width)
        elif info.state == DisplayState.RUNNING:
            line = self._format_running_line(info, available_width)
        else:
            line = self._format_pending_line(info, available_width)

        return connector + line

    @property
    def completed_count(self) -> int:
        """Get count of completed checks."""
        return self._completed_count

    @property
    def all_completed(self) -> bool:
        """Check if all checks are completed."""
        with self._lock:
            return all(c.state == DisplayState.COMPLETED for c in self._checks.values())

    # Backwards compatibility methods - delegate to renderer module
    def _format_time(self, seconds: float) -> str:
        """Format seconds as human-readable time. (Backwards compatibility)"""
        return format_time(seconds)

    def _build_progress_line(self, completed: int, total: int) -> str:
        """Build the progress line with bar and stats. (Backwards compatibility)"""
        elapsed = 0.0
        if self._overall_start_time:
            elapsed = time.time() - self._overall_start_time
        return build_overall_progress(completed, total, elapsed)

    def _right_justify(self, left: str, right: str) -> str:
        """Right-justify a line. (Backwards compatibility)"""
        return right_justify(left, right)

    def _align_columns(self, time_str: str, eta_str: str) -> str:
        """Right-align the time and ETA. (Backwards compatibility)"""
        return align_columns(time_str, eta_str)

    @staticmethod
    def _display_width(text: str) -> int:
        """Calculate terminal display width. (Backwards compatibility)"""
        return display_width(text)
