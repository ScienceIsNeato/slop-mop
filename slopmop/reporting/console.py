"""Console output formatting for quality gate results.

Provides clear, AI-friendly output with actionable error messages
that guide iterative fix-validate-resume workflows.
"""

from typing import Optional

from slopmop.core.result import CheckResult, CheckStatus, ExecutionSummary


class ConsoleReporter:
    """Console reporter for quality gate execution.

    Formats output for terminal display with:
    - Progress indicators
    - Color-coded status
    - Clear error messages
    - Actionable fix suggestions
    - Explicit iteration guidance for AI agents
    """

    # Status emoji mapping
    STATUS_EMOJI = {
        CheckStatus.PASSED: "✅",
        CheckStatus.FAILED: "❌",
        CheckStatus.WARNED: "⚠️",
        CheckStatus.SKIPPED: "⏭️",
        CheckStatus.NOT_APPLICABLE: "⊘",
        CheckStatus.ERROR: "💥",
    }

    def __init__(
        self,
        quiet: bool = False,
        verbose: bool = False,
        profile: Optional[str] = None,
    ):
        """Initialize reporter.

        Args:
            quiet: Minimal output mode (only failures)
            verbose: Verbose output mode (include all output)
            profile: The profile being run (commit, pr, etc.) for iteration guidance
        """
        self.quiet = quiet
        self.verbose = verbose
        self.profile = profile

    def on_check_complete(self, result: CheckResult) -> None:
        """Called when a check completes.

        Args:
            result: The check result
        """
        if self.quiet and result.passed:
            return

        emoji = self.STATUS_EMOJI.get(result.status, "❓")
        print(f"{emoji} {result.name}: {result.status.value} ({result.duration:.2f}s)")

        # Show output for failures or in verbose mode
        if result.failed or result.status == CheckStatus.ERROR:
            self._print_failure_details(result)
        elif result.status == CheckStatus.WARNED:
            self._print_warning_details(result)
        elif self.verbose and result.output:
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
            # PR checks get full output, others get truncated unless verbose
            is_pr_check = result.name.startswith("pr:")
            max_lines = None if (is_pr_check or self.verbose) else 20

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
    def _print_skip_sections(
        skipped: list[CheckResult],
        na: list[CheckResult],
    ) -> None:
        """Print skipped and not-applicable result sections."""
        if skipped:
            print()
            print("⏭️  SKIPPED:")
            for r in skipped:
                reason = r.output if r.output else "Skipped"
                print(f"   • {r.name}")
                print(f"     └─ {reason}")

        if na:
            print()
            print("⊘  NOT APPLICABLE:")
            for r in na:
                reason = r.output if r.output else "Not applicable to this project"
                print(f"   • {r.name}")
                print(f"     └─ {reason}")

    @staticmethod
    def _print_failure_sections(
        failed: list[CheckResult],
        errors: list[CheckResult],
    ) -> None:
        """Print failure and error detail sections."""
        if failed:
            print("❌ FAILED:")
            for r in failed:
                print(f"   • {r.name}")
                if r.error:
                    print(f"     └─ {r.error}")
                if r.fix_suggestion:
                    print(f"     💡 {r.fix_suggestion}")
            print()

        if errors:
            print("💥 ERRORS (check couldn't run):")
            for r in errors:
                print(f"   • {r.name}")
                print(f"     └─ {r.error}")
            print()

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
        print()
        print("=" * 60)

        # Categorize results
        passed = [r for r in summary.results if r.status == CheckStatus.PASSED]
        failed = [r for r in summary.results if r.status == CheckStatus.FAILED]
        warned = [r for r in summary.results if r.status == CheckStatus.WARNED]
        skipped = [r for r in summary.results if r.status == CheckStatus.SKIPPED]
        na = [r for r in summary.results if r.status == CheckStatus.NOT_APPLICABLE]
        errors = [r for r in summary.results if r.status == CheckStatus.ERROR]

        if summary.all_passed:
            passed_label = f"{summary.passed} checks passed"
            if warned:
                passed_label += f", {len(warned)} warned"
            print(
                f"✨ NO SLOP DETECTED · {passed_label} in {summary.total_duration:.1f}s"
            )
            print("=" * 60)
            if not self.quiet:
                for r in passed:
                    print(f"   ✅ {r.name} ({r.duration:.2f}s)")
                for r in warned:
                    print(f"   ⚠️  {r.name} ({r.duration:.2f}s)")
            if warned:
                self._print_warning_sections(warned)
            self._print_skip_sections(skipped, na)
            print()
            return

        # Failure output - more detailed
        print("🧹 SLOP DETECTED")
        print("=" * 60)

        # Show counts only for non-zero statuses
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
            counts.append(f"⏭️  {len(skipped)} skipped")
        if na:
            counts.append(f"⊘  {len(na)} n/a")

        print(f"   {' · '.join(counts)} · ⏱️  {summary.total_duration:.1f}s")
        print()

        self._print_failure_sections(failed, errors)
        if warned:
            self._print_warning_sections(warned)
        self._print_skip_sections(skipped, na)
        print()

        # Final verdict with iteration guidance
        print("─" * 60)
        print(f"🧹 Time to mop up {summary.failed + summary.errors} issue(s)")
        print()
        self._print_iteration_guidance(failed, errors)
        print("=" * 60)
        print()

    def _print_iteration_guidance(
        self,
        failed: list[CheckResult],
        errors: list[CheckResult],
    ) -> None:
        """Print explicit iteration guidance for AI agents.

        This tells the agent exactly what to do next in a fail-fast,
        iterative workflow.
        """
        # Get the first failure (fail-fast means this is what stopped us)
        first_failure = failed[0] if failed else (errors[0] if errors else None)
        if not first_failure:
            return

        profile = self.profile or "commit"
        gate_name = first_failure.name

        # Build content lines to compute dynamic width
        title = "🤖 AI AGENT ITERATION GUIDANCE"
        validate_cmd = f"sm validate {gate_name} --verbose"
        resume_cmd = f"sm validate {profile}"

        lines = [
            title,
            f"Profile: {profile}",
            f"Failed Gate: {gate_name}",
            "NEXT STEPS:",
            "",
            "1. Fix the issue described above",
            f"2. Validate: {validate_cmd}",
            f"3. Resume:   {resume_cmd}",
            "",
            "Keep iterating until all the slop is mopped.",
        ]

        # Compute box width (minimum 58 for aesthetics, expand if needed)
        content_width = max(len(line) for line in lines)
        box_width = max(58, content_width + 2)  # +2 for padding

        def box_line(text: str) -> str:
            """Format a line to fit in the box with padding."""
            return f"│ {text:<{box_width - 2}} │"

        print("┌" + "─" * box_width + "┐")
        print(box_line(title))
        print("├" + "─" * box_width + "┤")
        print(box_line(f"Profile: {profile}"))
        print(box_line(f"Failed Gate: {gate_name}"))
        print("├" + "─" * box_width + "┤")
        print(box_line("NEXT STEPS:"))
        print(box_line(""))
        print(box_line("1. Fix the issue described above"))
        print(box_line(f"2. Validate: {validate_cmd}"))
        print(box_line(f"3. Resume:   {resume_cmd}"))
        print(box_line(""))
        print(box_line("Keep iterating until all the slop is mopped."))
        print("└" + "─" * box_width + "┘")
