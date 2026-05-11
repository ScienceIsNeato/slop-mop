"""CI scan helpers for buff inspect."""

from __future__ import annotations

import argparse
from typing import Any, cast

from slopmop.cli.scan_triage import TriageError, run_triage

_SCAN_UNAVAILABLE_MARKERS = (
    "no workflow runs found for that pr/workflow",
    "no artifact matches any of the names or patterns provided",
    "no valid artifacts found to download",
    "artifact downloaded but slopmop-results.json not found",
)


def is_scan_unavailable_error(exc: TriageError) -> bool:
    """Return whether CI scan triage failed because the scan source is absent."""

    message = str(exc).lower()
    return any(marker in message for marker in _SCAN_UNAVAILABLE_MARKERS)


def scan_unavailable_detail(error: str) -> str:
    """Return a concise scan-unavailable detail line."""

    lines = [line.strip() for line in error.splitlines() if line.strip()]
    return lines[-1] if lines else error.strip()


def build_scan_unavailable_payload(
    *,
    pr_number: int | None,
    error: str,
) -> dict[str, Any]:
    """Build a buff payload when CI scan artifacts are unavailable."""

    return {
        "schema": "slopmop/ci-triage/v1",
        "source": "code-scanning",
        "pr_number": pr_number,
        "summary": {
            "failed": 0,
            "errors": 0,
            "warned": 0,
            "all_passed": None,
        },
        "actionable": [],
        "hard_failures": [],
        "lowest_coverage": [],
        "next_steps": [
            "CI scan artifact unavailable; use 'sm buff status' or "
            "'sm buff watch' to inspect check status.",
            "Review PR feedback below and continue with 'sm buff iterate' "
            "when threads remain.",
        ],
        "scan_unavailable": {
            "error": error,
        },
    }


def print_scan_unavailable(payload: dict[str, Any]) -> None:
    """Render the scan-unavailable fallback for human buff output."""

    unavailable = payload.get("scan_unavailable")
    error = ""
    if isinstance(unavailable, dict):
        unavailable_obj = cast(dict[str, Any], unavailable)
        error = str(unavailable_obj.get("error") or "")

    print("WARNING: CI scan artifact unavailable; continuing with PR feedback only.")
    detail = scan_unavailable_detail(error)
    if detail:
        print(f"Scan detail: {detail}")
    print("Next step for CI status: run 'sm buff status' or 'sm buff watch'.")


def run_inspect_scan(
    args: argparse.Namespace,
    resolved_pr_number: int,
    *,
    resolved_repo: str | None = None,
) -> tuple[int, dict[str, Any] | None]:
    """Run scan triage for buff inspect, keeping scan absence visible."""

    try:
        return run_triage(
            repo=resolved_repo or args.repo,
            run_id=args.run_id,
            pr_number=resolved_pr_number,
            workflow=args.workflow,
            artifact=args.artifact,
            show_low_coverage=False,
            json_out=None,
            print_output=False,
        )
    except TriageError as exc:
        if not is_scan_unavailable_error(exc):
            raise
        return (
            1,
            build_scan_unavailable_payload(
                pr_number=resolved_pr_number,
                error=str(exc),
            ),
        )
