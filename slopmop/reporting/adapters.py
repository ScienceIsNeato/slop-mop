"""Output adapters — pure-transform renderers from RunReport to format.

Each adapter takes a :class:`RunReport` and produces output in one
target format.  Adapters are stateless and side-effect-free (they
return strings or dicts; callers handle I/O).  The exception is
:class:`ConsoleAdapter`, which prints directly — console output is
inherently a stream and batching it into a string would lose
incremental-progress value.

The rule: adapters *format*, they don't *compute*.  Business-logic
derivations (what failed? what's the verify command? where are the
logs?) live in :class:`RunReport`.  Format-specific derivations
(SARIF fingerprints, JSON key ordering, console colouring) live here.
If you find yourself writing ``[r for r in summary.results if ...]``
inside an adapter, that's RunReport's job — add a property there.
"""

from typing import Dict, List, cast

from slopmop.constants import ROLE_BADGES, format_duration_suffix
from slopmop.core.result import CheckResult
from slopmop.reporting.report import RunReport


class JsonAdapter:
    """Render a RunReport as the compact JSON schema.

    Output shape is the established ``slopmop/v1``-and-onward contract:
    a ``summary`` block with counts, a ``passed_gates`` name list, a
    ``results`` array for actionable checks.  Enrichment fields
    (``schema``, ``level``, ``log_file``, ``next_steps``) that
    previously lived as inline computation in the CLI now come from
    RunReport's derived state.
    """

    @staticmethod
    def render(report: RunReport) -> Dict[str, object]:
        """Build the JSON-serialisable dict.  Caller owns ``json.dumps``."""
        # Base structure from ExecutionSummary — passed_gates list,
        # actionable results array, summary counts.  We extend it
        # with RunReport enrichment rather than rebuilding from scratch
        # so the to_dict() schema remains the single source of truth
        # for per-result serialisation.
        output = report.summary.to_dict()

        output["schema"] = report.schema_version
        if report.level:
            output["level"] = report.level

        # Attach log file paths into the per-result dicts.  This is
        # post-hoc enrichment — CheckResult.to_dict() doesn't know
        # about log files (they're a CLI concern, not a result
        # concern) so we inject them here where the full picture
        # exists.  Only applied to results that have a log entry;
        # warnings without a log file are left alone.
        if report.log_files and isinstance(output.get("results"), list):
            for entry in cast(List[Dict[str, object]], output["results"]):
                gate_name = str(entry.get("name", ""))
                if gate_name in report.log_files:
                    entry["log_file"] = report.log_files[gate_name]

        # Verify command → next_steps.  A list to leave room for
        # multi-step guidance later without schema churn.  Present
        # only when there IS something to verify — all-passed runs
        # have no next step beyond "commit".
        if report.verify_command:
            output["next_steps"] = [report.verify_command]

        cache = report.cache_metadata()
        if cache:
            output["cache"] = cache

        # Machine-readable runtime warnings for automation/CI parsers.
        # Keep this orthogonal to actionable gate failures: these are
        # execution-context warnings, not check results.
        warnings: List[Dict[str, object]] = []
        skip_reasons = report.summary.skip_reason_summary()
        budget_skips = skip_reasons.get("time", 0)
        if budget_skips > 0:
            warnings.append(
                {
                    "code": "swabbing_time_budget_skipped",
                    "message": (
                        "Swabbing-time budget skipped timed checks; "
                        "run full coverage when needed."
                    ),
                    "skipped_timed_checks": budget_skips,
                    "suggested_command": "sm swab --swabbing-time 0",
                }
            )

        if cache:
            warnings.append(
                {
                    "code": "cached_results_present",
                    "message": (
                        "Some results came from cache; rerun with --no-cache "
                        "for a fresh pass."
                    ),
                    "cached_results": cache["cached_results"],
                    "suggested_command": cache["refresh_command"],
                }
            )

        if warnings:
            output["runtime_warnings"] = warnings

        return output


