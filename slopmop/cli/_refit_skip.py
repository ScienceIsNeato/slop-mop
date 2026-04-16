"""Skip-path helper for ``sm refit``."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, cast

import slopmop.cli.refit as _refit
from slopmop.core.lock import SmLockError, sm_lock
from slopmop.utils import iso_now


def cmd_refit_skip(args: argparse.Namespace, project_root: Path) -> int:
    """Mark the current refit gate as skipped and advance the plan."""

    if not _refit._ensure_remediation_phase(project_root):
        _refit._emit_standalone_protocol(
            args,
            project_root,
            event="blocked_on_phase",
            status="blocked_on_phase",
            next_action=_refit._MAINTENANCE_NEXT_ACTION,
            human_lines=["Refit is only available in remediation phase."],
        )
        return 1

    plan = _refit._load_continue_plan(args, project_root)
    if plan is None:
        return 1
    if not _refit._ensure_continue_branch(args, project_root, plan):
        return 1

    items = cast(List[Dict[str, Any]], plan.get("items", []))
    current_index = int(plan.get("current_index", 0))
    if current_index >= len(items):
        _refit._emit_standalone_protocol(
            args,
            project_root,
            event="skip_past_end",
            status=str(plan.get("status", "completed")),
            next_action="Run `sm refit --finish`.",
            human_lines=[
                "No current gate to skip — plan is already past its last item."
            ],
        )
        return 0

    current_item = items[current_index]
    gate = str(current_item.get("gate", "?"))
    reason = str(getattr(args, "skip", None) or "manual skip")

    try:
        with sm_lock(project_root, "refit"):
            current_item["status"] = "skipped"
            current_item["skip_reason"] = reason
            plan = _refit._advance_plan(plan)
            _refit._save_plan(project_root, plan)
    except SmLockError as exc:
        protocol: Dict[str, Any] = {
            "schema": _refit._SCHEMA_VERSION,
            "recorded_at": iso_now(),
            "event": "blocked_on_lock",
            "status": "blocked_on_lock",
            "project_root": str(project_root),
            "next_action": "Wait for the active sm process to finish, then rerun `sm refit --skip`.",
            "details": {"message": str(exc)},
        }
        _refit._emit_protocol(
            args,
            project_root,
            protocol,
            [f"Refit blocked: {exc}"],
        )
        return 1

    next_gate = plan.get("current_gate")
    next_line = (
        f"Next gate: {next_gate}. Run: sm refit --iterate"
        if next_gate
        else "No gates remain. Run: sm refit --finish"
    )
    protocol = _refit._snapshot_protocol(
        plan,
        event="gate_skipped",
        next_action="Run `sm refit --iterate` to resume, or disable the skipped check in .sb_config.json.",
        details={"skipped_gate": gate, "reason": reason},
    )
    _refit._emit_protocol(
        args,
        project_root,
        protocol,
        [
            f"Skipped gate: {gate}",
            f"Reason: {reason}",
            next_line,
            "Note: skipped gates still block --finish. If this gate is permanently "
            "out of scope, disable it in .sb_config.json.",
        ],
    )
    return 0
