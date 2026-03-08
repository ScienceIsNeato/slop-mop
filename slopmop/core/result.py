"""Core result types for quality gate checks.

This module defines the fundamental data structures used throughout slopmop
to represent check definitions, statuses, and results.
"""

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, cast


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


class SkipReason(Enum):
    """Why a check was skipped or excluded from a run.

    Each value is the short code displayed in the summary footer,
    e.g. ``3 skipped (ff)``.

    Set on :pyclass:`CheckResult` via the ``skip_reason`` field whenever
    the status is SKIPPED or NOT_APPLICABLE.
    """

    FAIL_FAST = "ff"  # Stopped after an earlier failure
    FAILED_DEPENDENCY = "dep"  # A prerequisite check failed
    NOT_APPLICABLE = "n/a"  # Check doesn't apply (e.g. no Python files)
    DISABLED = "off"  # Turned off in .sb_config.json
    TIME_BUDGET = "time"  # Would exceed --swabbing-time budget
    SUPERSEDED = "sup"  # Replaced by a more thorough check in this run

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

    def to_dict(self) -> Dict[str, int]:
        """Serialize to a plain dict for JSON output."""
        return {"files": self.files, "lines": self.lines}

    def __add__(self, other: "ScopeInfo") -> "ScopeInfo":
        return ScopeInfo(self.files + other.files, self.lines + other.lines)

    def format_files_compact(self) -> str:
        """Format file count compactly: '104' or '1.2k'."""
        if self.files >= 10_000:
            return f"{self.files / 1000:.1f}k"
        return str(self.files) if self.files > 0 else ""

    def format_loc_compact(self) -> str:
        """Format LOC compactly: '33.4k' or '3,200'."""
        if self.lines >= 10_000:
            return f"{self.lines / 1000:.1f}k"
        if self.lines > 0:
            return f"{self.lines:,}"
        return ""

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


