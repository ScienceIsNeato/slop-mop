"""Shared machine-language rail helpers for CI triage and commentary.

These utilities keep generation and consumption aligned across:
- CI code-scan triage payloads
- PR/scour commentary summaries
"""

from __future__ import annotations

from typing import Any, Dict, List

from slopmop.checks import ensure_checks_registered
from slopmop.core.registry import get_registry

ACTIONABLE_STATUSES = {"failed", "error", "warned"}
HARD_FAILURE_STATUSES = {"failed", "error"}


def actionable_detail(row: Dict[str, Any]) -> str:
    """Return the canonical actionable detail string for a gate result."""
    return str(
        row.get("error")
        or row.get("fix_suggestion")
        or row.get("status_detail")
        or "(no detail)"
    )


def filter_actionable_rows(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return actionable rows (failed/error/warned) from raw result rows."""
    return [
        row
        for row in results
        if str(row.get("status", "")).lower() in ACTIONABLE_STATUSES
    ]


def filter_hard_failures(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return hard-failure rows (failed/error) from raw result rows."""
    return [
        row
        for row in results
        if str(row.get("status", "")).lower() in HARD_FAILURE_STATUSES
    ]


def normalize_actionable_row(row: Dict[str, Any]) -> Dict[str, str]:
    """Normalize a raw gate result row into the shared rail schema."""
    return {
        "status": str(row.get("status", "unknown")).upper(),
        "gate": str(row.get("name", "unknown")),
        "detail": actionable_detail(row),
    }


def format_actionable_line(row: Dict[str, str]) -> str:
    """Format a normalized actionable row as a single guidance line."""
    return f"- {row['status']}: {row['gate']} :: {row['detail']}"


def sort_rows_by_remediation_order(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort gate-like rows by remediation order, preserving unknown-row order."""
    ensure_checks_registered()
    registry = get_registry()
    indexed_rows = list(enumerate(rows))
    return [
        row
        for _index, row in sorted(
            indexed_rows,
            key=lambda item: (
                registry.remediation_sort_key_for_name(str(item[1].get("name", "")))
                or (999_999, 999_999, f"{item[0]:06d}"),
                item[0],
            ),
        )
    ]


def default_next_steps(pr_number: int | None) -> List[str]:
    """Return shared next-step guidance for the CI triage loop."""
    if pr_number is not None:
        return [
            "Fix failed gates locally using targeted gate reruns from output",
            "If fixes take multiple passes, loop on sm swab until local issues are stable",
            "Run full validation locally: sm scour",
            f"Re-run PR inspection: sm buff inspect {pr_number}",
        ]

    return [
        "Fix failed gates locally using targeted gate reruns from output",
        "If fixes take multiple passes, loop on sm swab until local issues are stable",
        "Run full validation locally: sm scour",
        "Re-run PR inspection: sm buff inspect",
    ]
