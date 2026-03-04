"""Regression tests for the Jest ``"pct": "Unknown"`` crash.

Extracted from ``test_javascript_checks.py`` when that file crested
the 1000-line ``code-sprawl`` threshold.  Found during Phase-2 beta
testing on ai-tic-tac-toe-game: Jest's ``coverage-summary.json`` emits
``"pct": "Unknown"`` (a string) for files with zero executable
statements.  The gate would raise ``TypeError: '>=' not supported
between 'str' and 'int'`` at the threshold comparison and ERROR the
whole run instead of reporting.
"""

from slopmop.checks.javascript.coverage import JavaScriptCoverageCheck
from slopmop.core.result import CheckStatus


class TestJavaScriptCoveragePctCoercion:
    def test_as_pct_coerces_int(self):
        assert JavaScriptCoverageCheck._as_pct(80) == 80.0

    def test_as_pct_coerces_float(self):
        assert JavaScriptCoverageCheck._as_pct(72.5) == 72.5

    def test_as_pct_coerces_numeric_string(self):
        # Not observed in the wild but cheap to handle
        assert JavaScriptCoverageCheck._as_pct("80") == 80.0

    def test_as_pct_handles_unknown_string(self):
        # This is the actual crash case — Jest emits this literally.
        assert JavaScriptCoverageCheck._as_pct("Unknown") == 0.0

    def test_as_pct_handles_none(self):
        assert JavaScriptCoverageCheck._as_pct(None) == 0.0

    def test_evaluate_coverage_survives_unknown_total(self):
        """The integration-level assertion: gate FAILS cleanly, not ERRORS."""
        check = JavaScriptCoverageCheck({"threshold": 80})
        jest_summary = {
            "total": {"lines": {"pct": "Unknown"}},
            "/src/types.ts": {"lines": {"pct": "Unknown"}},
        }
        # Before the fix: TypeError.  After: a normal FAILED with 0.0%.
        result = check._evaluate_coverage(jest_summary, "", 0.1)
        assert result.status is CheckStatus.FAILED

    def test_evaluate_coverage_mixed_unknown_and_numeric(self):
        """Realistic case: one type-only barrel, rest has real coverage."""
        check = JavaScriptCoverageCheck({"threshold": 50})
        jest_summary = {
            "total": {"lines": {"pct": 62.5}},
            "/src/index.ts": {"lines": {"pct": "Unknown"}},  # barrel
            "/src/app.ts": {"lines": {"pct": 85.0}},
        }
        result = check._evaluate_coverage(jest_summary, "", 0.1)
        assert result.status is CheckStatus.PASSED
