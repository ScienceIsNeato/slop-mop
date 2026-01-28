"""
Result types — Check outcomes and terminal-optimized formatting.

Designed for maximum signal-to-noise ratio. AI agents reading this output
should be able to identify and fix issues without re-running commands.
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class CheckStatus(Enum):
    """Outcome of a quality check."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"  # Check itself errored (not a validation failure)


@dataclass
class CheckResult:
    """Outcome of a single quality check."""

    name: str
    status: CheckStatus
    duration_secs: float = 0.0
    output: str = ""
    fix_hint: str = ""
    details: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == CheckStatus.PASSED

    @property
    def failed(self) -> bool:
        return self.status in (CheckStatus.FAILED, CheckStatus.ERROR)

    def format_brief(self) -> str:
        """One-line summary for the results table."""
        icon = {
            CheckStatus.PASSED: "  ",
            CheckStatus.FAILED: "  ",
            CheckStatus.SKIPPED: "  ",
            CheckStatus.ERROR: "  ",
        }[self.status]
        label = {
            CheckStatus.PASSED: "PASS",
            CheckStatus.FAILED: "FAIL",
            CheckStatus.SKIPPED: "SKIP",
            CheckStatus.ERROR: "ERR ",
        }[self.status]
        return f"  [{icon} {label}] {self.name:<35} ({self.duration_secs:.1f}s)"

    def format_failure_detail(self) -> str:
        """Expanded detail block for failures — what an agent needs to see."""
        lines = [
            "",
            f"  {'─' * 70}",
            f"  FAILED: {self.name}",
            f"  {'─' * 70}",
        ]

        if self.output:
            # Show last 30 lines of output (most relevant part)
            output_lines = self.output.strip().splitlines()
            if len(output_lines) > 30:
                lines.append(f"  ... ({len(output_lines) - 30} lines omitted) ...")
                output_lines = output_lines[-30:]
            for line in output_lines:
                lines.append(f"    {line}")

        if self.fix_hint:
            lines.append("")
            lines.append(f"  FIX: {self.fix_hint}")

        return "\n".join(lines)


@dataclass
class RunSummary:
    """Aggregated results from a full validation run."""

    results: List[CheckResult] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    profile_name: str = ""

    @property
    def total_duration(self) -> float:
        end = self.end_time or time.time()
        return end - self.start_time

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.status == CheckStatus.PASSED)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.failed)

    @property
    def skip_count(self) -> int:
        return sum(1 for r in self.results if r.status == CheckStatus.SKIPPED)

    @property
    def all_passed(self) -> bool:
        return self.fail_count == 0

    def format_summary(self) -> str:
        """Terminal-optimized summary report."""
        lines = []

        # Header
        lines.append("")
        lines.append(f"  {'═' * 70}")
        profile_label = f" [{self.profile_name}]" if self.profile_name else ""
        lines.append(f"  SLOPBUCKET VALIDATION RESULTS{profile_label}")
        lines.append(f"  {'═' * 70}")

        # Results table
        lines.append("")
        for result in sorted(
            self.results, key=lambda r: (r.status != CheckStatus.FAILED, r.name)
        ):
            lines.append(result.format_brief())

        # Failure details (most actionable info first)
        failures = [r for r in self.results if r.failed]
        if failures:
            lines.append("")
            lines.append(f"  {'─' * 70}")
            lines.append("  FAILURE DETAILS")
            lines.append(f"  {'─' * 70}")
            for result in failures:
                lines.append(result.format_failure_detail())

        # Footer
        lines.append("")
        lines.append(f"  {'─' * 70}")
        status_word = "ALL CHECKS PASSED" if self.all_passed else "VALIDATION FAILED"
        lines.append(
            f"  {status_word} | "
            f"{self.pass_count} passed, {self.fail_count} failed, "
            f"{self.skip_count} skipped | "
            f"{self.total_duration:.1f}s total"
        )
        lines.append(f"  {'═' * 70}")
        lines.append("")

        return "\n".join(lines)
