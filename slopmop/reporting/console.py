"""Console output formatting for quality gate results.

Provides clear, AI-friendly output with actionable error messages
that guide iterative fix-and-resume workflows.
"""

import os
from typing import Optional

from slopmop.constants import STATUS_EMOJI, format_duration_suffix
from slopmop.core.result import CheckResult, CheckStatus, ExecutionSummary, SkipReason


class ConsoleReporter:
    """Console reporter for quality gate execution.

    Formats output for terminal display with:
    - Progress indicators
    - Color-coded status
    - Clear error messages
    - Actionable fix suggestions
    - Explicit iteration guidance for AI agents
    """

    def __init__(
        self,
        quiet: bool = False,
        verbose: bool = False,
        verb: Optional[str] = None,
        project_root: Optional[str] = None,
    ):
        """Initialize reporter.

        Args:
            quiet: Minimal output mode (only failures)
            verbose: Verbose output mode (include all output)
            verb: The verb being run (swab, scour, etc.) for iteration guidance
            project_root: Project root for writing failure logs
        """
        self.quiet = quiet
        self.verbose = verbose
        self.verb = verb
        self.project_root = project_root

    def on_check_complete(self, result: CheckResult) -> None:
        """Called when a check completes.

        Prints a one-line status indicator.  Failure and warning details
        are deferred to ``print_summary()`` to avoid double-printing —
        the summary already shows compact failure sections with log paths.

        Args:
            result: The check result
        """
        if self.quiet and result.passed:
            return

        emoji = STATUS_EMOJI.get(result.status, "❓")
        print(f"{emoji} {result.name}: {result.status.value} ({result.duration:.2f}s)")

        # Only expand output in verbose mode — otherwise print_summary
        # handles failure/warning details to prevent duplication.
        if self.verbose and result.output:
            print(f"   Output: {result.output[:200]}...")

    def _print_failure_details(self, result: CheckResult) -> None:
        """Print detailed failure information.

        Args:
            result: Failed check result
        """
        print()
        print("   " + "=" * 56)

        if result.error:
            print(f"   ❌ Error: {result.error}")

        if result.output:
            print("   📋 Output:")
            lines = result.output.split("\n")
            max_lines = None if self.verbose else 20

            if max_lines and len(lines) > max_lines:
                for line in lines[:max_lines]:
                    print(f"      {line}")
                print("      ... (truncated)")
            else:
                for line in lines:
                    print(f"      {line}")

        if result.fix_suggestion:
            print()
            print(f"   💡 Fix: {result.fix_suggestion}")

        print("   " + "=" * 56)
        print()

    def _print_warning_details(self, result: CheckResult) -> None:
        """Print warning details (tool not installed, etc.).

        Args:
            result: Warned check result
        """
        print()
        print("   " + "-" * 56)

        if result.error:
            print(f"   ⚠️  {result.error}")

        if result.fix_suggestion:
            print(f"   💡 {result.fix_suggestion}")

        print("   " + "-" * 56)
        print()

    @staticmethod
    def _skip_reason_code(result: CheckResult) -> str:
        """Return a short reason code for a skipped check.

        Uses the structured SkipReason enum when available, falling
        back to string matching on output for legacy results.
        """
        if result.skip_reason is not None:
            return result.skip_reason.value
        # Legacy fallback — results created without skip_reason
        output = (result.output or "").lower()
        if "fail-fast" in output or "fail fast" in output:
            return SkipReason.FAIL_FAST.value
        if "dependency" in output:
            return SkipReason.FAILED_DEPENDENCY.value
        if "disabled" in output:
            return SkipReason.DISABLED.value
        return "skip"

    @staticmethod
    def _format_skipped_line(skipped: list[CheckResult]) -> str:
        """Format skipped checks into a compact single line.

        Groups by reason code: e.g. "4 skipped (ff)"
        or "2 skipped (ff), 1 skipped (dep)" if mixed.
        """
        if not skipped:
            return ""

        from collections import Counter

        codes = Counter(ConsoleReporter._skip_reason_code(r) for r in skipped)
        parts = [f"{count} skipped ({code})" for code, count in codes.items()]
        return " · ".join(parts)

    def write_failure_log(self, result: CheckResult) -> Optional[str]:
        """Write check output to a log file for detailed review.

        Returns relative path to the log file, or None if no project_root.
        """
        if not self.project_root:
            return None

        log_dir = os.path.join(self.project_root, ".slopmop", "logs")
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

    def _print_failure_sections(
        self,
        failed: list[CheckResult],
        errors: list[CheckResult],
    ) -> None:
        """Print compact failure and error details with optional log paths."""
        max_preview_lines = 10
        write_logs = self.project_root is not None

        for emoji, default_detail, results in [
            ("❌", "", failed),
            ("💥", "unknown error", errors),
        ]:
            for r in results:
                detail = r.error or default_detail
                header = (
                    f"{emoji} {r.name} — {detail}" if detail else f"{emoji} {r.name}"
                )
                print(header)
                if r.output:
                    all_lines = r.output.strip().split("\n")
                    lines = [
                        ln for ln in all_lines if "✅" not in ln and ln.strip()
                    ] or all_lines
                    for line in lines[:max_preview_lines]:
                        print(f"   {line}")
                    if write_logs and len(lines) > max_preview_lines:
                        print(
                            f"   ... ({len(lines) - max_preview_lines}"
                            " more lines in log)"
                        )
                if r.fix_suggestion:
                    print(f"   💡 {r.fix_suggestion}")
                self._print_rerun_hint(r, write_logs)

    def _print_rerun_hint(self, result: CheckResult, write_logs: bool) -> None:
        """Print the 'rerun this gate' hint with optional log path."""
        rerun = f"sm swab -g {result.name} --verbose"
        if write_logs:
            log_path = self.write_failure_log(result)
            if log_path:
                print(f"   📄 {log_path} · {rerun}")
                return
        print(f"   ▸ {rerun}")

    @staticmethod
    def _print_warning_sections(warned: list[CheckResult]) -> None:
        """Print warning section for missing tools / env issues."""
        print()
        print("⚠️  WARNINGS (non-blocking):")
        for r in warned:
            print(f"   • {r.name}")
            if r.error:
                print(f"     └─ {r.error}")
            if r.fix_suggestion:
                print(f"     💡 {r.fix_suggestion}")

    def print_summary(self, summary: ExecutionSummary) -> None:
        """Print execution summary.

        Args:
            summary: Execution summary to display
        """
        # Categorize results
        passed = [r for r in summary.results if r.status == CheckStatus.PASSED]
        failed = [r for r in summary.results if r.status == CheckStatus.FAILED]
        warned = [r for r in summary.results if r.status == CheckStatus.WARNED]
        skipped = [r for r in summary.results if r.status == CheckStatus.SKIPPED]
        errors = [r for r in summary.results if r.status == CheckStatus.ERROR]

        print("═" * 60)

        if summary.all_passed:
            passed_label = f"{summary.passed} checks passed"
            if warned:
                passed_label += f", {len(warned)} warned"
            print(
                f"✨ NO SLOP DETECTED · {passed_label}"
                f" in {summary.total_duration:.1f}s"
            )
            print("═" * 60)
            if warned:
                self._print_warning_sections(warned)
            return

        # --- Failure path: compact output ---

        # Build counts line
        counts: list[str] = []
        if passed:
            counts.append(f"✅ {len(passed)} passed")
        if warned:
            counts.append(f"⚠️  {len(warned)} warned")
        if failed:
            counts.append(f"❌ {len(failed)} failed")
        if errors:
            counts.append(f"💥 {len(errors)} errored")
        if skipped:
            counts.append(f"⏭️  {self._format_skipped_line(skipped)}")

        print(
            f"🪣 SLOP DETECTED · {' · '.join(counts)}"
            f"{format_duration_suffix(summary.total_duration)}"
        )
        print("─" * 60)

        # Failure details (writes logs when project_root available)
        self._print_failure_sections(failed, errors)
        if warned:
            self._print_warning_sections(warned)

        print("═" * 60)
