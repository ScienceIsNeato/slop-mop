"""Dynamic terminal display for quality gate execution.

Provides brew-style live updating display with spinners for running checks
and real-time progress updates.
"""

import os
import sys
import threading
import time
from typing import Dict, List, Optional

from slopmop.constants import STATUS_EMOJI
from slopmop.core.result import CheckResult, CheckStatus
from slopmop.reporting.display import config
from slopmop.reporting.display.colors import (
    category_header_color,
    reset_color,
    status_color,
    supports_color,
)
from slopmop.reporting.display.renderer import (
    align_columns,
    build_category_header,
    build_dot_leader,
    build_overall_progress,
    build_progress_bar,
    format_time,
    get_terminal_width,
    right_justify,
    strip_category_prefix,
    truncate_for_inline,
    truncate_to_width,
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
        self._disabled_names: List[str] = []  # config-disabled checks
        self._na_names: List[str] = []  # not-applicable checks

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

    def register_pending_checks(self, checks: List[tuple[str, Optional[str]]]) -> None:
        """Register all checks as pending so they appear immediately.

        Called before execution begins so the full list is visible from
        the start — no more "items only appear when they start".

        Args:
            checks: List of (full_name, category_key) tuples
        """
        with self._lock:
            for name, category in checks:
                if name not in self._checks:
                    info = CheckDisplayInfo(name=name, category=category)
                    # Populate expected duration from historical data
                    if name in self._historical_timings:
                        info.expected_duration = self._historical_timings[name]
                    self._checks[name] = info
                    self._check_order.append(name)

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
            # Static mode: print completion (full names since no group headers)
            icon = STATUS_EMOJI.get(result.status, "❓")
            print(
                f"{icon} {result.name}: {result.status.value} ({result.duration:.2f}s)"
            )

    def on_check_disabled(self, name: str) -> None:
        """Called when a check is disabled by config.

        Args:
            name: Check name
        """
        with self._lock:
            if name not in self._disabled_names:
                self._disabled_names.append(name)

    def on_check_not_applicable(self, name: str) -> None:
        """Called when a check is not applicable for this project type.

        Args:
            name: Check name
        """
        with self._lock:
            if name not in self._na_names:
                self._na_names.append(name)

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
        interleaving. Lines are truncated to terminal width using
        ANSI-aware truncation to prevent color code leaks.
        """
        if self.quiet or not self._is_tty:
            return

        with self._lock:
            # Don't draw anything until we have checks registered
            if not self._checks:
                return

            lines = self._build_display()
            term_width = get_terminal_width()

            # Move cursor up to overwrite previous output
            if self._lines_drawn > 0:
                sys.stdout.write(f"\033[{self._lines_drawn}A")  # Move up
                sys.stdout.write("\033[J")  # Clear from cursor to end

            # ANSI-aware truncation preserves escape codes and appends reset
            truncated = [truncate_to_width(line, term_width) for line in lines]

            output = "\n".join(truncated)
            sys.stdout.write(output + "\n")
            sys.stdout.flush()

            self._lines_drawn = len(truncated)

    def _build_display(self) -> List[str]:
        """Build the display lines, grouped by category.

        Returns:
            List of lines to display
        """
        lines: List[str] = []

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
            lines.append(
                build_overall_progress(
                    completed, total, elapsed, colors_enabled=self._colors_enabled
                )
            )
            lines.append("")

        # Group checks by category
        groups = self._group_checks_by_category()
        term_width = get_terminal_width()

        # Compute max short-name width across all checks for column alignment
        all_checks_flat = [c for _, _, gc in groups for c in gc]
        max_name_w = 0
        for c in all_checks_flat:
            sn = strip_category_prefix(c.name)
            max_name_w = max(max_name_w, len(sn))

        for category_key, category_label, group_checks in groups:
            cat_completed = sum(
                1 for c in group_checks if c.state == DisplayState.COMPLETED
            )
            cat_total = len(group_checks)
            header = build_category_header(
                category_label, cat_completed, cat_total, term_width
            )
            # Colorize the entire header line
            hdr_color = category_header_color(category_key, self._colors_enabled)
            rc = reset_color(self._colors_enabled)
            if hdr_color:
                header = f"{hdr_color}{header}{rc}"
            lines.append(header)

            # Sort within group: completed by order, then running, then pending
            group_checks.sort(
                key=lambda c: (
                    0 if c.state == DisplayState.COMPLETED else 1,
                    c.completion_order if c.state == DisplayState.COMPLETED else 0,
                    0 if c.expected_duration is not None else 1,
                    -(c.expected_duration or 0),
                    c.name,
                )
            )

            for info in group_checks:
                lines.append(self._format_check_line(info, name_width=max_name_w))

        # N/A summary (not applicable — no matching project type)
        if self._na_names:
            lines.append("")
            na_short = [strip_category_prefix(n) for n in self._na_names]
            lines.append(f"Not applicable: {', '.join(na_short)}")

        # Disabled summary (explicitly disabled in config)
        if self._disabled_names:
            lines.append("")
            disabled_short = [strip_category_prefix(n) for n in self._disabled_names]
            lines.append(f"Disabled: {', '.join(disabled_short)}")

        # Status summary - only when checks still running
        if running > 0:
            lines.append("")
            lines.append(f"🔄 {running} running · ✓ {completed} done")

        return lines

    def _group_checks_by_category(
        self,
    ) -> List[tuple[str, str, List[CheckDisplayInfo]]]:
        """Group checks by category in defined display order.

        Returns:
            List of (category_key, display_label, checks) tuples.
            Only categories with checks are included.
        """
        from collections import defaultdict

        # Bucket checks by category key
        buckets: dict[str, List[CheckDisplayInfo]] = defaultdict(list)
        for info in self._checks.values():
            cat = info.category or "unknown"
            buckets[cat].append(info)

        # Build category labels from GateCategory enum
        from slopmop.checks.base import GateCategory

        cat_labels = {cat.key: cat.display for cat in GateCategory}

        # Emit groups in defined order, skip empty categories
        groups: List[tuple[str, str, List[CheckDisplayInfo]]] = []
        seen: set[str] = set()
        for key in config.CATEGORY_ORDER:
            if key in buckets:
                label = cat_labels.get(key, key.title())
                groups.append((key, label, buckets[key]))
                seen.add(key)

        # Any categories not in CATEGORY_ORDER go at the end
        for key in sorted(buckets.keys()):
            if key not in seen:
                label = cat_labels.get(key, key.title())
                groups.append((key, label, buckets[key]))

        return groups

    def _format_completed_line(
        self, info: CheckDisplayInfo, width: int, name_width: int = 0
    ) -> str:
        """Format a completed check line.

        Args:
            info: Check display info (must be completed with result)
            width: Available width for the line
            name_width: Minimum name column width for alignment

        Returns:
            Formatted line
        """
        assert info.result is not None
        ce = self._colors_enabled

        short_name = strip_category_prefix(info.name)
        padded_name = f"{short_name:<{name_width}}" if name_width else short_name
        icon = STATUS_EMOJI.get(info.result.status, "❓")
        status_val = info.result.status.value
        padded_status = f"{status_val:<{config.STATUS_COLUMN_WIDTH}}"

        # Colorize status word
        sc = status_color(info.result.status, ce)
        rc = reset_color(ce)
        colored_status = f"{sc}{padded_status}{rc}"

        left = f"{config.CHECK_INDENT}{icon} {padded_name}: {colored_status}"

        # Inline failure preview for failed/error checks
        preview = ""
        if info.result.status in (CheckStatus.FAILED, CheckStatus.ERROR):
            preview_text = info.result.error or info.result.output
            if preview_text:
                preview = truncate_for_inline(preview_text, config.MAX_PREVIEW_WIDTH)
                if preview:
                    preview = f" — {preview}"

        time_str = format_time(info.duration)
        right = align_columns(time_str, "")
        return right_justify(left + preview, right, width)

    def _format_running_line(
        self, info: CheckDisplayInfo, width: int, name_width: int = 0
    ) -> str:
        """Format a running check line with spinner and progress.

        Args:
            info: Check display info (must be running)
            width: Available width for the line
            name_width: Minimum name column width for alignment

        Returns:
            Formatted line
        """
        # Use default spinner
        spinner = config.SPINNER_FRAMES[self._spinner_idx]

        elapsed = time.time() - info.start_time
        short_name = strip_category_prefix(info.name)
        padded_name = f"{short_name:<{name_width}}" if name_width else short_name
        left = f"{config.CHECK_INDENT}{spinner} {padded_name}"
        time_str = format_time(elapsed)

        if info.expected_duration and info.expected_duration > 0:
            remaining = max(0.0, info.expected_duration - elapsed)
            eta_str = format_time(remaining)
            pct = min(elapsed / info.expected_duration, 0.99)
            right = align_columns(time_str, eta_str)
            return build_progress_bar(
                left, right, width, pct, colors_enabled=self._colors_enabled
            )
        else:
            right = align_columns(time_str, "N/A")
            return build_dot_leader(left, right, width, self._animation_tick)

    def _format_pending_line(
        self, info: CheckDisplayInfo, width: int, name_width: int = 0
    ) -> str:
        """Format a pending check line.

        Args:
            info: Check display info (pending state)
            width: Available width for the line
            name_width: Minimum name column width for alignment

        Returns:
            Formatted line (without connector)
        """
        short_name = strip_category_prefix(info.name)
        padded_name = f"{short_name:<{name_width}}" if name_width else short_name
        left = f"{config.CHECK_INDENT}○ {padded_name}"
        eta_str = (
            format_time(info.expected_duration) if info.expected_duration else "N/A"
        )
        right = align_columns("", eta_str)
        return right_justify(left, right, width)

    def _format_check_line(self, info: CheckDisplayInfo, name_width: int = 0) -> str:
        """Format a single check line with aligned columns.

        Dispatches to state-specific formatters based on check state.

        Args:
            info: Check display info
            name_width: Minimum name column width for alignment

        Returns:
            Formatted line string
        """
        width = get_terminal_width()

        if info.state == DisplayState.COMPLETED and info.result:
            return self._format_completed_line(info, width, name_width)
        elif info.state == DisplayState.RUNNING:
            return self._format_running_line(info, width, name_width)
        else:
            return self._format_pending_line(info, width, name_width)

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
        return build_overall_progress(
            completed, total, elapsed, colors_enabled=self._colors_enabled
        )

    def _right_justify(self, left: str, right: str) -> str:
        """Right-justify a line. (Backwards compatibility)"""
        return right_justify(left, right)

    def _align_columns(self, time_str: str, eta_str: str) -> str:
        """Right-align the time and ETA. (Backwards compatibility)"""
        return align_columns(time_str, eta_str)
