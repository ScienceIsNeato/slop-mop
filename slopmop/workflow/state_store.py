"""Persistence layer for workflow state and repo phase.

Reads and writes the current ``WorkflowState`` and ``RepoPhase`` to
``.slopmop/workflow_state.json`` inside the project root.

All operations are best-effort: failures are logged but never propagate
to callers — a broken state file should never crash a tool invocation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, cast

from slopmop.workflow.state_machine import RepoPhase, WorkflowState

logger = logging.getLogger(__name__)

_STATE_FILE = "workflow_state.json"
_STATE_DIR = ".slopmop"
_STATE_KEY = "state"
_PHASE_KEY = "phase"
_BASELINE_KEY = "baseline_achieved"


def _state_path(project_root: str | Path) -> Path:
    return Path(project_root) / _STATE_DIR / _STATE_FILE


def read_state(project_root: str | Path) -> Optional[WorkflowState]:
    """Return the persisted workflow state, or ``None`` if not set."""
    data = _read_raw(project_root)
    raw = data.get(_STATE_KEY)
    if isinstance(raw, str):
        try:
            return WorkflowState(raw)
        except ValueError:
            pass
    return None


def read_phase(project_root: str | Path) -> RepoPhase:
    """Return the persisted repo phase, defaulting to ``REMEDIATION``.

    A new repo starts in REMEDIATION until a clean baseline is recorded.
    """
    data = _read_raw(project_root)
    raw = data.get(_PHASE_KEY)
    if isinstance(raw, str):
        try:
            return RepoPhase(raw)
        except ValueError:
            pass
    # Default: REMEDIATION — must earn MAINTENANCE
    return RepoPhase.REMEDIATION


def read_baseline_achieved(project_root: str | Path) -> bool:
    """Return True when a clean scour baseline has been recorded."""
    data = _read_raw(project_root)
    return bool(data.get(_BASELINE_KEY, False))


def write_state(project_root: str | Path, state: WorkflowState) -> None:
    """Persist *state* without touching other fields."""
    _update(project_root, {_STATE_KEY: state.value})
    logger.debug("Workflow state → %s", state.value)


def record_baseline(project_root: str | Path) -> None:
    """Mark that a clean scour baseline has been achieved; promote to MAINTENANCE."""
    _update(
        project_root,
        {
            _BASELINE_KEY: True,
            _PHASE_KEY: RepoPhase.MAINTENANCE.value,
        },
    )
    logger.debug("Baseline achieved — phase → maintenance")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_raw(project_root: str | Path) -> Dict[str, Any]:
    path = _state_path(project_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return cast(Dict[str, Any], data)
    except Exception as exc:
        logger.debug("Could not read workflow state: %s", exc)
    return {}


def _update(project_root: str | Path, updates: Dict[str, Any]) -> None:
    path = _state_path(project_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = _read_raw(project_root)
        existing.update(updates)
        path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.debug("Could not write workflow state: %s", exc)
