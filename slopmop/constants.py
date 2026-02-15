"""Shared string constants extracted to avoid duplication across modules."""

# CLI help text
PROJECT_ROOT_HELP = "Project root directory (default: current directory)"


def format_duration_suffix(seconds: float) -> str:
    """Format a duration as a trailing summary fragment, e.g. ' · ⏱️  3.2s'."""
    return f" · ⏱️  {seconds:.1f}s"


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
