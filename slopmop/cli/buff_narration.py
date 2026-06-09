"""Human narration helpers for buff command state."""

from __future__ import annotations

from typing import Any, cast

from slopmop.cli.ci import _categorize_checks
from slopmop.cli.scan_triage import PRResolutionSource
from slopmop.core.result import CheckResult, CheckStatus


def pr_resolution_reason(
    pr_number: int,
    source: PRResolutionSource,
    requested_pr_number: int | None,
    *,
    assume_latest: bool,
) -> str:
    """Explain why a PR resolution source was chosen."""

    if source == "explicit":
        return (
            f"Explicit PR #{requested_pr_number or pr_number} was provided, "
            "so buff validated that it is still open and selected it."
        )
    if source == "branch":
        return (
            "No explicit PR was provided, so buff looked up the current branch "
            f"and found open PR #{pr_number}."
        )
    if source == "configured":
        return (
            "No explicit PR or open current-branch PR was available, so buff "
            f"used configured working PR #{pr_number} after validating it."
        )
    if assume_latest:
        return (
            "No explicit PR, current-branch PR, or configured working PR was "
            f"available, so buff assumed the most recently updated open PR #{pr_number}."
        )
    return (
        "Buff selected the resolved open PR after checking explicit, branch, "
        "and configured PR sources."
    )


def print_pr_selection_trace(
    *,
    repo: str,
    current_branch: str | None,
    json_output: bool,
    requested_pr_number: int | None,
    resolved_pr_number: int,
    source: PRResolutionSource,
    assume_latest: bool,
) -> None:
    """Print how buff selected a PR for human output."""

    if json_output:
        return
    requested = f"#{requested_pr_number}" if requested_pr_number is not None else "none"
    order = ["explicit argument", "current branch", "configured working PR"]
    if assume_latest:
        order.append("most recently updated open PR")
    print("== Buff PR selection ==")
    print(f"Repository: {repo}")
    print(f"Current branch: {current_branch or 'unknown'}")
    print(f"Requested PR: {requested}")
    print(f"Candidate order: {' -> '.join(order)}")
    print(f"Selected PR: #{resolved_pr_number} ({source})")
    if source == "latest_open":
        print(
            "WARNING: no PR matched the current branch and no working PR is selected. "
            f"Assuming most recently updated open PR #{resolved_pr_number}."
        )
    print(
        "Why: "
        + pr_resolution_reason(
            resolved_pr_number,
            source,
            requested_pr_number,
            assume_latest=assume_latest,
        )
    )
    print()


def feedback_state_label(feedback_result: CheckResult) -> tuple[str, str]:
    """Return a compact human status for PR feedback."""

    if feedback_result.status == CheckStatus.PASSED:
        return "resolved", "myopia:ignored-feedback found no unresolved threads"
    if feedback_result.status == CheckStatus.FAILED:
        detail = feedback_result.status_detail or feedback_result.error
        return "unresolved", detail or "unresolved PR review threads remain"
    detail = feedback_result.error or feedback_result.status_detail
    return "error", detail or "could not verify PR feedback"


def format_feedback_state(feedback_result: CheckResult) -> str:
    """Format a one-line PR feedback state."""

    state, detail = feedback_state_label(feedback_result)
    return f"PR feedback: {state} - {detail}"


def print_inspect_state_summary(
    *,
    scan_exit: int,
    payload: dict[str, Any],
    feedback_result: CheckResult,
    json_output: bool,
) -> None:
    """Print buff's overall PR state after inspect has enough evidence."""

    if json_output:
        return
    scan_state, scan_detail = _scan_state_label(scan_exit, payload)
    feedback_state, feedback_detail = feedback_state_label(feedback_result)
    overall_state, overall_detail = _inspect_overall_state(scan_state, feedback_state)
    print("== Buff PR state ==")
    print(f"Scan artifact: {scan_state} - {scan_detail}")
    print(f"PR feedback: {feedback_state} - {feedback_detail}")
    print(f"Overall: {overall_state} - {overall_detail}")
    print()


def print_ci_state_summary(checks: list[dict[str, Any]]) -> None:
    """Print a one-line CI interpretation before detailed status output."""

    state, detail = _ci_state_label(checks)
    print(f"Overall PR state: {state} - {detail}")
    print()


def _scan_state_label(scan_exit: int, payload: dict[str, Any]) -> tuple[str, str]:
    """Return a compact human status for the CI scan artifact."""

    unavailable = payload.get("scan_unavailable")
    if unavailable:
        kind = ""
        if isinstance(unavailable, dict):
            kind = str(cast(dict[str, Any], unavailable).get("kind") or "")
        if kind == "artifact_missing":
            return "missing", "CI scan ran but its results artifact is missing"
        return "unavailable", "no code-scanning run for this repo"
    if scan_exit == 0:
        return "clean", "CI scan artifact has no actionable signals"
    return "needs work", "CI scan artifact contains actionable signals"


def _inspect_overall_state(
    scan_state: str,
    feedback_state: str,
) -> tuple[str, str]:
    """Summarize the full inspect state in one line."""

    if scan_state == "clean" and feedback_state == "resolved":
        return "clean", "CI scan signals and PR feedback are resolved"
    if scan_state == "missing":
        return (
            "blocked",
            "CI scan ran but its results artifact is missing — fix the upload",
        )
    if scan_state == "unavailable":
        if feedback_state == "resolved":
            return (
                "resolved",
                "PR feedback resolved; no code-scanning gate to verify",
            )
        return (
            "needs work",
            "no code-scanning run; PR feedback still needs attention",
        )
    if feedback_state == "error":
        return "blocked", "buff could not verify PR feedback"
    return "needs work", "CI scan signals or PR feedback still need attention"


def _ci_state_label(checks: list[dict[str, Any]]) -> tuple[str, str]:
    """Return buff's overall CI interpretation for a check set."""

    completed, in_progress, failed = _categorize_checks(checks)
    if failed:
        return (
            "blocked by CI",
            f"{len(failed)} failed, {len(in_progress)} pending, {len(completed)} passed",
        )
    if in_progress:
        return (
            "waiting on CI",
            f"{len(in_progress)} pending, {len(completed)} passed",
        )
    return "CI clean", f"{len(completed)}/{len(checks)} checks completed successfully"
