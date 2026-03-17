"""RunReport — the canonical enriched representation of a validation run.

The output pipeline (console, JSON, SARIF) previously built its own view
of the same ``ExecutionSummary`` independently.  Each path duplicated
enrichment logic (log file paths, next-step hints, failure categorisation)
and silently diverged over time.

``RunReport`` sits between ``ExecutionSummary`` and the output adapters.
It derives everything any adapter needs *once*, in one place, from the
same source of truth.  Adapters then format that derived state without
recomputing it.

Division of labour:

- ``RunReport`` computes **business-logic** derivations: which checks
  failed, what the re-run command is, where the log files live, how
  results group by role.  Adapters do not rediscover these.
- Adapters compute **format-specific** derivations: SARIF fingerprints,
  console colouring, JSON key ordering.  ``RunReport`` does not know or
  care about output format.
- Log file writing is a side effect owned by ``RunReport.write_logs()``.
  Calling it populates :attr:`log_files`.  Adapters read the mapping;
  none of them perform I/O.

This keeps adapters pure-transform functions of ``RunReport``, which
makes them trivially testable and lets new formats (JUnit XML, GitHub
Actions annotations) slot in without touching enrichment logic.
"""

import os
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, List, Optional

from slopmop.core.result import CheckResult, CheckStatus, ExecutionSummary

if TYPE_CHECKING:
    from slopmop.core.registry import CheckRegistry


def _format_age(iso_timestamp: str) -> Optional[str]:
    """Human-readable relative age from an ISO-8601 timestamp.

    Returns e.g. '2m', '1h', '3d', or None on parse failure.
    """
    then = _parse_iso_timestamp(iso_timestamp)
    if then is None:
        return None
    delta = datetime.now(timezone.utc) - then
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


def _parse_iso_timestamp(iso_timestamp: str) -> Optional[datetime]:
    """Parse ISO-8601 timestamps into timezone-aware datetimes."""
    try:
        then = datetime.fromisoformat(iso_timestamp)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return then
    except (ValueError, TypeError):
        return None


