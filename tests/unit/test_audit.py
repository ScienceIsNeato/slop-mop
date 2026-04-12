"""Tests for slopmop.cli.audit — focusing on count/reporting correctness.

Three mismatch bugs motivate these tests:

1. ``_format_gate_section`` derived "passing" count from ``results`` only,
   but the scour JSON puts passing gates in ``passed_gates`` (not in
   ``results``).  The PASSING GATES section was always 0.

2. ``sm status`` RECENT HISTORY read from ``last_swab.json`` which only
   covers swab-level gates, so scour-only failures (dependency-risk,
   just-this-once) showed "Failed gates: 0" even when they were failing.

3. Same summary line in ``_format_gate_section`` uses ``summary.failed``
   from the scour JSON — that is correct — but the displayed gate list
   must match: len(failing) == summary["failed"].
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from slopmop.cli.audit import _format_gate_section

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_gate_data(
    *,
    passed: int = 0,
    failed: int = 0,
    warned: int = 0,
    not_applicable: int = 0,
    skipped: int = 0,
    passed_gates: Optional[List[str]] = None,
    failing_results: Optional[List[Dict[str, Any]]] = None,
    warned_results: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build a minimal gate-data dict that mirrors the scour JSON structure."""
    total = passed + failed + warned + not_applicable + skipped
    results: List[Dict[str, Any]] = []
    if failing_results:
        results.extend(failing_results)
    if warned_results:
        results.extend(warned_results)
    return {
        "summary": {
            "total_checks": total,
            "passed": passed,
            "failed": failed,
            "warned": warned,
            "not_applicable": not_applicable,
            "skipped": skipped,
            "errors": 0,
            "all_passed": failed == 0 and warned == 0,
            "total_duration": 10.0,
        },
        # Passing names live here, NOT in results
        "passed_gates": passed_gates or [],
        # Only non-passing entries appear in results
        "results": results,
    }


def _failing(name: str, error: str = "some issue") -> Dict[str, Any]:
    return {"name": name, "status": "failed", "error": error, "findings": []}


def _warned(name: str) -> Dict[str, Any]:
    return {"name": name, "status": "warned", "error": ""}


# ── Bug 1: passing count was always 0 because it read the wrong field ────────


class TestFormatGateSectionPassingCount:
    """``_format_gate_section`` must show the right number of passing gates."""

    def test_passing_gates_shown_from_passed_gates_field(self) -> None:
        """Regression: previously PASSING GATES section was always empty (0)
        because it filtered ``results`` for status="passed", but passing gates
        only appear in the top-level ``passed_gates`` list."""
        gate_data = _make_gate_data(
            passed=3,
            failed=0,
            passed_gates=[
                "myopia:ambiguity-mines.py",
                "laziness:dead-code.py",
                "overconfidence:coverage-gaps.py",
            ],
        )
        lines = _format_gate_section(gate_data)
        text = "\n".join(lines)

        assert "PASSING GATES (3)" in text, "Section header should say 3, not 0"
        assert "myopia:ambiguity-mines.py" in text
        assert "laziness:dead-code.py" in text

    def test_passing_count_matches_summary_passed(self) -> None:
        """The PASSING GATES header count must equal summary['passed']."""
        passed_names = [f"cat:gate-{i}" for i in range(5)]
        gate_data = _make_gate_data(passed=5, passed_gates=passed_names)
        lines = _format_gate_section(gate_data)
        text = "\n".join(lines)

        assert "PASSING GATES (5)" in text

    def test_no_passing_gates_section_when_none_passed(self) -> None:
        """When nothing passed, the PASSING GATES section must be absent."""
        gate_data = _make_gate_data(
            passed=0,
            failed=1,
            failing_results=[_failing("myopia:x")],
        )
        lines = _format_gate_section(gate_data)
        text = "\n".join(lines)

        assert "PASSING GATES" not in text


# ── Bug 2: summary line "failing" count matches the list actually shown ──────


class TestFormatGateSectionFailingCount:
    """Summary line ``failed`` and the FAILING GATES section must agree."""

    def test_summary_line_matches_failing_list(self) -> None:
        failing = [
            _failing("myopia:dependency-risk.py"),
            _failing("myopia:just-this-once.py"),
        ]
        gate_data = _make_gate_data(
            passed=18,
            failed=2,
            not_applicable=14,
            passed_gates=[f"cat:g{i}" for i in range(18)],
            failing_results=failing,
        )
        lines = _format_gate_section(gate_data)
        text = "\n".join(lines)

        # Summary line
        assert "2 failing" in text
        # Section header
        assert "FAILING GATES (2)" in text
        # Both gates present
        assert "myopia:dependency-risk.py" in text
        assert "myopia:just-this-once.py" in text

    def test_zero_failing_shows_no_failing_section(self) -> None:
        gate_data = _make_gate_data(
            passed=5, passed_gates=[f"c:g{i}" for i in range(5)]
        )
        lines = _format_gate_section(gate_data)
        text = "\n".join(lines)

        assert "FAILING GATES" not in text
        assert "0 failing" in text

    def test_warned_gates_not_counted_as_failing(self) -> None:
        """``warned`` status must not inflate the failed count or appear in
        the FAILING GATES section."""
        gate_data = _make_gate_data(
            passed=2,
            failed=0,
            warned=1,
            passed_gates=["a:x", "b:y"],
            warned_results=[_warned("myopia:ignored-feedback")],
        )
        lines = _format_gate_section(gate_data)
        text = "\n".join(lines)

        assert "FAILING GATES" not in text
        # warned gate may appear in a separate section but not as failing
        assert "0 failing" in text


# ── Bug 3: gate_data=None renders a graceful fallback, not a crash ───────────


class TestFormatGateSectionNoneInput:
    def test_none_gate_data_renders_fallback(self) -> None:
        lines = _format_gate_section(None)
        text = "\n".join(lines)
        # Should not raise and should mention the issue
        assert "gate scan failed" in text.lower() or "check" in text.lower()
