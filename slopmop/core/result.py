"""Core result types for quality gate checks.

This module defines the fundamental data structures used throughout slopmop
to represent check definitions, statuses, and results.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, cast


class CheckStatus(Enum):
    """Status of a quality gate check."""

    PASSED = "passed"
    FAILED = "failed"
    WARNED = "warned"
    SKIPPED = "skipped"
    NOT_APPLICABLE = "not_applicable"
    ERROR = "error"

    def __str__(self) -> str:
        return self.value


@dataclass
class ScopeInfo:
    """Scope metrics for a quality gate check.

    Tracks the number of files and lines of code examined by a check,
    giving users visibility into what each gate actually scanned.

    Attributes:
        files: Number of source files examined
        lines: Total lines of code across those files
    """

    files: int = 0
    lines: int = 0

    def __add__(self, other: "ScopeInfo") -> "ScopeInfo":
        return ScopeInfo(self.files + other.files, self.lines + other.lines)

    def format_compact(self) -> str:
        """Format scope as a compact string like '47 files · 3.2k LOC'."""
        parts: List[str] = []
        if self.files > 0:
            parts.append(f"{self.files} files")
        if self.lines > 0:
            if self.lines >= 10_000:
                parts.append(f"{self.lines / 1000:.1f}k LOC")
            else:
                parts.append(f"{self.lines:,} LOC")
        return " · ".join(parts)


@dataclass
class CheckResult:
    """Result of executing a quality gate check.

    Attributes:
        name: Unique identifier for the check
        status: Pass/fail/skip/error status
        duration: Execution time in seconds
        output: Captured stdout/stderr from the check
        error: Error message if status is ERROR or FAILED
        fix_suggestion: Actionable suggestion for fixing failures
        auto_fixed: Whether issues were automatically fixed
        category: Category key for grouping (python, quality, security, etc.)
        scope: Scope metrics (files/LOC examined), if available
    """

    name: str
    status: CheckStatus
    duration: float
    output: str = ""
    error: Optional[str] = None
    fix_suggestion: Optional[str] = None
    auto_fixed: bool = False
    category: Optional[str] = None
    scope: Optional[ScopeInfo] = None

    @property
    def passed(self) -> bool:
        """Return True if check passed."""
        return self.status == CheckStatus.PASSED

    @property
    def failed(self) -> bool:
        """Return True if check failed."""
        return self.status == CheckStatus.FAILED

    def __str__(self) -> str:
        emoji = {
            CheckStatus.PASSED: "✅",
            CheckStatus.FAILED: "❌",
            CheckStatus.WARNED: "⚠️",
            CheckStatus.SKIPPED: "⏭️",
            CheckStatus.NOT_APPLICABLE: "⊘",
            CheckStatus.ERROR: "💥",
        }.get(self.status, "❓")
        return f"{emoji} {self.name}: {self.status.value} ({self.duration:.2f}s)"


@dataclass
class CheckDefinition:
    """Definition of a quality gate check.

    Attributes:
        flag: Command-line flag for this check (e.g., "python-lint-format")
        name: Human-readable display name with emoji
        runner: Optional custom runner function
        depends_on: List of check flags this check depends on
        auto_fix: Whether this check can auto-fix issues
    """

    flag: str
    name: str
    runner: Optional[Callable[[], CheckResult]] = None
    depends_on: List[str] = field(default_factory=lambda: cast(List[str], []))
    auto_fix: bool = False

    def __hash__(self) -> int:
        return hash(self.flag)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, CheckDefinition):
            return self.flag == other.flag
        return False


@dataclass
class ExecutionSummary:
    """Summary of a quality gate execution run.

    Attributes:
        total_checks: Total number of checks executed
        passed: Number of checks that passed
        failed: Number of checks that failed
        skipped: Number of checks that were skipped
        errors: Number of checks that had errors
        total_duration: Total execution time in seconds
        results: List of individual check results
    """

    total_checks: int
    passed: int
    failed: int
    warned: int
    skipped: int
    not_applicable: int
    errors: int
    total_duration: float
    results: List[CheckResult] = field(
        default_factory=lambda: cast(List[CheckResult], [])
    )

    @property
    def all_passed(self) -> bool:
        """Return True if all checks passed (no failures or errors)."""
        return self.failed == 0 and self.errors == 0

    def scope_by_category(self) -> Dict[str, ScopeInfo]:
        """Aggregate scope info by category, taking max per category.

        When multiple checks in the same category report scope, we take
        the maximum files/lines since they typically scan overlapping sets.

        Returns:
            Dict mapping category key to aggregated ScopeInfo
        """
        by_cat: Dict[str, ScopeInfo] = {}
        for r in self.results:
            if r.scope and r.category:
                existing = by_cat.get(r.category)
                if existing is None:
                    by_cat[r.category] = ScopeInfo(
                        files=r.scope.files, lines=r.scope.lines
                    )
                else:
                    # Take the max — checks in same category scan overlapping files
                    by_cat[r.category] = ScopeInfo(
                        files=max(existing.files, r.scope.files),
                        lines=max(existing.lines, r.scope.lines),
                    )
        return by_cat

    def total_scope(self) -> Optional[ScopeInfo]:
        """Get overall scope across all categories.

        Takes the max files/lines across categories to avoid
        double-counting overlapping scans.

        Returns:
            Aggregate ScopeInfo, or None if no checks reported scope
        """
        by_cat = self.scope_by_category()
        if not by_cat:
            return None
        return ScopeInfo(
            files=max(s.files for s in by_cat.values()),
            lines=max(s.lines for s in by_cat.values()),
        )

    @classmethod
    def from_results(
        cls, results: List[CheckResult], duration: float
    ) -> "ExecutionSummary":
        """Create summary from a list of check results."""
        return cls(
            total_checks=len(results),
            passed=sum(1 for r in results if r.status == CheckStatus.PASSED),
            failed=sum(1 for r in results if r.status == CheckStatus.FAILED),
            warned=sum(1 for r in results if r.status == CheckStatus.WARNED),
            skipped=sum(1 for r in results if r.status == CheckStatus.SKIPPED),
            not_applicable=sum(
                1 for r in results if r.status == CheckStatus.NOT_APPLICABLE
            ),
            errors=sum(1 for r in results if r.status == CheckStatus.ERROR),
            total_duration=duration,
            results=results,
        )