def _unique_non_empty(values: List[Optional[str]]) -> List[str]:
    """Return unique non-empty strings while preserving order."""
    seen: set[str] = set()
    unique: List[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _no_results() -> List[CheckResult]:
    """Typed default-factory for pyright strict mode.

    ``field(default_factory=list)`` infers ``list[Unknown]`` under strict
    pyright — the bare builtin has no element type.  A named factory with
    an explicit return annotation satisfies the checker without suppressing
    anything.
    """
    return []


def _no_logs() -> Dict[str, str]:
    """Same typed-factory fix as _no_results, for the log_files dict.

    ``dict[str, str]`` as a factory happens to work on 3.14 (GenericAlias
    gained __call__) but raises ``TypeError: 'types.GenericAlias' object
    is not callable`` on 3.9–3.11.  An explicit factory is correct
    everywhere and symmetric with the list-field fix.
    """
    return {}


def _sort_results_for_remediation_display(
    results: List[CheckResult],
    registry: "CheckRegistry",
) -> List[CheckResult]:
    """Sort display rows by remediation order while preserving unknown-name order."""
    indexed = list(enumerate(results))
    return [
        result
        for _index, result in sorted(
            indexed,
            key=lambda item: (
                registry.remediation_sort_key_for_name(item[1].name)
                or (999_999, 999_999, f"{item[0]:06d}"),
                item[0],
            ),
        )
    ]


# Single source of truth for the JSON schema identifier.  Bump when
# output shape changes (new required fields, removed fields, renamed
# keys).  Additive-only changes (new optional fields) are a judgement
# call — v2 was bumped for the introduction of ``role`` and
# ``fix_strategy`` to signal "look at the changelog, there's new
# structure here" even though v1 consumers would not break.
JSON_SCHEMA_VERSION = "slopmop/v2"


def _structured_console_lines(
    result: CheckResult,
    *,
    details_path: Optional[str],
    verify_command: str,
    max_findings: int,
    max_instructions: int,
) -> List[str]:
    """Return compact structured guidance lines for console output."""
    findings = result.findings[:max_findings]
    lines: List[str] = ["   WHAT'S BROKEN:"]
    for finding in findings:
        location = finding.file or "(location unknown)"
        if finding.file and finding.line is not None:
            location = f"{finding.file}:{finding.line}"
        lines.append(f"     {location} — {finding.message}")
    if len(result.findings) > len(findings):
        lines.append(f"     ... and {len(result.findings) - len(findings)} more")

    if result.why_it_matters:
        lines.append("   WHY IT MATTERS:")
        for wrapped in textwrap.wrap(result.why_it_matters, width=66):
            lines.append(f"     {wrapped}")

    instructions = [f.fix_strategy for f in findings if f.fix_strategy]
    if not instructions and result.fix_suggestion:
        instructions = [result.fix_suggestion]
    if instructions:
        lines.append("   EXACTLY WHAT TO DO:")
        for index, instruction in enumerate(instructions[:max_instructions], start=1):
            lines.append(f"     {index}. {instruction}")

    if details_path:
        lines.append(f"   FULL DETAILS: {details_path}")
    lines.append(f"   AFTER FIXING: {verify_command}")
    return lines


@dataclass
class RunReport:
    """Canonical enriched view of a validation run.

    All derived state that more than one output format needs lives here.
    Construct via :meth:`from_summary` — direct field assignment is
    possible but bypasses the derivation logic.
    """

    summary: ExecutionSummary
    level: Optional[str]
    project_root: Optional[str]
    verbose: bool = False
    schema_version: str = JSON_SCHEMA_VERSION

    # --- Derived categorisations ------------------------------------
    # Filled by from_summary().  Each list is stable-ordered (same as
    # summary.results) so adapters can rely on ordering for display.
    passed: List[CheckResult] = field(default_factory=_no_results)
    failed: List[CheckResult] = field(default_factory=_no_results)
    warned: List[CheckResult] = field(default_factory=_no_results)
    errored: List[CheckResult] = field(default_factory=_no_results)
    skipped: List[CheckResult] = field(default_factory=_no_results)
    # NOT_APPLICABLE is distinct from SKIPPED — "this gate doesn't
    # apply to your project" (all JS gates on a Python-only repo) vs
    # "this was supposed to run but something blocked it" (fail-fast,
    # missing dep).  The console adapter displays operational skips in
    # the failure summary; inflating that count with n/a gates adds
    # noise.  ExecutionSummary already tracks the split in its counts.
    not_applicable: List[CheckResult] = field(default_factory=_no_results)

    # --- Log file mapping -------------------------------------------
    # gate_name → relative path.  Populated by write_logs().  Adapters
    # that don't need log files (SARIF) simply ignore this.
    log_files: Dict[str, str] = field(default_factory=_no_logs)

    # --- Agent guidance ---------------------------------------------
    # The verify command is the single command an agent should run to
    # re-check the first failure after attempting a fix.  Distinct
    # from per-gate fix_suggestion — this is "how to confirm you fixed
    # it", not "how to fix it".  None when everything passed.
    verify_command: Optional[str] = None
    first_to_fix: Optional[str] = None
    baseline_filter: Optional[Dict[str, object]] = None

    @classmethod
    def from_summary(
        cls,
        summary: ExecutionSummary,
        *,
        level: Optional[str] = None,
        project_root: Optional[str] = None,
        registry: Optional["CheckRegistry"] = None,
        sort_actionable_by_remediation_order: bool = False,
        verbose: bool = False,
    ) -> "RunReport":
        """Build a RunReport from a raw ExecutionSummary.

        Derives all categorisations and guidance fields in one pass.
        Log file writing is NOT done here — call :meth:`write_logs`
        separately when the adapter chain needs file paths.  This
        separation keeps ``from_summary`` pure and side-effect-free,
        which matters for tests.
        """
        # One-pass categorisation.  Same buckets every adapter wants;
        # computing them once here means adapters never re-scan
        # summary.results to find "the failed ones".
        status_buckets: Dict[CheckStatus, List[CheckResult]] = {
            CheckStatus.PASSED: [],
            CheckStatus.FAILED: [],
            CheckStatus.WARNED: [],
            CheckStatus.ERROR: [],
            CheckStatus.SKIPPED: [],
            CheckStatus.NOT_APPLICABLE: [],
        }
        for r in summary.results:
            status_buckets.setdefault(r.status, []).append(r)

        failed = status_buckets[CheckStatus.FAILED]
        warned = status_buckets[CheckStatus.WARNED]
        errored = status_buckets[CheckStatus.ERROR]

        if sort_actionable_by_remediation_order and registry is not None:
            failed = _sort_results_for_remediation_display(failed, registry)
            warned = _sort_results_for_remediation_display(warned, registry)
            errored = _sort_results_for_remediation_display(errored, registry)

        # Verify command targets the first blocking result.  "First"
        # follows the surfaced failure order. When remediation ordering
        # is enabled for display, this keeps the verify hint aligned with
        # the first gate users are told to fix.
        first_blocking = failed[0] if failed else (errored[0] if errored else None)
        verify = None
        if first_blocking is not None:
            verb = level or "swab"
            verify = f"sm {verb} -g {first_blocking.name}"

        return cls(
            summary=summary,
            level=level,
            project_root=project_root,
            verbose=verbose,
            passed=status_buckets[CheckStatus.PASSED],
            failed=failed,
            warned=warned,
            errored=errored,
            skipped=status_buckets[CheckStatus.SKIPPED],
            not_applicable=status_buckets[CheckStatus.NOT_APPLICABLE],
            verify_command=verify,
            first_to_fix=first_blocking.name if first_blocking is not None else None,
        )

    def per_gate_verify_command(self, gate_name: str) -> str:
        """Return the canonical rerun command for one gate."""
        return f"sm {self.level or 'swab'} -g {gate_name}"

    def per_gate_log_file(self, gate_name: str) -> Optional[str]:
        """Return the persisted log path for one gate, if available."""
        return self.log_files.get(gate_name)

    def console_detail_lines(self, result: CheckResult) -> List[str]:
        """Return compact, console-ready detail lines for one actionable result."""
        if result.why_it_matters and result.findings:
            return _structured_console_lines(
                result,
                details_path=self.per_gate_log_file(result.name),
                verify_command=self.per_gate_verify_command(result.name),
                max_findings=5 if self.verbose else 3,
                max_instructions=5 if self.verbose else 3,
            )
        return self._output_preview_lines(result)

    def _output_preview_lines(self, result: CheckResult) -> List[str]:
        """Return a short preview of raw gate output for console rendering."""
        if not result.output:
            return []

        all_lines = result.output.strip().splitlines()
        filtered = [line for line in all_lines if "✅" not in line and line.strip()]
        lines = filtered or [line for line in all_lines if line.strip()]
        if not lines:
            return []

        limit = 10 if self.verbose else 3
        preview = [f"   {line}" for line in lines[:limit]]
        if len(lines) > limit:
            hidden = len(lines) - limit
            if self.log_files.get(result.name):
                preview.append(f"   ... ({hidden} more lines in log)")
            else:
                preview.append(f"   ... ({hidden} more lines)")
        return preview

    def write_logs(self) -> Dict[str, str]:
        """Write per-gate log files for actionable checks.

        Populates and returns :attr:`log_files`.  Idempotent — calling
        twice overwrites the same files with the same content.  No-op
        when ``project_root`` is unset (tests, dry-runs).

        Returns the same dict stored on ``self.log_files`` so callers
        can chain: ``paths = report.write_logs()``.
        """
        if not self.project_root:
            return self.log_files

        log_dir = os.path.join(self.project_root, ".slopmop", "logs")
        os.makedirs(log_dir, exist_ok=True)

        for result in self.actionable:
            # Gate names use "category:check-name" format. Replacing ":"
            # with "_" is safe because no two registered gates would
            # produce the same sanitized filename.
            safe_name = result.name.replace(":", "_").replace("/", "_")
            log_path = os.path.join(log_dir, f"{safe_name}.log")
            with open(log_path, "w") as f:
                f.write(f"Check: {result.name}\n")
                f.write(f"Status: {result.status.value}\n")
                f.write(f"Duration: {result.duration:.2f}s\n")
                if result.error:
                    f.write(f"Error: {result.error}\n")
                if result.fix_suggestion:
                    f.write(f"Fix: {result.fix_suggestion}\n")
                f.write("\n--- Output ---\n")
                f.write(result.output or "(no output)")
                f.write("\n")
            self.log_files[result.name] = f".slopmop/logs/{safe_name}.log"

        return self.log_files

    @property
    def actionable(self) -> List[CheckResult]:
        """Results that need agent attention: failed + warned + errored.

        Same filter applied by ``ExecutionSummary.to_dict()`` for its
        ``results`` key.  Exposed here so the JSON adapter and console
        adapter share one definition of "things the agent should see".
        """
        return self.failed + self.warned + self.errored

    def role_counts(self) -> Dict[str, int]:
        """Count passed checks by role.

        Answers "how much of the foundation is green vs how many
        diagnostic checks cleared?" — useful for ``sm status`` and
        console summary output to distinguish "your baseline tooling
        works" from "no novel issues detected".

        Counts only PASSED results.  Failed/warned are reported
        individually; aggregate counts are for the success path.
        Unknown role (None) bucketed under "diagnostic" — matches
        the BaseCheck default.
        """
        counts: Dict[str, int] = {"foundation": 0, "diagnostic": 0}
        for r in self.passed:
            role = r.role or "diagnostic"
            if role in counts:
                counts[role] += 1
            else:  # future roles — don't crash, bucket as diagnostic
                counts["diagnostic"] += 1
        return counts

    def cache_summary(self) -> Optional[str]:
        """One-line cache summary, or None if no results came from cache.

        Format: '📦 N/M from cache (commit abc1234, 2m ago)'
        """
        cached = [r for r in self.summary.results if r.cached]
        if not cached:
            return None

        total_ran = self._cache_total_ran(cached)
        n_cached = len(cached)

        parts = [f"📦 {n_cached}/{total_ran} from cache"]

        detail_parts: list[str] = []
        commits = _unique_non_empty([r.cache_commit for r in cached])
        if len(commits) == 1:
            detail_parts.append(f"commit {commits[0]}")
        elif commits:
            detail_parts.append(f"{len(commits)} commits")

        timestamps = self._cache_timestamps(cached)
        if len(timestamps) == 1:
            age = _format_age(timestamps[0])
            if age:
                detail_parts.append(f"{age} ago")
        elif len(timestamps) > 1:
            oldest_age = _format_age(timestamps[0])
            newest_age = _format_age(timestamps[-1])
            if oldest_age and newest_age:
                detail_parts.append(f"{newest_age} to {oldest_age} ago")
        if detail_parts:
            parts.append(f"({', '.join(detail_parts)})")

        return " ".join(parts)

    def cache_metadata(self) -> Optional[Dict[str, object]]:
        """Structured cache provenance for adapters and machine output."""
        cached = [r for r in self.summary.results if r.cached]
        if not cached:
            return None

        refresh_command = f"sm {self.level or 'swab'} --no-cache"
        metadata: Dict[str, object] = {
            "cached_results": len(cached),
            "total_ran": self._cache_total_ran(cached),
            "refresh_command": refresh_command,
        }

        commits = _unique_non_empty([r.cache_commit for r in cached])
        if len(commits) == 1:
            metadata["source_commit"] = commits[0]
        elif commits:
            metadata["source_commits"] = commits

        timestamps = self._cache_timestamps(cached)
        if len(timestamps) == 1:
            metadata["source_timestamp"] = timestamps[0]
            age = _format_age(timestamps[0])
            if age:
                metadata["source_age"] = age
        elif len(timestamps) > 1:
            metadata["oldest_source_timestamp"] = timestamps[0]
            metadata["newest_source_timestamp"] = timestamps[-1]
            oldest_age = _format_age(timestamps[0])
            newest_age = _format_age(timestamps[-1])
            if oldest_age:
                metadata["oldest_source_age"] = oldest_age
            if newest_age:
                metadata["newest_source_age"] = newest_age
        return metadata

    def _cache_total_ran(self, cached: List[CheckResult]) -> int:
        """Count cache-eligible results with a non-zero denominator."""
        total = len(
            [r for r in self.summary.results if r.status != CheckStatus.NOT_APPLICABLE]
        )
        return max(total, len(cached))

    def _cache_timestamps(self, cached: List[CheckResult]) -> List[str]:
        """Return cached timestamps ordered from oldest to newest."""
        ordered: List[tuple[str, datetime]] = []
        for raw in _unique_non_empty([r.cache_timestamp for r in cached]):
            parsed = _parse_iso_timestamp(raw)
            if parsed is None:
                continue
            ordered.append((raw, parsed))
        ordered.sort(key=lambda item: item[1])
        return [raw for raw, _ in ordered]
