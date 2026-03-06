"""Shared string constants extracted to avoid duplication across modules."""

from slopmop.core.result import CheckStatus

# CLI help text
PROJECT_ROOT_HELP = "Project root directory (default: current directory)"


def format_duration_suffix(seconds: float) -> str:
    """Format a duration as a trailing summary fragment, e.g. ' · ⏱️  3.2s'."""
    return f" · ⏱️  {seconds:.1f}s"


# Status emoji mapping — shared between ConsoleReporter and DynamicDisplay
STATUS_EMOJI = {
    CheckStatus.PASSED: "✅",
    CheckStatus.FAILED: "❌",
    CheckStatus.WARNED: "⚠️",
    CheckStatus.SKIPPED: "⏭️",
    CheckStatus.NOT_APPLICABLE: "⊘",
    CheckStatus.ERROR: "💥",
}

# Role → badge emoji.  Keyed off CheckRole.value (str) rather than the
# enum itself so callers that handle bare strings (CheckResult.role,
# CLI JSON output) don't need an import of checks.base just to look up
# an emoji.  Wrench = foundation (wraps standard tooling), microscope
# = diagnostic (novel analysis).  Unknown key → "" via .get().
#
# Shared between ConsoleAdapter (post-run summary) and `sm status`
# (gate inventory) so both surfaces speak the same visual language.
ROLE_BADGES = {
    "foundation": "🔧 ",
    "diagnostic": "🔬 ",
}


# Check result messages
NO_ISSUES_FOUND = "No issues found"
COVERAGE_XML_NOT_FOUND = "coverage.xml not found"
COVERAGE_MEETS_THRESHOLD = "Coverage meets required threshold."
COVERAGE_BELOW_THRESHOLD = "Coverage below threshold"
NPM_INSTALL_FAILED = "npm install failed"

# Coverage fix guidance — used by both Python and JS coverage checks
COVERAGE_STANDARDS_PREFIX = "This commit doesn't meet code coverage standards. "
COVERAGE_GUIDANCE_FOOTER = (
    "When adding coverage, extend existing tests when possible. "
    "Focus on meaningful assertions, not just line coverage."
)
