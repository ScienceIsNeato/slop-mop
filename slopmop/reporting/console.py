"""Console output formatting for quality gate results.

Real-time progress callbacks for terminal display.  End-of-run
summary rendering lives in :class:`slopmop.reporting.adapters.ConsoleAdapter`.
"""

from typing import Optional

from slopmop.constants import STATUS_EMOJI
from slopmop.core.result import CheckResult


class ConsoleReporter:
    """Real-time console progress reporter for quality gate execution.

    Handles per-check progress callbacks during execution.  The
    end-of-run summary is rendered by ``ConsoleAdapter`` — this
    class only emits the live, one-line-per-check status indicators.
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
        are deferred to the end-of-run summary to avoid double-printing.

        Args:
            result: The check result
        """
        if self.quiet and result.passed:
            return

        emoji = STATUS_EMOJI.get(result.status, "❓")
        print(f"{emoji} {result.name}: {result.status.value} ({result.duration:.2f}s)")

        # Only expand output in verbose mode — otherwise the end-of-run
        # summary handles failure/warning details to prevent duplication.
        if self.verbose and result.output:
            print(f"   Output: {result.output[:200]}...")
