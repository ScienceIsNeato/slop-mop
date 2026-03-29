"""Staged precheck helpers for ``sm refit --start``."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

from slopmop.doctor.gate_preflight import (
    GatePreflightRecord,
    gather_gate_preflight_records,
)

_PRECHECK_SCHEMA = "refit-precheck/v1"
_NESTED_VALIDATE_OWNER = "refit_precheck"


def _precheck_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def precheck_path(project_root: Path) -> Path:
    return project_root / ".slopmop" / "refit" / "precheck.json"


def _probe_artifact_path(project_root: Path, gate: str) -> Path:
    safe_gate = re.sub(r"[^A-Za-z0-9._-]+", "_", gate)
    return project_root / ".slopmop" / "refit" / "precheck" / f"{safe_gate}.json"


def load_precheck(project_root: Path) -> Optional[Dict[str, Any]]:
    path = precheck_path(project_root)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return cast(Dict[str, Any], raw) if isinstance(raw, dict) else None


def save_precheck(project_root: Path, precheck: Dict[str, Any]) -> None:
    path = precheck_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(precheck, indent=2, sort_keys=True), encoding="utf-8")


def _run_gate_probe(project_root: Path, gate: str, artifact_path: Path) -> int:
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "slopmop.sm",
        "scour",
        "--no-auto-fix",
        "--no-cache",
        "--json-file",
        str(artifact_path),
        "--project-root",
        str(project_root),
        "-g",
        gate,
    ]
    env = os.environ.copy()
    env["SLOPMOP_SKIP_REPO_LOCK"] = "1"
    env["SLOPMOP_NESTED_VALIDATE_OWNER"] = _NESTED_VALIDATE_OWNER
    result = subprocess.run(
        command,
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode


def _previous_entry(
    previous: Optional[Dict[str, Any]], gate: str
) -> Optional[Dict[str, Any]]:
    if not previous:
        return None
    raw_entries = previous.get("gates")
    if not isinstance(raw_entries, list):
        return None
    for entry_any in cast(List[Dict[str, Any]], raw_entries):
        if not isinstance(entry_any, dict):
            continue
        if entry_any.get("gate") == gate:
            return entry_any
    return None


def _preserved_review_status(
    record: GatePreflightRecord,
    previous_entry: Optional[Dict[str, Any]],
) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    if previous_entry is None:
        return "pending", None, None, None
    if previous_entry.get("config_fingerprint") != record.config_fingerprint:
        return "pending", None, None, None
    status = str(previous_entry.get("review_status") or "pending")
    if status not in {"approved", "blocked_disabled"}:
        return "pending", None, None, None
    return (
        status,
        cast(Optional[str], previous_entry.get("reviewed_at")),
        cast(Optional[str], previous_entry.get("blocker_issue")),
        cast(Optional[str], previous_entry.get("blocker_reason")),
    )


def _build_gate_entry(
    project_root: Path,
    record: GatePreflightRecord,
    previous: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    previous_entry = _previous_entry(previous, record.gate)
    review_status, reviewed_at, blocker_issue, blocker_reason = (
        _preserved_review_status(record, previous_entry)
    )

    probe_status = record.runnability_status
    probe_exit_code: Optional[int] = None
    artifact_value: Optional[str] = None
    if record.enabled and record.applicable and not record.missing_tools:
        artifact = _probe_artifact_path(project_root, record.gate)
        probe_exit_code = _run_gate_probe(project_root, record.gate, artifact)
        artifact_value = str(artifact)
        probe_status = "runnable" if probe_exit_code in {0, 1} else "blocked"

    if not record.enabled and review_status != "blocked_disabled":
        review_status = "pending"
        reviewed_at = None
        blocker_issue = None
        blocker_reason = None
    if record.enabled and probe_status != "runnable":
        review_status = "pending"
        reviewed_at = None
        blocker_issue = None
        blocker_reason = None
    if record.enabled and probe_status == "runnable" and review_status != "approved":
        review_status = "pending"
        reviewed_at = None
        blocker_issue = None
        blocker_reason = None

    return {
        "gate": record.gate,
        "display_name": record.display_name,
        "enabled": record.enabled,
        "applicable": record.applicable,
        "skip_reason": record.skip_reason,
        "config_fingerprint": record.config_fingerprint,
        "missing_tools": list(record.missing_tools),
        "probe_status": probe_status,
        "probe_exit_code": probe_exit_code,
        "probe_artifact": artifact_value,
        "review_status": review_status,
        "reviewed_at": reviewed_at,
        "blocker_issue": blocker_issue,
        "blocker_reason": blocker_reason,
    }


def build_precheck(
    project_root: Path, previous: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    entries = [
        _build_gate_entry(project_root, record, previous)
        for record in gather_gate_preflight_records(project_root)
    ]
    precheck: Dict[str, Any] = {
        "schema": _PRECHECK_SCHEMA,
        "recorded_at": _precheck_timestamp(),
        "project_root": str(project_root),
        "gates": entries,
    }
    precheck["status"] = precheck_status(precheck)
    return precheck


def apply_review_actions(
    precheck: Dict[str, Any],
    *,
    approve_gates: Sequence[str],
    blocker_gate: Optional[str],
    blocker_issue: Optional[str],
    blocker_reason: Optional[str],
) -> Optional[str]:
    entries_raw = precheck.get("gates")
    if not isinstance(entries_raw, list):
        return "Refit precheck state is corrupt."
    entries = cast(List[Dict[str, Any]], entries_raw)
    by_gate = {str(entry.get("gate")): entry for entry in entries}

    for gate in approve_gates:
        entry = by_gate.get(gate)
        if entry is None:
            return f"Cannot approve unknown precheck gate: {gate}"
        if not bool(entry.get("enabled")):
            return f"Cannot approve disabled gate: {gate}"
        if str(entry.get("probe_status")) != "runnable":
            return f"Cannot approve gate that is not runnable: {gate}"
        entry["review_status"] = "approved"
        entry["reviewed_at"] = _precheck_timestamp()
        entry["blocker_issue"] = None
        entry["blocker_reason"] = None

    if blocker_gate is not None:
        entry = by_gate.get(blocker_gate)
        if entry is None:
            return f"Cannot record blocker for unknown precheck gate: {blocker_gate}"
        if bool(entry.get("enabled")):
            return (
                f"Disable {blocker_gate} in .sb_config.json first, then rerun "
                "sm refit --start --record-blocker ..."
            )
        if not blocker_issue or not blocker_issue.strip():
            return "--blocker-issue is required when recording a tooling blocker."
        if not blocker_reason or not blocker_reason.strip():
            return "--blocker-reason is required when recording a tooling blocker."
        entry["review_status"] = "blocked_disabled"
        entry["reviewed_at"] = _precheck_timestamp()
        entry["blocker_issue"] = blocker_issue.strip()
        entry["blocker_reason"] = blocker_reason.strip()

    precheck["status"] = precheck_status(precheck)
    return None


def blocked_runnability_entries(precheck: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = precheck.get("gates")
    if not isinstance(raw, list):
        return []
    entries = cast(List[Dict[str, Any]], raw)
    return [
        entry
        for entry in entries
        if bool(entry.get("applicable"))
        and bool(entry.get("enabled"))
        and str(entry.get("probe_status")) == "blocked"
    ]


def pending_fidelity_entries(precheck: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = precheck.get("gates")
    if not isinstance(raw, list):
        return []
    entries = cast(List[Dict[str, Any]], raw)
    pending: List[Dict[str, Any]] = []
    for entry in entries:
        if not bool(entry.get("applicable")):
            continue
        if bool(entry.get("enabled")):
            if (
                str(entry.get("probe_status")) == "runnable"
                and str(entry.get("review_status")) != "approved"
            ):
                pending.append(entry)
            continue
        if str(entry.get("review_status")) != "blocked_disabled":
            pending.append(entry)
    return pending


def approved_entries(precheck: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = precheck.get("gates")
    if not isinstance(raw, list):
        return []
    return [
        entry
        for entry in cast(List[Dict[str, Any]], raw)
        if isinstance(entry, dict) and str(entry.get("review_status")) == "approved"
    ]


def blocker_entries(precheck: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = precheck.get("gates")
    if not isinstance(raw, list):
        return []
    return [
        entry
        for entry in cast(List[Dict[str, Any]], raw)
        if isinstance(entry, dict)
        and str(entry.get("review_status")) == "blocked_disabled"
    ]


def precheck_status(precheck: Dict[str, Any]) -> str:
    if blocked_runnability_entries(precheck):
        return "blocked_on_gate_runnability"
    if pending_fidelity_entries(precheck):
        return "blocked_on_gate_fidelity"
    return "ready_for_plan"
