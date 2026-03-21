"""Iteration pipeline for the refit remediation process.

Contains the per-plan-item processing logic that drives `sm refit --iterate`.
Separated from the main refit module to keep file size within code-sprawl
limits.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

import slopmop.cli.refit as _refit


def _block_continue_plan(
    args: argparse.Namespace,
    project_root: Path,
    plan: Dict[str, Any],
    *,
    event: str,
    status: str,
    next_action: str,
    human_lines: List[str],
    details: Dict[str, Any],
    current_item: Optional[Dict[str, Any]] = None,
    artifact_path: Optional[Path] = None,
    increment_attempt: bool = False,
) -> int:
    if current_item is not None:
        current_item["status"] = status
        if artifact_path is not None:
            current_item["last_artifact"] = str(artifact_path)
        if increment_attempt:
            current_item["attempt_count"] = (
                int(current_item.get("attempt_count", 0)) + 1
            )
    plan["status"] = status
    _refit._save_plan(project_root, plan)
    protocol = _refit._snapshot_protocol(
        plan,
        event=event,
        next_action=next_action,
        details=details,
    )
    _refit._emit_protocol(args, project_root, protocol, human_lines)
    return 1


def _block_on_repo_state_error(
    args: argparse.Namespace,
    project_root: Path,
    plan: Dict[str, Any],
    *,
    error: RuntimeError,
    current_item: Optional[Dict[str, Any]] = None,
    gate: Optional[str] = None,
    artifact_path: Optional[Path] = None,
) -> int:
    lines = [
        "Refit blocked: could not read repository state safely.",
        str(error),
    ]
    if gate:
        lines.insert(0, f"Refit blocked on {gate}: repository state check failed.")
    return _block_continue_plan(
        args,
        project_root,
        plan,
        event="blocked_on_repo_state_error",
        status="blocked_on_repo_state_error",
        next_action="Resolve the repository state problem, then rerun `sm refit --iterate`.",
        human_lines=lines,
        details={
            "reason": "repo_state_unreadable",
            "error": str(error),
            "gate": gate,
            "artifact": str(artifact_path) if artifact_path is not None else None,
        },
        current_item=current_item,
        artifact_path=artifact_path,
    )


def _advance_without_commit(
    args: argparse.Namespace,
    project_root: Path,
    plan: Dict[str, Any],
    current_item: Dict[str, Any],
    gate: str,
    artifact_path: Path,
) -> int:
    current_item["status"] = "completed_no_changes"
    current_item["last_artifact"] = str(artifact_path)
    current_item["attempt_count"] = int(current_item.get("attempt_count", 0)) + 1
    plan = _refit._advance_plan(plan)
    _refit._save_plan(project_root, plan)
    protocol = _refit._snapshot_protocol(
        plan,
        event="advanced_without_commit",
        next_action=(
            "Run `sm refit --iterate` again to keep advancing the plan."
            if plan.get("status") != "completed"
            else _refit._POST_REFIT_NEXT_ACTION
        ),
        details={"gate": gate, "artifact": str(artifact_path)},
    )
    _refit._emit_protocol(
        args,
        project_root,
        protocol,
        [f"Refit advanced {gate}: gate already passes with no new commit required."],
    )
    return 0 if plan.get("status") == "completed" else _refit._CONTINUE_LOOP


def _commit_and_advance(
    args: argparse.Namespace,
    project_root: Path,
    plan: Dict[str, Any],
    current_item: Dict[str, Any],
    gate: str,
    artifact_path: Path,
) -> int:
    commit_code, detail = _refit._commit_current_changes(
        project_root, str(current_item.get("commit_message"))
    )
    current_item["attempt_count"] = int(current_item.get("attempt_count", 0)) + 1
    current_item["last_artifact"] = str(artifact_path)
    if commit_code != 0:
        return _block_continue_plan(
            args,
            project_root,
            plan,
            event="blocked_on_commit",
            status="blocked_on_commit",
            next_action="Resolve the git commit problem, then rerun `sm refit --iterate`.",
            human_lines=[
                line
                for line in [
                    f"Refit blocked on {gate}: automatic commit failed.",
                    detail,
                ]
                if line
            ],
            details={"gate": gate, "artifact": str(artifact_path), "detail": detail},
            current_item=current_item,
        )

    new_head = _refit._current_head(project_root)
    current_item["status"] = "completed"
    current_item["commit_sha"] = new_head
    plan["expected_head"] = new_head
    plan = _refit._advance_plan(plan)
    _refit._save_plan(project_root, plan)
    protocol = _refit._snapshot_protocol(
        plan,
        event="committed",
        next_action=(
            "Run `sm refit --iterate` again to keep advancing the plan."
            if plan.get("status") != "completed"
            else _refit._POST_REFIT_NEXT_ACTION
        ),
        details={
            "committed_gate": gate,
            "commit_message": current_item.get("commit_message"),
            "commit_sha": new_head,
            "artifact": str(artifact_path),
        },
    )
    _refit._emit_protocol(
        args,
        project_root,
        protocol,
        [f"Refit committed {gate}: {current_item['commit_message']}"],
    )
    return 0 if plan.get("status") == "completed" else _refit._CONTINUE_LOOP


def process_current_plan_item(
    args: argparse.Namespace,
    project_root: Path,
    plan: Dict[str, Any],
) -> int:
    """Process the current plan item: run the gate, handle outcomes."""
    items = cast(List[Dict[str, Any]], plan.get("items", []))
    current_index = int(plan.get("current_index", 0))
    if current_index >= len(items):
        return _refit._emit_continue_completion(args, project_root, plan)

    current_item = items[current_index]
    gate_value = current_item.get("gate")
    if not isinstance(gate_value, str) or not gate_value.strip():
        return _block_continue_plan(
            args,
            project_root,
            plan,
            event="blocked_on_plan_corruption",
            status="blocked_on_plan_corruption",
            next_action=(
                "The refit plan appears to be corrupt. Inspect or regenerate the plan "
                "before rerunning `sm refit --iterate`."
            ),
            human_lines=[
                "Refit blocked: current plan item has no gate. The refit plan appears to be corrupt."
            ],
            details={
                "reason": "current_plan_item_missing_gate",
                "current_index": current_index,
                "current_item": current_item,
            },
            current_item=current_item,
        )
    gate = gate_value

    expected_head = cast(Optional[str], plan.get("expected_head"))
    live_head = _refit._current_head(project_root)
    if expected_head and live_head != expected_head:
        return _block_continue_plan(
            args,
            project_root,
            plan,
            event="blocked_on_head_drift",
            status="blocked_on_head_drift",
            next_action="Review the repo state, then rerun `sm refit --iterate` once HEAD is stable.",
            human_lines=[
                "Refit blocked: HEAD changed unexpectedly since the plan last advanced. "
                "Review the repo state before resuming."
            ],
            details={"expected_head": expected_head, "current_head": live_head},
        )

    try:
        status_before = _refit._worktree_status(project_root)
    except RuntimeError as exc:
        return _block_on_repo_state_error(
            args,
            project_root,
            plan,
            error=exc,
            current_item=current_item,
            gate=gate,
        )
    artifact_path = _refit._continue_scour_path(project_root)
    exit_code = _refit._run_scour(project_root, artifact_path, gate=gate)
    live_head_after_run = _refit._current_head(project_root)
    try:
        status_after = _refit._worktree_status(project_root)
    except RuntimeError as exc:
        return _block_on_repo_state_error(
            args,
            project_root,
            plan,
            error=exc,
            current_item=current_item,
            gate=gate,
            artifact_path=artifact_path,
        )

    if expected_head and live_head_after_run != expected_head:
        return _block_continue_plan(
            args,
            project_root,
            plan,
            event="blocked_on_head_drift",
            status="blocked_on_head_drift",
            next_action="Review the repo state, then rerun `sm refit --iterate` once HEAD is stable.",
            human_lines=[
                f"Refit blocked on {gate}: HEAD changed during execution. "
                "Review the repo state before resuming."
            ],
            details={
                "expected_head": expected_head,
                "current_head": live_head_after_run,
                "artifact": str(artifact_path),
            },
            current_item=current_item,
            artifact_path=artifact_path,
            increment_attempt=True,
        )
    if exit_code not in {0, 1}:
        return _block_continue_plan(
            args,
            project_root,
            plan,
            event="blocked_on_execution_error",
            status="blocked_on_execution_error",
            next_action="Inspect the artifact and execution environment, then rerun `sm refit --iterate`.",
            human_lines=[
                f"Refit blocked on {gate}: targeted scour errored instead of producing a normal gate result."
            ],
            details={"gate": gate, "artifact": str(artifact_path)},
            current_item=current_item,
            artifact_path=artifact_path,
            increment_attempt=True,
        )
    if exit_code == 1:
        lines = [
            f"Refit stopped on failing gate: {gate}",
            f"Inspect: {artifact_path}",
        ]
        if current_item.get("log_file"):
            lines.append(f"Latest log: {current_item['log_file']}")
        lines.append("Fix the issue, then rerun: sm refit --iterate")
        return _block_continue_plan(
            args,
            project_root,
            plan,
            event="blocked_on_failure",
            status="blocked_on_failure",
            next_action="Fix the failing gate, then rerun `sm refit --iterate`.",
            human_lines=lines,
            details={"gate": gate, "artifact": str(artifact_path)},
            current_item=current_item,
            artifact_path=artifact_path,
            increment_attempt=True,
        )
    if not status_before and status_after:
        return _block_continue_plan(
            args,
            project_root,
            plan,
            event="blocked_on_dirty_worktree",
            status="blocked_on_dirty_worktree",
            next_action="Review unexpected worktree changes, then rerun `sm refit --iterate`.",
            human_lines=[
                f"Refit blocked on {gate}: worktree changed during validation even though the item started clean."
            ],
            details={
                "gate": gate,
                "status_before": status_before,
                "status_after": status_after,
                "artifact": str(artifact_path),
            },
            current_item=current_item,
            artifact_path=artifact_path,
            increment_attempt=True,
        )
    if status_before and not _refit._status_is_same(status_before, status_after):
        return _block_continue_plan(
            args,
            project_root,
            plan,
            event="blocked_on_dirty_worktree",
            status="blocked_on_dirty_worktree",
            next_action="Review the changed worktree state, then rerun `sm refit --iterate`.",
            human_lines=[
                f"Refit blocked on {gate}: worktree changed during validation beyond the planned remediation edits."
            ],
            details={
                "gate": gate,
                "status_before": status_before,
                "status_after": status_after,
                "artifact": str(artifact_path),
            },
            current_item=current_item,
            artifact_path=artifact_path,
            increment_attempt=True,
        )
    if not status_after:
        return _advance_without_commit(
            args, project_root, plan, current_item, gate, artifact_path
        )
    return _commit_and_advance(
        args, project_root, plan, current_item, gate, artifact_path
    )