class FindingLevel(Enum):
    """Severity level for a single finding — maps directly to SARIF ``result.level``.

    Distinct from :class:`CheckStatus`: a gate FAILS or PASSES as a whole,
    but individual findings inside that gate carry their own severity.  A
    gate can FAIL because it found five warnings that exceeded a
    ``max_warnings: 0`` threshold — those are still WARNING-level findings
    in SARIF, and GitHub renders them with yellow badges, not red.

    SARIF consumers (GitHub Code Scanning, IDE extensions) use THIS level
    to decide annotation colour.  They don't see the gate's pass/fail.
    """

    ERROR = "error"
    WARNING = "warning"
    NOTE = "note"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Finding:
    """A single structured issue discovered by a check.

    Carries the minimum data needed to produce a SARIF ``result`` object
    with a ``physicalLocation``.  All location fields are optional: some
    gates are aggregate (coverage %, complexity score) and have no file
    anchor — SARIF permits location-less results and GitHub renders them
    under the rule name in the Security tab.

    Gates are NOT required to emit findings.  The free-form
    :attr:`CheckResult.output` remains the baseline for console display.
    Findings are an additive layer for gates that HAVE file:line data —
    when populated, the SARIF reporter emits one ``result`` per finding.

    The design deliberately keeps gate identity OUT of this type.  A
    Finding doesn't know which gate produced it; that's carried by the
    enclosing :class:`CheckResult`.  This keeps construction sites clean
    (no redundant ``gate_name=self.full_name`` at every call) and lets
    the SARIF reporter compose ``ruleId`` from both pieces at emission
    time, where it has the full picture.

    Attributes:
        message: Human-readable description.  First sentence should be
            the TL;DR — GitHub truncates to the first sentence when
            space is limited.  Maps to SARIF ``result.message.text``.
        level: Severity of THIS finding.  Defaults to ERROR because the
            common case is building findings in a failure path.
        file: Path relative to project root, POSIX separators.  ``None``
            for location-less aggregate findings.  Gates should pass
            relative paths; the reporter normalises to POSIX and
            percent-encodes.  Maps to SARIF ``artifactLocation.uri``.
        line: 1-based start line.  Maps to SARIF ``region.startLine``.
            Without this, GitHub won't render an inline PR annotation.
        column: 1-based start column.  SARIF is strict: the schema
            rejects ``startColumn: 0``.  If you have a 0-based column
            from a tool, add 1 before passing it here.
        end_line: 1-based end line for multi-line ranges.
        end_column: 1-based exclusive end column (one past the last
            character of the range).
        rule_id: Tool-native sub-rule identifier, e.g. ``"F401"``
            (flake8), ``"reportUnknownVariableType"`` (pyright),
            ``"no-unused-vars"`` (eslint).  Distinct from the gate's
            own name — one gate wraps many rules.  ``None`` when the
            gate has a single rule; the SARIF reporter then uses the
            gate's ``full_name`` as the ruleId.
        fix_strategy: Specific, actionable remediation instruction —
            what the agent should *actually do* to resolve THIS finding.
            Distinct from :attr:`CheckResult.fix_suggestion`, which is
            gate-level guidance; this is per-finding.  The contract:
            an agent reading ``fix_strategy`` should be able to produce
            a fix without further analysis.  ``None`` when the gate
            cannot determine a specific fix — better to say nothing
            than guess.  Examples:
            ``"Replace yaml.load(data) with yaml.safe_load(data)"``,
            ``"Move PythonCheckMixin (273 lines, starts line 619) to "
            "its own file"``.
    """

    message: str
    level: FindingLevel = FindingLevel.ERROR
    file: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    end_line: Optional[int] = None
    end_column: Optional[int] = None
    rule_id: Optional[str] = None
    fix_strategy: Optional[str] = None

    def __str__(self) -> str:
        """Human-readable ``file:line:col: message`` format.

        Used by the auto-output rail in ``_create_result`` to synthesise
        console output from structured findings when a gate didn't supply
        free-form text.  When ``fix_strategy`` is set, renders as a
        second indented line so the instruction is visually distinct
        from the diagnosis.
        """
        loc = ""
        if self.file:
            loc = self.file
            if self.line is not None:
                loc += f":{self.line}"
                if self.column is not None:
                    loc += f":{self.column}"
            loc += ": "
        base = f"{loc}{self.message}"
        if self.fix_strategy:
            return f"{base}\n  → fix: {self.fix_strategy}"
        return base

    def to_dict(self) -> Dict[str, object]:
        """Serialise for JSON output.  Omits ``None`` fields — matches
        the token-saving convention used throughout this module.
        """
        d: Dict[str, object] = {
            "message": self.message,
            "level": self.level.value,
        }
        if self.file is not None:
            d["file"] = self.file
        if self.line is not None:
            d["line"] = self.line
        if self.column is not None:
            d["column"] = self.column
        if self.end_line is not None:
            d["end_line"] = self.end_line
        if self.end_column is not None:
            d["end_column"] = self.end_column
        if self.rule_id is not None:
            d["rule_id"] = self.rule_id
        if self.fix_strategy is not None:
            d["fix_strategy"] = self.fix_strategy
        return d


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
        findings: Structured per-issue findings for SARIF / IDE
            annotations.  Empty by default — gates that only produce
            free-form ``output`` need zero changes.  When populated,
            the SARIF reporter emits one ``result`` per finding; the
            console reporter ignores this and uses ``output`` as before.
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
    skip_reason: Optional["SkipReason"] = None
    status_detail: Optional[str] = None
    role: Optional[str] = None
    findings: List[Finding] = field(default_factory=lambda: cast(List[Finding], []))
    cached: bool = False
    cache_timestamp: Optional[str] = (
        None  # ISO 8601 when result was originally produced
    )
    cache_commit: Optional[str] = None  # Short commit hash when result was produced

    def to_dict(self) -> Dict[str, object]:
        """Serialize to a plain dict for JSON output."""
        d: Dict[str, object] = {
            "name": self.name,
            "status": self.status.value,
            "duration": round(self.duration, 3),
        }
        if self.output:
            d["output"] = self.output
        if self.error:
            d["error"] = self.error
        if self.fix_suggestion:
            d["fix_suggestion"] = self.fix_suggestion
        if self.auto_fixed:
            d["auto_fixed"] = True
        if self.category:
            d["category"] = self.category
        if self.scope:
            d["scope"] = self.scope.to_dict()
        if self.skip_reason:
            d["skip_reason"] = self.skip_reason.value
        if self.status_detail:
            d["status_detail"] = self.status_detail
        if self.role:
            d["role"] = self.role
        if self.findings:
            d["findings"] = [f.to_dict() for f in self.findings]
        if self.cached:
            d["cached"] = True
        if self.cache_timestamp:
            d["cache_timestamp"] = self.cache_timestamp
        if self.cache_commit:
            d["cache_commit"] = self.cache_commit
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CheckResult":
        """Deserialize from a plain dict (inverse of to_dict)."""
        findings: List[Finding] = []
        raw_findings = d.get("findings")
        if isinstance(raw_findings, list):
            findings_list = cast(List[object], raw_findings)
            for fd_raw in findings_list:
                if isinstance(fd_raw, dict):
                    fd: Dict[str, Any] = cast(Dict[str, Any], fd_raw)
                    level = FindingLevel.ERROR
                    raw_level: object = fd.get("level")
                    if isinstance(raw_level, str):
                        try:
                            level = FindingLevel(raw_level)
                        except ValueError:
                            pass
                    _file = fd.get("file")
                    _line = fd.get("line")
                    _col = fd.get("column")
                    _end_line = fd.get("end_line")
                    _end_col = fd.get("end_column")
                    _rule = fd.get("rule_id")
                    _fix = fd.get("fix_strategy")
                    findings.append(
                        Finding(
                            message=str(fd.get("message", "")),
                            level=level,
                            file=str(_file) if _file is not None else None,
                            line=(
                                int(_line) if isinstance(_line, (int, float)) else None
                            ),
                            column=(
                                int(_col) if isinstance(_col, (int, float)) else None
                            ),
                            end_line=(
                                int(_end_line)
                                if isinstance(_end_line, (int, float))
                                else None
                            ),
                            end_column=(
                                int(_end_col)
                                if isinstance(_end_col, (int, float))
                                else None
                            ),
                            rule_id=str(_rule) if _rule is not None else None,
                            fix_strategy=str(_fix) if _fix is not None else None,
                        )
                    )

        scope = None
        raw_scope = d.get("scope")
        if isinstance(raw_scope, dict):
            scope_dict: Dict[str, Any] = cast(Dict[str, Any], raw_scope)
            raw_files = scope_dict.get("files", 0)
            raw_lines = scope_dict.get("lines", 0)
            scope = ScopeInfo(
                files=int(raw_files) if isinstance(raw_files, (int, float)) else 0,
                lines=int(raw_lines) if isinstance(raw_lines, (int, float)) else 0,
            )

        skip_reason = None
        raw_skip = d.get("skip_reason")
        if isinstance(raw_skip, str):
            try:
                skip_reason = SkipReason(raw_skip)
            except ValueError:
                pass

        status = CheckStatus.PASSED
        raw_status = d.get("status")
        if isinstance(raw_status, str):
            try:
                status = CheckStatus(raw_status)
            except ValueError:
                pass

        return cls(
            name=str(d.get("name", "")),
            status=status,
            duration=float(d.get("duration", 0)),  # type: ignore[arg-type]
            output=str(d.get("output", "")),
            error=d.get("error"),  # type: ignore[arg-type]
            fix_suggestion=d.get("fix_suggestion"),  # type: ignore[arg-type]
            auto_fixed=bool(d.get("auto_fixed", False)),
            category=d.get("category"),  # type: ignore[arg-type]
            scope=scope,
            skip_reason=skip_reason,
            status_detail=d.get("status_detail"),  # type: ignore[arg-type]
            role=d.get("role"),  # type: ignore[arg-type]
            findings=findings,
            cached=bool(d.get("cached", False)),
            cache_timestamp=d.get("cache_timestamp"),  # type: ignore[arg-type]
            cache_commit=d.get("cache_commit"),  # type: ignore[arg-type]
        )

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

    def skip_reason_summary(self) -> Dict[str, int]:
        """Count checks by skip reason.

        Returns:
            Dict mapping reason code to count, e.g.
            {"n/a": 8, "time": 3}
        """
        counts: Counter[str] = Counter()
        for r in self.results:
            if r.status in (CheckStatus.SKIPPED, CheckStatus.NOT_APPLICABLE):
                label = r.skip_reason.value if r.skip_reason else "skipped"
                counts[label] += 1
        return dict(counts)

    def to_dict(self) -> Dict[str, object]:
        """Serialize to a compact dict optimised for LLM consumption.

        Token-saving measures:
        * Passing checks are collapsed to a name list (``passed_gates``)
          instead of full result objects — an LLM only needs to know they
          passed.
        * Only non-passing results carry full detail (output, errors, etc.).
        * Null / empty optional summary fields (``scope``, ``skip_reasons``)
          are omitted rather than serialised as ``null``.
        """
        scope = self.total_scope()
        skip_reasons = self.skip_reason_summary()

        summary: Dict[str, object] = {
            "total_checks": self.total_checks,
            "passed": self.passed,
            "failed": self.failed,
            "warned": self.warned,
            "skipped": self.skipped,
            "not_applicable": self.not_applicable,
            "errors": self.errors,
            "all_passed": self.all_passed,
            "total_duration": round(self.total_duration, 3),
        }
        if scope:
            summary["scope"] = scope.to_dict()
        if skip_reasons:
            summary["skip_reasons"] = skip_reasons

        # Collapse passing checks to just names.
        # Only include actionable results (failed / warned / error).
        # Skipped and n/a results carry no actionable info for an
        # LLM agent — the summary counts + skip_reasons dict are
        # sufficient.
        passed_names = [r.name for r in self.results if r.status == CheckStatus.PASSED]
        actionable = [
            r.to_dict()
            for r in self.results
            if r.status
            in (
                CheckStatus.FAILED,
                CheckStatus.WARNED,
                CheckStatus.ERROR,
            )
        ]

        out: Dict[str, object] = {"summary": summary}
        if passed_names:
            out["passed_gates"] = passed_names
        if actionable:
            out["results"] = actionable
        return out

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
