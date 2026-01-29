"""Console output formatting for quality gate results.

Provides clear, AI-friendly output with actionable error messages
that guide iterative fix-validate-resume workflows.
"""

from typing import Optional

from slopbucket.core.result import CheckResult, CheckStatus, ExecutionSummary


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
        CheckStatus.SKIPPED: "⏭️",
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
        skipped = [r for r in summary.results if r.status == CheckStatus.SKIPPED]
        errors = [r for r in summary.results if r.status == CheckStatus.ERROR]

        if summary.all_passed:
            # Clean, minimal success output
            print(
                f"✨ NO SLOP DETECTED · {summary.passed} checks passed in {summary.total_duration:.1f}s"
            )
            print("=" * 60)
            if not self.quiet:
                for r in passed:
                    print(f"   ✅ {r.name}")
            if skipped:
                print()
                print(f"   ⏭️  {len(skipped)} skipped (not applicable)")
            print()
            return

        # Failure output - more detailed
        print("🪣 SLOP DETECTED")
        print("=" * 60)

        # Show counts only for non-zero statuses
        counts = []
        if passed:
            counts.append(f"✅ {len(passed)} passed")
        if failed:
            counts.append(f"❌ {len(failed)} failed")
        if errors:
            counts.append(f"💥 {len(errors)} errored")
        if skipped:
            counts.append(f"⏭️  {len(skipped)} skipped")

        print(f"   {' · '.join(counts)} · ⏱️  {summary.total_duration:.1f}s")
        print()

        # Show failures with details
        if failed:
            print("❌ FAILED:")
            for r in failed:
                print(f"   • {r.name}")
                if r.error:
                    print(f"     └─ {r.error}")
                if r.fix_suggestion:
                    print(f"     💡 {r.fix_suggestion}")
            print()

        # Show errors (check couldn't run at all)
        if errors:
            print("💥 ERRORS (check couldn't run):")
            for r in errors:
                print(f"   • {r.name}")
                print(f"     └─ {r.error}")
            print()

        # Show skipped only in verbose mode
        if skipped and self.verbose:
            print("⏭️  SKIPPED (not applicable):")
            for r in skipped:
                print(f"   • {r.name}")
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

        print("┌" + "─" * 58 + "┐")
        print("│ 🤖 AI AGENT ITERATION GUIDANCE" + " " * 27 + "│")
        print("├" + "─" * 58 + "┤")
        print(f"│ Profile: {profile:<48} │")
        print(f"│ Failed Gate: {gate_name:<44} │")
        print("├" + "─" * 58 + "┤")
        print("│ NEXT STEPS:                                              │")
        print("│                                                          │")
        print("│ 1. Fix the issue described above                         │")
        print(f"│ 2. Validate: sb validate {gate_name:<32} │")
        print(f"│ 3. Resume:   sb validate {profile:<32} │")
        print("│                                                          │")
        print("│ Keep iterating until the bucket is empty.                │")
        print("└" + "─" * 58 + "┘")
