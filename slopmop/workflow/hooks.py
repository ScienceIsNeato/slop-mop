"""State-machine hooks for swab, scour, and buff.

Each tool invocation calls the appropriate hook after it completes.  The hook
maps the tool outcome to a ``WorkflowEvent``, advances the machine, and persists
the new state.  All hooks are best-effort — they never raise.

Integration points
------------------
``sm swab``   → call :func:`on_swab_complete` after ``executor.run_checks``
``sm scour``  → call :func:`on_scour_complete` after ``executor.run_checks``
``sm buff``   → call :func:`on_buff_complete` after the buff action resolves
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Union

from slopmop.workflow.state_machine import (
    MACHINE,
    RepoPhase,
    WorkflowEvent,
    WorkflowState,
)
from slopmop.workflow.state_store import (
    read_phase,
    read_state,
    record_baseline,
    write_state,
)

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]


def _current_state(project_root: PathLike) -> WorkflowState:
    """Return persisted state, defaulting to IDLE when unknown."""
    return read_state(project_root) or WorkflowState.IDLE


def _current_phase(project_root: PathLike) -> RepoPhase:
    """Return persisted repo phase."""
    return read_phase(project_root)


def on_swab_complete(project_root: PathLike, passed: bool) -> None:
    """Advance state after ``sm swab`` completes.

    Args:
        project_root: Project root directory.
        passed:       True when all swab gates are green.
    """
    try:
        state = _current_state(project_root)
        event = WorkflowEvent.SWAB_PASSED if passed else WorkflowEvent.SWAB_FAILED
        result = MACHINE.advance(state, event)
        if result:
            next_state, next_action = result
            write_state(project_root, next_state)
            logger.debug(
                "swab hook: %s + %s → %s  (next: %s)",
                state.value,
                event.value,
                next_state.value,
                next_action,
            )
        else:
            logger.debug(
                "swab hook: no transition from %s on %s — state unchanged",
                state.value,
                event.value,
            )
    except Exception as exc:
        logger.debug("swab hook error (ignored): %s", exc)


def on_scour_complete(
    project_root: PathLike, passed: bool, all_gates_enabled: bool = False
) -> None:
    """Advance state after ``sm scour`` completes.

    Args:
        project_root:      Project root directory.
        passed:            True when all scour gates are green (warnings allowed).
        all_gates_enabled: True when no gates were skipped/disabled for this run.
                           When both ``passed`` and ``all_gates_enabled`` are True,
                           the repo transitions to MAINTENANCE phase (baseline achieved).
    """
    try:
        state = _current_state(project_root)
        phase = _current_phase(project_root)
        event = WorkflowEvent.SCOUR_PASSED if passed else WorkflowEvent.SCOUR_FAILED
        result = MACHINE.advance(state, event, phase)
        if result:
            next_state, next_action = result
            write_state(project_root, next_state)
            logger.debug(
                "scour hook: %s + %s → %s  (next: %s)",
                state.value,
                event.value,
                next_state.value,
                next_action,
            )
        else:
            # scour can be run from any state (e.g. re-runs) — treat a pass
            # as reaching SCOUR_CLEAN regardless of prior state.
            if passed:
                write_state(project_root, WorkflowState.SCOUR_CLEAN)
                logger.debug(
                    "scour hook: no formal transition from %s — setting SCOUR_CLEAN",
                    state.value,
                )

        # Promote to MAINTENANCE when the first fully-clean baseline lands.
        if passed and all_gates_enabled and phase == RepoPhase.REMEDIATION:
            record_baseline(project_root)
    except Exception as exc:
        logger.debug("scour hook error (ignored): %s", exc)


def on_buff_complete(project_root: PathLike, has_issues: bool) -> None:
    """Advance state after ``sm buff`` completes.

    Args:
        project_root: Project root directory.
        has_issues:   True when buff found CI failures or unresolved threads.
    """
    try:
        state = _current_state(project_root)
        event = (
            WorkflowEvent.BUFF_HAS_ISSUES
            if has_issues
            else WorkflowEvent.BUFF_ALL_GREEN
        )
        result = MACHINE.advance(state, event)
        if result:
            next_state, next_action = result
            write_state(project_root, next_state)
            logger.debug(
                "buff hook: %s + %s → %s  (next: %s)",
                state.value,
                event.value,
                next_state.value,
                next_action,
            )
        else:
            # buff can be re-run from any state — set PR_OPEN or BUFF_ITERATING
            # based on outcome when no formal transition matches.
            fallback = (
                WorkflowState.BUFF_FAILING if has_issues else WorkflowState.PR_READY
            )
            write_state(project_root, fallback)
            logger.debug(
                "buff hook: no formal transition from %s — setting %s",
                state.value,
                fallback.value,
            )
    except Exception as exc:
        logger.debug("buff hook error (ignored): %s", exc)


def on_iteration_started(project_root: PathLike) -> None:
    """Advance state when ``sm buff iterate`` prepares a work batch.

    Args:
        project_root: Project root directory.
    """
    try:
        state = _current_state(project_root)
        event = WorkflowEvent.ITERATION_STARTED
        result = MACHINE.advance(state, event)
        if result:
            next_state, _ = result
            write_state(project_root, next_state)
        # No fallback — state stays as-is when no transition matches
    except Exception as exc:
        logger.debug("iteration hook error (ignored): %s", exc)
