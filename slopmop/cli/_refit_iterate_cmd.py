"""Handler for ``sm refit --iterate``.

Extracted from ``refit.py`` to keep that file within the code-line limit.
All imports from ``refit`` are lazy (inside the function body) to avoid
circular-import issues — both modules are fully initialised by the time
any function here is called.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict


def _emit_drift_warning(
    args: argparse.Namespace, plan: Dict[str, Any], project_root: Path
) -> None:
    """Emit a non-blocking config-drift warning for the current iterate run."""
    import slopmop.cli.refit as _r
    from slopmop.cli.scan_triage import write_json_out

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
        drift_protocol.setdefault("protocol_file", str(_r._protocol_path(project_root)))
        _r._save_protocol(project_root, drift_protocol)
        write_json_out(getattr(args, "output_file", None), drift_protocol)
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
        with _r.sm_lock(project_root, "refit"):  # type: ignore[attr-defined]
            while True:
                result = process_current_plan_item(args, project_root, plan)
                if result == _r._CONTINUE_LOOP:
                    continue
                return result
    except _r.SmLockError as exc:  # type: ignore[attr-defined]
        protocol: Dict[str, Any] = {
            "schema": _r._SCHEMA_VERSION,
            "recorded_at": _r._iso_now(),
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
