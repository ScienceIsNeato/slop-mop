"""Canonical state machine for the slop-mop development loop.

This module is the **single source of truth** for the swab → scour → buff
workflow.  Hooks, terminal checks, and diagram generators all derive from
the objects defined here — nothing is duplicated elsewhere.

Usage::

    from slopmop.workflow.state_machine import MACHINE, WorkflowEvent

    state = MACHINE.current_state(project_root)
    next_state, action = MACHINE.advance(state, WorkflowEvent.SWAB_PASSED)

Diagram generation::

    python scripts/gen_workflow_diagrams.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Tuple

from slopmop.constants import (
    ACTION_BUFF_INSPECT,
    ACTION_FIX_AND_SWAB,
    ACTION_GIT_COMMIT,
)

# ---------------------------------------------------------------------------
# Repo phase — the meta-mode that shapes agent guidance
# ---------------------------------------------------------------------------


class RepoPhase(str, Enum):
    """Whether the repo has ever reached a fully-clean baseline.

    REMEDIATION — The repo has not yet had a single ``sm scour`` run that
        passed with all checks enabled and all issues resolved.  Agents
        receive extra guidance: prioritised fix lists, effort framing, and
        progress indicators toward the first green baseline.

    MAINTENANCE — The baseline has been achieved at least once.  The loop
        runs normally; agents are trusted to advance autonomously.  This is
        the steady-state mode.
    """

    REMEDIATION = "remediation"
    MAINTENANCE = "maintenance"


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------


class WorkflowState(str, Enum):
    """Every possible position in the development loop.

    States are *conditions the agent is in*, not actions.  Actions (running
    tools, writing code) happen on the transitions between states.  Failure
    events land in distinct failure states so the diagram never has
    meaningless self-loops.
    """

    IDLE = "idle"
    """No pending slop-mop issues.  Agent writes code freely.
    Next: run ``sm swab`` when ready for a quality check,
    or ``sm scour`` when the feature is complete."""

    SWAB_FAILING = "swab_failing"
    """``sm swab`` reported failing gates.
    Next: fix the specific failures, then re-run ``sm swab``."""

    SWAB_CLEAN = "swab_clean"
    """``sm swab`` passed.  Code is quality-gate clean at swab level.
    Next: commit your changes."""

    SCOUR_FAILING = "scour_failing"
    """``sm scour`` reported failing gates.
    Next: fix the issues and re-enter the swab loop."""

    SCOUR_CLEAN = "scour_clean"
    """``sm scour`` passed.  Code is PR-ready.
    Next: push branch and open or update the PR."""

    PR_OPEN = "pr_open"
    """PR is open.  Waiting for CI to finish and/or review feedback.
    Next: run ``sm buff inspect`` to triage results."""

    BUFF_FAILING = "buff_failing"
    """Buff found issues (CI failures or unresolved review threads).
    Next: fix feedback and re-enter the swab loop."""

    PR_READY = "pr_ready"
    """Buff is clean — all CI green, no unresolved threads.
    Next: ``sm buff finalize --push`` to land the PR."""

    @property
    def position(self) -> int:
        """1-based position in the workflow loop (S1–S7)."""
        return _STATE_POSITIONS[self]

    @property
    def state_id(self) -> str:
        """Short identifier for display, e.g. ``"S3"``."""
        return f"S{self.position}"

    @property
    def next_action(self) -> str:
        """Default next action for this state (not event-dependent)."""
        return _STATE_NEXT_ACTIONS[self]

    @property
    def display_label(self) -> str:
        """Short human-readable label for diagram nodes."""
        return _STATE_DISPLAY_LABELS[self]


#: Position mapping — defines the S1–S8 numbering.
_STATE_POSITIONS: Dict[WorkflowState, int] = {
    WorkflowState.IDLE: 1,
    WorkflowState.SWAB_FAILING: 2,
    WorkflowState.SWAB_CLEAN: 3,
    WorkflowState.SCOUR_FAILING: 4,
    WorkflowState.SCOUR_CLEAN: 5,
    WorkflowState.PR_OPEN: 6,
    WorkflowState.BUFF_FAILING: 7,
    WorkflowState.PR_READY: 8,
}

#: Default next actions per state — used by ``state_id`` display and
#: ``sm status`` output.  These are the *default* actions; the transition
#: table's ``next_action`` field is context-dependent (varies by event).
_STATE_NEXT_ACTIONS: Dict[WorkflowState, str] = {
    WorkflowState.IDLE: "run sm swab",
    WorkflowState.SWAB_FAILING: ACTION_FIX_AND_SWAB,
    WorkflowState.SWAB_CLEAN: "git commit",
    WorkflowState.SCOUR_FAILING: ACTION_FIX_AND_SWAB,
    WorkflowState.SCOUR_CLEAN: "git push, then open or update PR",
    WorkflowState.PR_OPEN: "run sm buff status, then sm buff inspect",
    WorkflowState.BUFF_FAILING: ACTION_FIX_AND_SWAB,
    WorkflowState.PR_READY: "run sm buff finalize --push",
}

#: Short human-readable labels for diagram nodes and display.
_STATE_DISPLAY_LABELS: Dict[WorkflowState, str] = {
    WorkflowState.IDLE: "Ready to code",
    WorkflowState.SWAB_FAILING: "Swab failed \u2014 fix reported gates",
    WorkflowState.SWAB_CLEAN: "Swab passed",
    WorkflowState.SCOUR_FAILING: "Scour failed \u2014 fix and re-swab",
    WorkflowState.SCOUR_CLEAN: "Scour passed",
    WorkflowState.PR_OPEN: "PR open \u2014 awaiting CI/review",
    WorkflowState.BUFF_FAILING: "Buff found issues \u2014 fix and re-swab",
    WorkflowState.PR_READY: "PR ready to land",
}


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class WorkflowEvent(str, Enum):
    """Concrete outcomes that drive state transitions.

    Each tool invocation emits one event; the machine maps it to a new state
    and a ``next_action`` string the agent should follow.
    """

    SWAB_PASSED = "swab_passed"
    """``sm swab`` completed with all gates green."""

    SWAB_FAILED = "swab_failed"
    """``sm swab`` reported one or more failing gates."""

    GIT_COMMITTED = "git_committed"
    """The working tree is clean — all changes are committed."""

    SCOUR_PASSED = "scour_passed"
    """``sm scour`` completed with all gates green."""

    SCOUR_FAILED = "scour_failed"
    """``sm scour`` reported one or more failing gates."""

    PR_OPENED = "pr_opened"
    """A PR was opened or updated for the current branch."""

    BUFF_HAS_ISSUES = "buff_has_issues"
    """``sm buff`` found CI failures or unresolved review threads."""

    BUFF_ALL_GREEN = "buff_all_green"
    """``sm buff`` reports CI green and no unresolved threads."""

    ITERATION_STARTED = "iteration_started"
    """``sm buff iterate`` prepared the next work batch — time to code."""


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Transition:
    """A single edge in the state machine graph.

    Attributes:
        from_state:  State the machine must be in for this transition to fire.
        event:       The event that triggers the transition.
        to_state:    State the machine moves to after the transition.
        next_action: Human/agent-readable command or instruction for what to
                     do *immediately* after landing in ``to_state``.
        label:       Short label used on diagram arrows (defaults to event value).
        description: Longer human-readable explanation, used in generated docs.
        phases:      Which :class:`RepoPhase` values this transition applies to.
                     ``None`` means the transition applies to both phases.
    """

    from_state: WorkflowState
    event: WorkflowEvent
    to_state: WorkflowState
    next_action: str
    label: str = ""
    description: str = ""
    phases: Optional[FrozenSet[RepoPhase]] = None  # None → all phases

    def __post_init__(self) -> None:
        # Default label to the event value when not supplied
        if not self.label:
            object.__setattr__(self, "label", self.event.value.replace("_", " "))

    def applies_to_phase(self, phase: RepoPhase) -> bool:
        """Return True when this transition is valid in *phase*."""
        return self.phases is None or phase in self.phases


#: The complete transition table — the only place any of this is defined.
TRANSITIONS: List[Transition] = [
    # ── Swab from IDLE ─────────────────────────────────────────────────────
    Transition(
        from_state=WorkflowState.IDLE,
        event=WorkflowEvent.SWAB_PASSED,
        to_state=WorkflowState.SWAB_CLEAN,
        next_action=ACTION_GIT_COMMIT,
        label="passes",
        description="Swab is green — commit and move toward scour.",
    ),
    Transition(
        from_state=WorkflowState.IDLE,
        event=WorkflowEvent.SWAB_FAILED,
        to_state=WorkflowState.SWAB_FAILING,
        next_action=ACTION_FIX_AND_SWAB,
        label="fails",
        description="One or more gates failed — fix the reported issues.",
    ),
    # ── Swab from SWAB_FAILING ─────────────────────────────────────────────
    Transition(
        from_state=WorkflowState.SWAB_FAILING,
        event=WorkflowEvent.SWAB_PASSED,
        to_state=WorkflowState.SWAB_CLEAN,
        next_action=ACTION_GIT_COMMIT,
        label="passes",
        description="Fixes resolved the issues — commit.",
    ),
    Transition(
        from_state=WorkflowState.SWAB_FAILING,
        event=WorkflowEvent.SWAB_FAILED,
        to_state=WorkflowState.SWAB_FAILING,
        next_action=ACTION_FIX_AND_SWAB,
        label="fails",
        description="Fix attempt introduced new issues — iterate.",
    ),
    # ── Swab from SCOUR_FAILING ────────────────────────────────────────────
    Transition(
        from_state=WorkflowState.SCOUR_FAILING,
        event=WorkflowEvent.SWAB_PASSED,
        to_state=WorkflowState.SWAB_CLEAN,
        next_action=ACTION_GIT_COMMIT,
        label="passes",
        description="Scour-issue fixes are swab-clean — commit.",
    ),
    Transition(
        from_state=WorkflowState.SCOUR_FAILING,
        event=WorkflowEvent.SWAB_FAILED,
        to_state=WorkflowState.SWAB_FAILING,
        next_action=ACTION_FIX_AND_SWAB,
        label="fails",
        description="Fix attempt broke swab — address swab failures first.",
    ),
    # ── Swab from BUFF_FAILING ─────────────────────────────────────────────
    Transition(
        from_state=WorkflowState.BUFF_FAILING,
        event=WorkflowEvent.SWAB_PASSED,
        to_state=WorkflowState.SWAB_CLEAN,
        next_action=ACTION_GIT_COMMIT,
        label="passes",
        description="Feedback fixes are swab-clean — commit.",
    ),
    Transition(
        from_state=WorkflowState.BUFF_FAILING,
        event=WorkflowEvent.SWAB_FAILED,
        to_state=WorkflowState.SWAB_FAILING,
        next_action=ACTION_FIX_AND_SWAB,
        label="fails",
        description="Fix attempt broke swab — address swab failures first.",
    ),
    # ── Commit ─────────────────────────────────────────────────────────────
    Transition(
        from_state=WorkflowState.SWAB_CLEAN,
        event=WorkflowEvent.GIT_COMMITTED,
        to_state=WorkflowState.IDLE,
        next_action="continue coding, or run sm scour when feature is complete",
        label="committed",
        description="Changes committed — resume coding or run scour for PR.",
    ),
    # ── Scour (from IDLE when feature is complete) ─────────────────────────
    Transition(
        from_state=WorkflowState.IDLE,
        event=WorkflowEvent.SCOUR_PASSED,
        to_state=WorkflowState.SCOUR_CLEAN,
        next_action="git push && open or update PR",
        label="passes",
        description="Scour is green — push the branch and open the PR.",
    ),
    Transition(
        from_state=WorkflowState.IDLE,
        event=WorkflowEvent.SCOUR_FAILED,
        to_state=WorkflowState.SCOUR_FAILING,
        next_action=ACTION_FIX_AND_SWAB,
        label="fails",
        description="Scour found issues — fix and re-enter swab loop.",
    ),
    # ── PR open ────────────────────────────────────────────────────────────
    Transition(
        from_state=WorkflowState.SCOUR_CLEAN,
        event=WorkflowEvent.PR_OPENED,
        to_state=WorkflowState.PR_OPEN,
        next_action=ACTION_BUFF_INSPECT,
        label="PR opened/updated",
        description="PR is live — triage CI and review feedback with buff.",
    ),
    # ── Buff ───────────────────────────────────────────────────────────────
    Transition(
        from_state=WorkflowState.PR_OPEN,
        event=WorkflowEvent.BUFF_HAS_ISSUES,
        to_state=WorkflowState.BUFF_FAILING,
        next_action=ACTION_FIX_AND_SWAB,
        label="has issues",
        description="CI/review found problems — fix and re-enter swab loop.",
    ),
    Transition(
        from_state=WorkflowState.PR_OPEN,
        event=WorkflowEvent.BUFF_ALL_GREEN,
        to_state=WorkflowState.PR_READY,
        next_action="sm buff finalize --push",
        label="all green",
        description="CI is green and all threads are resolved — ready to land.",
    ),
    # ── Finalize ───────────────────────────────────────────────────────────
    Transition(
        from_state=WorkflowState.PR_READY,
        event=WorkflowEvent.PR_OPENED,
        to_state=WorkflowState.PR_OPEN,
        next_action=ACTION_BUFF_INSPECT,
        label="final push",
        description="Re-enter PR_OPEN after the final push to confirm CI is still green.",
    ),
]


# ---------------------------------------------------------------------------
# Runtime helpers
# ---------------------------------------------------------------------------


@dataclass
class StateMachine:
    """Immutable transition table with lookup helpers.

    This class wraps ``TRANSITIONS`` and exposes:

    * ``advance(state, event)`` — returns ``(next_state, next_action)``
    * ``transitions_from(state)`` — all outgoing transitions for a state
    * ``all_states`` / ``all_events`` — full enumerations for diagram generation
    """

    transitions: List[Transition] = field(default_factory=lambda: TRANSITIONS)

    def __post_init__(self) -> None:
        # Build a phase-aware index: (from_state, event) → list of transitions
        # (there can be at most one per phase, but the structure allows it).
        self._index: Dict[Tuple[WorkflowState, WorkflowEvent], Transition] = {
            (t.from_state, t.event): t for t in self.transitions
        }

    def advance(
        self,
        state: WorkflowState,
        event: WorkflowEvent,
        phase: RepoPhase = RepoPhase.MAINTENANCE,
    ) -> Optional[Tuple[WorkflowState, str]]:
        """Return ``(next_state, next_action)`` or ``None`` if no transition exists.

        Args:
            state:  Current workflow state.
            event:  The event that just occurred.
            phase:  Current repo phase — used to filter phase-specific transitions.
                    Defaults to ``MAINTENANCE`` (the steady-state mode).
        """
        t = self._index.get((state, event))
        if t is None:
            return None
        if not t.applies_to_phase(phase):
            return None
        return t.to_state, t.next_action

    def transitions_from(
        self,
        state: WorkflowState,
        phase: Optional[RepoPhase] = None,
    ) -> List[Transition]:
        """All outgoing transitions from *state*, optionally filtered by *phase*."""
        return [
            t
            for t in self.transitions
            if t.from_state == state and (phase is None or t.applies_to_phase(phase))
        ]

    @property
    def all_states(self) -> List[WorkflowState]:
        """Ordered list of all states that appear in the transition table."""
        seen: Dict[WorkflowState, None] = {}
        for t in self.transitions:
            seen.setdefault(t.from_state, None)
            seen.setdefault(t.to_state, None)
        return list(seen)

    @property
    def all_events(self) -> List[WorkflowEvent]:
        """Ordered list of all events that appear in the transition table."""
        seen: Dict[WorkflowEvent, None] = {}
        for t in self.transitions:
            seen.setdefault(t.event, None)
        return list(seen)


#: Global singleton — import this wherever you need the machine.
MACHINE = StateMachine()
