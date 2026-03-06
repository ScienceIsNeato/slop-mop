"""Canonical run representation and output adapters.

``RunReport`` is the single enriched view of a validation run.
``ExecutionSummary`` is what the executor produces — raw results plus
counts.  ``RunReport`` is what adapters consume — categorised results,
log file paths, rerun commands, role aggregation.  Everything any
output format needs, computed once.

The adapters (:class:`JsonAdapter`, :class:`SarifAdapter`,
:class:`ConsoleAdapter`) are pure transforms: they format, they don't
compute.  Adding a new output format (JUnit XML, GitHub Actions
annotations) means writing one ``render(report)`` function, not
threading a new branch through ``_run_validation()``.

Why this exists: before this module, JSON enrichment lived inline in
``validate.py`` while console and SARIF delegated to classes.  Result
categorisation ran twice.  Rerun hints were formatted in two places.
Adding ``fix_strategy`` and ``role`` would have meant touching three
code paths for every field.  Now there's one pipe.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, cast

from slopmop.core.result import CheckResult, CheckStatus, ExecutionSummary

# JSON schema version.  Bumped from v1 when ``role`` (CheckResult) and
# ``fix_strategy`` (Finding) were added — both additive, but v1
# consumers deserve a signal that the shape grew.
JSON_SCHEMA = "slopmop/v2"


def _write_failure_log(result: CheckResult, project_root: str) -> Optional[str]:
    """Write a check's full output to ``.slopmop/logs/{name}.log``.

    Returns the relative path, or ``None`` when no ``project_root``
    is available.  Lifted from ``ConsoleReporter`` so it's not owned
    by any one adapter — both JSON and console paths reference the
    same log files.
    """
    if not project_root:
        return None

    log_dir = os.path.join(project_root, ".slopmop", "logs")
    os.makedirs(log_dir, exist_ok=True)

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

    return f".slopmop/logs/{safe_name}.log"


@dataclass
class RunReport:
    """Canonical enriched representation of a validation run.

    Built from an :class:`ExecutionSummary` via :meth:`from_summary`.
    Holds every derived view any adapter needs — categorised result
    lists, log file paths, rerun commands — so adapters never compute.

    Attributes:
        summary: Raw executor output.  Kept for adapters that need
            counts or want to reach through to ``to_dict()``.
        passed, failed, warned, skipped, errors: Result lists split
            by status.  The same categorisation console and JSON both
            did independently — now done once here.
        level: ``"swab"`` / ``"scour"`` run label, or ``None`` for
            explicit ``-g`` invocations.
        project_root: Absolute project root.  Needed by log writing
            and SARIF URI normalisation.
        log_files: Gate name → relative log path for failed/errored
            gates.  Populated at construction so JSON and console
            reference identical paths.
    """

    summary: ExecutionSummary
    passed: List[CheckResult] = field(
        default_factory=lambda: cast(List[CheckResult], [])
    )
    failed: List[CheckResult] = field(
        default_factory=lambda: cast(List[CheckResult], [])
    )
    warned: List[CheckResult] = field(
        default_factory=lambda: cast(List[CheckResult], [])
    )
    skipped: List[CheckResult] = field(
        default_factory=lambda: cast(List[CheckResult], [])
    )
    errors: List[CheckResult] = field(
        default_factory=lambda: cast(List[CheckResult], [])
    )
    level: Optional[str] = None
    project_root: str = ""
    log_files: Dict[str, str] = field(default_factory=lambda: cast(Dict[str, str], {}))

    @classmethod
    def from_summary(
        cls,
        summary: ExecutionSummary,
        project_root: str,
        level: Optional[str] = None,
        write_logs: bool = True,
    ) -> "RunReport":
        """Build the enriched report from raw executor output.

        ``write_logs`` controls whether failure logs are written to
        disk during construction.  It's on by default because every
        real output path wants them; tests turn it off to avoid
        filesystem churn.
        """
        results = summary.results
        passed = [r for r in results if r.status == CheckStatus.PASSED]
        failed = [r for r in results if r.status == CheckStatus.FAILED]
        warned = [r for r in results if r.status == CheckStatus.WARNED]
        skipped = [r for r in results if r.status == CheckStatus.SKIPPED]
        errors = [r for r in results if r.status == CheckStatus.ERROR]

        log_files: Dict[str, str] = {}
        if write_logs and project_root:
            for r in failed + errors:
                path = _write_failure_log(r, project_root)
                if path:
                    log_files[r.name] = path

        return cls(
            summary=summary,
            passed=passed,
            failed=failed,
            warned=warned,
            skipped=skipped,
            errors=errors,
            level=level,
            project_root=project_root,
            log_files=log_files,
        )

    @property
    def all_passed(self) -> bool:
        return self.summary.all_passed

    @property
    def first_actionable(self) -> Optional[CheckResult]:
        """The first failed/errored result — where to start fixing.

        Failed takes precedence over errored: a FAILED gate found real
        slop; an ERROR gate couldn't run.  Fix the slop first.
        """
        if self.failed:
            return self.failed[0]
        if self.errors:
            return self.errors[0]
        return None

    @staticmethod
    def verify_command(result: CheckResult) -> str:
        """The exact command that re-checks ONE gate.

        Every gate's output should end with this.  It's the closing
        of the loop: read the fix, apply the fix, run this command,
        see green.  ``--verbose`` because if the fix didn't land the
        agent needs the full output, not the preview.

        Assumes ``sm`` is on PATH — pipx puts the entrypoint there,
        and the legacy setup.sh bolt-on does the same.
        """
        return f"sm swab -g {result.name} --verbose"

    @property
    def next_steps(self) -> List[str]:
        """Commands to run next.  Empty when everything passed."""
        first = self.first_actionable
        return [self.verify_command(first)] if first else []

    def role_counts(self) -> Dict[str, Dict[str, int]]:
        """Pass/fail counts split by architectural tier.

        Shape: ``{"foundation": {"passed": 5, "failed": 1}, ...}``.
        Results without a ``role`` (legacy, or constructed outside
        ``_create_result``) are bucketed under ``"unknown"``.
        """
        counts: Dict[str, Dict[str, int]] = {}
        for r in self.summary.results:
            role = r.role or "unknown"
            bucket = counts.setdefault(role, {"passed": 0, "failed": 0})
            if r.status == CheckStatus.PASSED:
                bucket["passed"] += 1
            elif r.status in (CheckStatus.FAILED, CheckStatus.ERROR):
                bucket["failed"] += 1
        return counts


# ─── Adapters ────────────────────────────────────────────────────────────


class JsonAdapter:
    """Render a RunReport as the compact JSON format.

    Everything that used to happen inline in ``_run_validation()`` —
    schema tag, level, log file attachment, next_steps — now reads
    from the report.  The adapter composes; it doesn't compute.
    """

    @staticmethod
    def render(report: RunReport) -> str:
        output = report.summary.to_dict()
        output["schema"] = JSON_SCHEMA

        if report.level:
            output["level"] = report.level

        # Attach log file paths.  ``results`` only contains actionable
        # (failed/warned/error) entries — the same set that has logs.
        if report.log_files and isinstance(output.get("results"), list):
            for entry in cast(List[Dict[str, object]], output["results"]):
                gate_name = str(entry.get("name", ""))
                if gate_name in report.log_files:
                    entry["log_file"] = report.log_files[gate_name]

        if report.next_steps:
            output["next_steps"] = report.next_steps

        # Role split lets agents reason about "is the floor clean"
        # separately from "are there diagnostic findings".
        roles = report.role_counts()
        if roles:
            output["roles"] = roles

        return json.dumps(output, separators=(",", ":"))


class SarifAdapter:
    """Render a RunReport as SARIF 2.1.0.

    Thin wrapper over :class:`SarifReporter` — that class has 390
    lines of URI normalisation and fingerprint hashing that just
    survived an A/B bake-off.  We delegate, we don't rewrite.  The
    only adapter concern here is the JSON serialisation shape
    (indented, for human diffability of the ``.sarif`` file).
    """

    @staticmethod
    def render(report: RunReport) -> str:
        from slopmop.reporting.sarif import SarifReporter

        sarif = SarifReporter(report.project_root).generate(report.summary)
        return json.dumps(sarif, indent=2)


class ConsoleAdapter:
    """Render a RunReport to the terminal.

    Unlike the other adapters, :meth:`render` returns ``None`` and
    writes directly to stdout — console output is inherently a side
    effect, and returning a string the caller prints would just add
    a layer of indirection for no benefit.

    The live-progress callback (``on_check_complete``) remains on
    :class:`ConsoleReporter`; that's a streaming concern, not a
    report-rendering one.  This adapter only handles the final
    summary.
    """

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose

    def render(self, report: RunReport) -> None:
        from slopmop.constants import format_duration_suffix

        summary = report.summary
        print("═" * 60)

        if report.all_passed:
            label = f"{summary.passed} checks passed"
            if report.warned:
                label += f", {len(report.warned)} warned"
            print(f"✨ NO SLOP DETECTED · {label} in {summary.total_duration:.1f}s")
            self._print_role_line(report)
            print("═" * 60)
            if report.warned:
                self._print_warnings(report.warned)
            return

        # Failure path — compact, actionable, one rerun hint per gate.
        counts: List[str] = []
        if report.passed:
            counts.append(f"✅ {len(report.passed)} passed")
        if report.warned:
            counts.append(f"⚠️  {len(report.warned)} warned")
        if report.failed:
            counts.append(f"❌ {len(report.failed)} failed")
        if report.errors:
            counts.append(f"💥 {len(report.errors)} errored")
        if report.skipped:
            counts.append(f"⏭️  {len(report.skipped)} skipped")

        print(
            f"🪣 SLOP DETECTED · {' · '.join(counts)}"
            f"{format_duration_suffix(summary.total_duration)}"
        )
        self._print_role_line(report)
        print("─" * 60)

        self._print_failures(report)
        if report.warned:
            self._print_warnings(report.warned)

        print("═" * 60)

    @staticmethod
    def _print_role_line(report: RunReport) -> None:
        """One-line foundation vs diagnostic summary.

        Only printed when there's something to distinguish — a run
        with all-unknown roles (legacy results, custom gates) skips
        this rather than print ``unknown: 5/5``.
        """
        roles = report.role_counts()
        known = {k: v for k, v in roles.items() if k != "unknown"}
        if not known:
            return
        parts: List[str] = []
        for role in ("foundation", "diagnostic"):
            if role in known:
                c = known[role]
                total = c["passed"] + c["failed"]
                parts.append(f"{role}: {c['passed']}/{total}")
        if parts:
            print(f"   {' · '.join(parts)}")

    def _print_failures(self, report: RunReport) -> None:
        """Compact failure details with rerun hints.

        Preview is capped at 10 lines to keep the console readable;
        the log file has everything.  The ``✅`` filter strips lines
        from tools that print per-file success before the final
        failure — noise when what you want is the one failing case.
        """
        max_preview = 10

        for emoji, default_detail, results in [
            ("❌", "", report.failed),
            ("💥", "unknown error", report.errors),
        ]:
            for r in results:
                detail = r.error or default_detail
                header = (
                    f"{emoji} {r.name} — {detail}" if detail else f"{emoji} {r.name}"
                )
                if r.role:
                    header += f"  [{r.role}]"
                print(header)

                if r.output:
                    all_lines = r.output.strip().split("\n")
                    lines = [
                        ln for ln in all_lines if "✅" not in ln and ln.strip()
                    ] or all_lines
                    for line in lines[:max_preview]:
                        print(f"   {line}")
                    if report.log_files and len(lines) > max_preview:
                        print(f"   ... ({len(lines) - max_preview} more lines in log)")

                if r.fix_suggestion:
                    print(f"   💡 {r.fix_suggestion}")

                rerun = RunReport.verify_command(r)
                log_path = report.log_files.get(r.name)
                if log_path:
                    print(f"   📄 {log_path} · {rerun}")
                else:
                    print(f"   ▸ {rerun}")

    @staticmethod
    def _print_warnings(warned: List[CheckResult]) -> None:
        print()
        print("⚠️  WARNINGS (non-blocking):")
        for r in warned:
            print(f"   • {r.name}")
            if r.error:
                print(f"     └─ {r.error}")
            if r.fix_suggestion:
                print(f"     💡 {r.fix_suggestion}")
