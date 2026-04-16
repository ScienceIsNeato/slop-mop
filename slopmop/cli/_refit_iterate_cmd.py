"""Iteration handler for ``sm refit --iterate``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict

from slopmop.core.lock import SmLockError, sm_lock
from slopmop.utils import iso_now


def _emit_drift_warning(
    args: argparse.Namespace, plan: Dict[str, Any], project_root: Path
) -> None:
    """Emit a non-blocking config-drift warning for the current iterate run."""
    import slopmop.cli.refit as _r

    expected = plan.get("config_hash", "")
    if not (expected and _r._config_hash(project_root) != expected):
        return

    drift_protocol = _r._snapshot_protocol(
        plan,
        event="warn_config_drift",
        next_action=(
            "If the change was intentional, continue with `sm refit --iterate`. "
            "If it may affect the gate list or thresholds, regenerate the plan "
            "with `sm refit --start`."
        ),
        details={
            "expected_hash": expected,
            "current_hash": _r._config_hash(project_root),
        },
    )
    _drift_human_lines = [
        "Warning: .sb_config.json has changed since the refit plan was "
        "generated. The gate list may be stale.",
        "If the change affects gate thresholds or disables a gate that is "
        "still in the plan, regenerate with `sm refit --start`.",
    ]
    if getattr(args, "json_output", False):
        # Save to protocol file only; do not write to stdout here.
        # The main protocol event comes from process_current_plan_item and
        # must be the sole JSON object on stdout — a second object would
        # make the output unparseable for consumers.
        drift_protocol.setdefault("protocol_file", str(_r._protocol_path(project_root)))
        _r._save_protocol(project_root, drift_protocol)
        print(
            "Warning: .sb_config.json has changed since the refit plan was"
            " generated. The gate list may be stale.",
            file=sys.stderr,
        )
    else:
        _r._emit_protocol(args, project_root, drift_protocol, _drift_human_lines)


def run_iterate(args: argparse.Namespace) -> int:
    import slopmop.cli.refit as _r

    project_root = _r._project_root(args)
    if not _r._ensure_remediation_phase(project_root):
        _r._emit_standalone_protocol(
            args,
            project_root,
            event="blocked_on_phase",
            status="blocked_on_phase",
            next_action=_r._MAINTENANCE_NEXT_ACTION,
            human_lines=[
                "Refit is only available while the repo is in remediation phase. "
                "Run the normal swab/scour/buff workflow for maintenance repos."
            ],
        )
        return 1

    plan = _r._load_continue_plan(args, project_root)
    if plan is None:
        return 1

    if plan.get("status") == "completed":
        _r._emit_standalone_protocol(
            args,
            project_root,
            event="already_completed",
            status="already_completed",
            next_action="Run `sm refit --finish` to transition to maintenance mode.",
            human_lines=[
                "Refit plan is already completed. "
                "Run `sm refit --finish` to check results and transition to maintenance."
            ],
        )
        return 0

    if not _r._ensure_continue_branch(args, project_root, plan):
        return 1

    _emit_drift_warning(args, plan, project_root)

    from slopmop.cli._refit_iteration import process_current_plan_item

    try:
        with sm_lock(project_root, "refit"):
            while True:
                result = process_current_plan_item(args, project_root, plan)
                if result == _r._CONTINUE_LOOP:
                    continue
                return result
    except SmLockError as exc:
        protocol: Dict[str, Any] = {
            "schema": _r._SCHEMA_VERSION,
            "recorded_at": iso_now(),
            "event": "blocked_on_lock",
            "status": "blocked_on_lock",
            "project_root": str(project_root),
            "next_action": (
                "Wait for the active sm process to finish, "
                "then rerun `sm refit --iterate`."
            ),
            "details": {"message": str(exc)},
        }
        _r._emit_protocol(
            args,
            project_root,
            protocol,
            [f"Refit blocked: {exc}"],
        )
        return 1