class SarifAdapter:
    """Render a RunReport as SARIF 2.1.0.

    Thin wrapper over :class:`SarifReporter` — that class already
    encapsulates the SARIF-specific derivations (fingerprinting, rule
    dedup, artifactLocation normalisation) and they *should* stay
    there because they're format-specific, not business-logic.

    This adapter's value is the uniform RunReport interface. SARIF
    format-specific derivations (fingerprinting, rule shaping,
    artifactLocation normalization) remain in ``SarifReporter``.
    """

    @staticmethod
    def render(report: RunReport) -> Dict[str, object]:
        """Build the SARIF document dict.  Caller owns serialisation."""
        from slopmop.reporting.sarif import SarifReporter

        # SarifReporter needs a project root for artifactLocation
        # normalisation and file reads (fingerprint line content).
        # When RunReport has no project root (tests), use "." — SARIF
        # still validates, fingerprints just won't resolve file content.
        root = report.project_root or "."
        return SarifReporter(root).generate(report.summary)


class ConsoleAdapter:
    """Render a RunReport to stdout as human-readable text.

    Owns end-of-run summary output.  ``ConsoleReporter`` remains the
    real-time progress handler (``on_check_complete`` callbacks).

    Unlike the other adapters this one prints directly rather than
    returning a string.  Console output is a stream — buffering the
    whole summary into a string and then printing it gains nothing
    and costs the memory.  For testing, capture stdout via capsys.
    """

    def __init__(self, report: RunReport) -> None:
        self.report = report

    def render(self) -> None:
        """Print the end-of-run summary to stdout."""
        r = self.report
        s = r.summary

        print("═" * 60)

        if s.all_passed:
            self._render_success()
            return

        self._render_failure()

    def _render_success(self) -> None:
        r = self.report
        s = r.summary
        passed_label = f"{s.passed} checks passed"
        if r.warned:
            passed_label += f", {len(r.warned)} warned"

        # Role breakdown — distinguish "standard tooling green" from
        # "diagnostic analysis clean".  Only shown when both tiers
        # have results; single-role runs don't need the split.
        roles = r.role_counts()
        if roles["foundation"] and roles["diagnostic"]:
            passed_label += (
                f" (🔧 {roles['foundation']} foundation,"
                f" 🔬 {roles['diagnostic']} diagnostic)"
            )

        header = f"✨ NO SLOP DETECTED · {passed_label} in {s.total_duration:.1f}s"
        if len(header) > 60:
            print(f"✨ NO SLOP DETECTED · {passed_label}")
            print(f"   in {s.total_duration:.1f}s")
        else:
            print(header)

        cache_line = r.cache_summary()
        if cache_line:
            print(f"   {cache_line}")
            self._render_cache_refresh_hint()

        self._render_time_budget_warning()

        print("═" * 60)
        if r.warned:
            self._render_warnings()

    def _render_failure(self) -> None:
        r = self.report
        s = r.summary

        counts: List[str] = []
        if r.passed:
            counts.append(f"✅ {len(r.passed)} passed")
        if r.warned:
            counts.append(f"⚠️  {len(r.warned)} warned")
        if r.failed:
            counts.append(f"❌ {len(r.failed)} failed")
        if r.errored:
            counts.append(f"💥 {len(r.errored)} errored")
        if r.skipped:
            counts.append(f"⏭️  {self._skipped_line()}")

        duration = format_duration_suffix(s.total_duration)
        header = f"🪣 SLOP DETECTED · {' · '.join(counts)}{duration}"
        # Keep summary under 60 cols (separator width) to avoid PTY wrapping
        if len(header) > 60:
            print("🪣 SLOP DETECTED")
            print(f"   {' · '.join(counts)}{duration}")
        else:
            print(header)

        cache_line = r.cache_summary()
        if cache_line:
            print(f"   {cache_line}")
            self._render_cache_refresh_hint()

        self._render_time_budget_warning()

        print("─" * 60)

        self._render_failure_details()
        if r.warned:
            self._render_warnings()

        print("═" * 60)

    def _render_failure_details(self) -> None:
        """Per-gate breakdown of failures and errors."""
        r = self.report
        max_preview = 10

        for emoji, default_detail, bucket in [
            ("❌", "", r.failed),
            ("💥", "unknown error", r.errored),
        ]:
            for res in bucket:
                badge = _role_badge(res)
                detail = res.error or default_detail
                header = f"{emoji} {badge}{res.name}"
                if detail:
                    header += f" — {detail}"
                print(header)

                if res.output:
                    all_lines = res.output.strip().split("\n")
                    lines = [
                        ln for ln in all_lines if "✅" not in ln and ln.strip()
                    ] or all_lines
                    for ln in lines[:max_preview]:
                        print(f"   {ln}")
                    if r.log_files and len(lines) > max_preview:
                        print(
                            f"   ... ({len(lines) - max_preview}" " more lines in log)"
                        )

                if res.fix_suggestion:
                    print(f"   💡 {res.fix_suggestion}")

                # Verify hint — the command to re-check THIS gate.
                # Different from report.verify_command, which is the
                # overall "first thing to fix" hint; this is per-gate.
                verb = r.level or "swab"
                rerun = f"sm {verb} -g {res.name} --verbose"
                log_path = r.log_files.get(res.name)
                if log_path:
                    print(f"   📄 {log_path}")
                print(f"   ▸ verify: {rerun}")

    def _render_warnings(self) -> None:
        print()
        print("⚠️  WARNINGS (non-blocking):")
        for res in self.report.warned:
            print(f"   • {_role_badge(res)}{res.name}")
            if res.error:
                print(f"     └─ {res.error}")
            if res.fix_suggestion:
                print(f"     💡 {res.fix_suggestion}")

    def _render_time_budget_warning(self) -> None:
        """Warn when timed gates were skipped due to swabbing-time budget."""
        counts = self.report.summary.skip_reason_summary()
        skipped_for_budget = counts.get("time", 0)
        if skipped_for_budget <= 0:
            return

        print(
            "   ⚠️  Swabbing-time budget skipped "
            f"{skipped_for_budget} timed check(s); "
            "run `sm swab --swabbing-time 0` for full coverage."
        )

    def _render_cache_refresh_hint(self) -> None:
        """Print a short freshness hint when cached results were used."""
        cache = self.report.cache_metadata()
        if not cache:
            return
        print(
            "   🔄 Fresh run: rerun `"
            + str(cache["refresh_command"])
            + "` if you need uncached results."
        )

    def _skipped_line(self) -> str:
        """Compact skip-reason breakdown, e.g. '5 skipped (3 n/a · 2 ff)'.

        Results without an explicit ``skip_reason`` are bucketed under
        the neutral ``"skip"`` code rather than guessed.  Defaulting a
        missing reason to ``ff`` (fail-fast) would misreport: a check
        that marked itself SKIPPED for its own reasons would show up
        as if an earlier failure caused it.  The enum docstring says
        ``skip_reason`` should always be set on skipped results, so
        ``"skip"`` showing up is a signal that a check's skip path
        needs fixing — not a fail-fast tally to inflate.
        """
        r = self.report
        n = len(r.skipped)
        reason_counts: Dict[str, int] = {}
        for res in r.skipped:
            code = res.skip_reason.value if res.skip_reason else "skip"
            reason_counts[code] = reason_counts.get(code, 0) + 1
        if not reason_counts:
            return f"{n} skipped"
        parts = [f"{v} {k}" for k, v in sorted(reason_counts.items())]
        return f"{n} skipped ({' · '.join(parts)})"


# ─── helpers ─────────────────────────────────────────────────────────────


def _role_badge(result: CheckResult) -> str:
    """Short emoji prefix distinguishing foundation vs diagnostic gates.

    Foundation = wrench (tooling).  Diagnostic = microscope (analysis).
    Unknown/None → empty string — don't guess.  Map lives in
    constants.py (shared with `sm status`) so both surfaces agree.
    """
    return ROLE_BADGES.get(result.role or "", "")
