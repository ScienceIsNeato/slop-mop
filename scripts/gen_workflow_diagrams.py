#!/usr/bin/env python3
"""Generate workflow diagrams from the slop-mop state machine.

Usage::

    python scripts/gen_workflow_diagrams.py           # writes docs/WORKFLOW.md
    python scripts/gen_workflow_diagrams.py --check   # exits non-zero if docs are stale

The diagrams are derived entirely from
``slopmop.workflow.state_machine.TRANSITIONS`` — the Python objects ARE the
source of truth.  Edit the state machine, re-run this script; the docs update
automatically.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

# Ensure repo root is on sys.path so the package is importable without install.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts._freshness import (  # noqa: E402
    report_missing,
    report_stale,
    report_up_to_date,
)
from slopmop.checks import ensure_checks_registered  # noqa: E402
from slopmop.checks.base import CheckRole, GateLevel  # noqa: E402
from slopmop.core.registry import get_registry  # noqa: E402
from slopmop.workflow.state_machine import (  # noqa: E402
    MACHINE,
    TRANSITIONS,
    WorkflowState,
)

OUTPUT_PATH = REPO_ROOT / "docs" / "WORKFLOW.md"

# ── State diagram ─────────────────────────────────────────────────────────


def _build_choice_maps(
    lines: list[str],
) -> tuple[dict, dict]:
    """Register ``<<choice>>`` pseudostates and return lookup maps.

    Returns ``(event_to_choice, choice_action_label)`` and appends the
    ``state ... <<choice>>`` declarations to *lines* as a side-effect.
    """
    from slopmop.workflow.state_machine import WorkflowEvent

    _OUTCOME_PAIRS: dict[str, tuple[WorkflowEvent, WorkflowEvent, str]] = {
        "swab_check": (
            WorkflowEvent.SWAB_PASSED,
            WorkflowEvent.SWAB_FAILED,
            "run sm swab",
        ),
        "scour_check": (
            WorkflowEvent.SCOUR_PASSED,
            WorkflowEvent.SCOUR_FAILED,
            "run sm scour",
        ),
        "buff_check": (
            WorkflowEvent.BUFF_ALL_GREEN,
            WorkflowEvent.BUFF_HAS_ISSUES,
            "run sm buff inspect",
        ),
    }
    event_to_choice: dict[WorkflowEvent, str] = {}
    choice_action_label: dict[str, str] = {}
    for choice_id, (e1, e2, action_label) in _OUTCOME_PAIRS.items():
        event_to_choice[e1] = choice_id
        event_to_choice[e2] = choice_id
        choice_action_label[choice_id] = action_label
        lines.append(f"    state {choice_id} <<choice>>")
    return event_to_choice, choice_action_label


def gen_flowchart() -> str:
    """Generate a Mermaid stateDiagram-v2 from the transition table.

    Every node and edge is derived from ``MACHINE.all_states`` and
    ``TRANSITIONS`` — zero hardcoded structure.  Tool executions that
    produce binary outcomes (pass/fail) are rendered as ``<<choice>>``
    pseudostates so ACTIONS appear as visual decision diamonds the agent
    passes through, while STATES remain as resting-place rectangles.
    """
    lines = ["stateDiagram-v2", "    direction TB"]

    # State nodes — include display_label and next_action for detail
    initial_sid: str | None = None
    for state in MACHINE.all_states:
        sid = state.value
        label = f"({state.state_id}) {state.display_label}"
        action = f"Next: {state.next_action}"
        lines.append(f'    state "{label}<br/>{action}" as {sid}')
        if state.position == 1:
            initial_sid = sid

    lines.append("")

    # Choice pseudostates for binary-outcome tool executions
    event_to_choice, choice_action_label = _build_choice_maps(lines)

    lines.append("")

    # Start marker — derived from position == 1 (the initial state)
    if initial_sid:
        lines.append(f"    [*] --> {initial_sid}")

    # Note on the initial state — slop-mop is idle while agent codes
    if initial_sid:
        lines.append(f"    note right of {initial_sid}")
        lines.append("        Agent writes code freely.")
        lines.append("        slop-mop is idle in this state.")
        lines.append("        All other states are slop-mop")
        lines.append("        telling the agent what to do")
        lines.append("        before or after code changes.")
        lines.append("    end note")

    lines.append("")

    # Edges — route through choice pseudostates for binary outcomes
    seen_edges: set[tuple[str, str, str]] = set()
    for t in TRANSITIONS:
        src = t.from_state.value
        dst = t.to_state.value
        choice_id = event_to_choice.get(t.event)

        if choice_id:
            # Source → choice diamond (label = the tool action, e.g. "run sm swab")
            action = choice_action_label[choice_id]
            in_key = (src, choice_id, action)
            if in_key not in seen_edges:
                seen_edges.add(in_key)
                lines.append(f"    {src} --> {choice_id} : {action}")

            # Choice diamond → target state (label = the outcome)
            out_key = (choice_id, dst, t.label)
            if out_key not in seen_edges:
                seen_edges.add(out_key)
                lines.append(f"    {choice_id} --> {dst} : {t.label}")
        else:
            # Direct edge — no binary outcome
            key = (src, dst, t.label)
            if key not in seen_edges:
                seen_edges.add(key)
                lines.append(f"    {src} --> {dst} : {t.label}")

    return "\n".join(lines)


# ── Transition table ──────────────────────────────────────────────────────


def gen_transition_table() -> str:
    """Generate a Markdown table of all transitions."""
    rows = [
        "| From state | Event | To state | Next action |",
        "|---|---|---|---|",
    ]
    for t in TRANSITIONS:
        from_label = t.from_state.value.replace("_", "\\_")
        to_label = t.to_state.value.replace("_", "\\_")
        event_label = t.event.value.replace("_", "\\_")
        rows.append(f"| `{from_label}` | `{event_label}` | `{to_label}` | {t.next_action} |")
    return "\n".join(rows)


# ── State descriptions ────────────────────────────────────────────────────


def gen_state_table() -> str:
    """Generate a Markdown table of all states, derived from WorkflowState."""
    rows = [
        "| ID | State | Label | Next action |",
        "|---|---|---|---|",
    ]
    for state in sorted(MACHINE.all_states, key=lambda s: s.position):
        rows.append(
            f"| {state.state_id} | `{state.value}` "
            f"| {state.display_label} | {state.next_action} |"
        )
    return "\n".join(rows)


# ── Gate resolution priority ──────────────────────────────────────────────


def gen_gate_priority_table() -> str:
    """Generate issue resolution priority table from registered gates.

    When multiple gates fail, this table tells the agent which failures
    to address first.  Ordering rationale — fix from the outside in:

    1. HIGH-churn structural gates first — silenced-gates and gate-dodging
       (could be masking anything), bogus/hand-wavy tests and coverage gaps
       (untested code has unlimited blast radius), code-sprawl, duplication,
       complexity-creep, dead-code.  These move, extract, or delete code,
       so their fixes are likely to re-trigger lower-churn gates.
    2. MEDIUM-churn additive gates — annotations, type checking.
       These add code but don't restructure existing code.
    3. LOW-churn cosmetic gates last — formatting, debugger-artifact removal.
       These are cheap to re-run and their fixes get undone by structural
       changes, so they should run once after everything else has settled.

    Within each churn tier, gates are sorted alphabetically by full name.
    """
    from slopmop.checks.base import RemediationChurn

    ensure_checks_registered()
    registry = get_registry()

    _CHURN_LABELS = {
        RemediationChurn.DOWNSTREAM_CHANGES_VERY_LIKELY: "1 — fix first",
        RemediationChurn.DOWNSTREAM_CHANGES_LIKELY: "2 — fix next",
        RemediationChurn.DOWNSTREAM_CHANGES_UNLIKELY: "3 — fix later",
        RemediationChurn.DOWNSTREAM_CHANGES_VERY_UNLIKELY: "4 — fix last",
    }

    # Collect gate metadata from registry
    gate_rows: list[tuple[int, str, str, str, str, str]] = []
    for name in sorted(registry.list_checks()):
        check_class = registry._check_classes.get(name)
        if check_class is None:
            continue
        instance = check_class({})

        # Skip scour-only gates — this table is for the swab loop
        if instance.level == GateLevel.SCOUR:
            continue

        churn = instance.remediation_churn
        tier = {
            RemediationChurn.DOWNSTREAM_CHANGES_VERY_LIKELY: 1,
            RemediationChurn.DOWNSTREAM_CHANGES_LIKELY: 2,
            RemediationChurn.DOWNSTREAM_CHANGES_UNLIKELY: 3,
            RemediationChurn.DOWNSTREAM_CHANGES_VERY_UNLIKELY: 4,
        }[churn]
        tier_label = _CHURN_LABELS[churn]

        role_label = instance.role.value.capitalize()
        fix_label = "yes" if instance.can_auto_fix() else "no"
        flaw_label = instance.flaw.display

        gate_rows.append(
            (tier, instance.full_name, role_label, flaw_label, fix_label, tier_label)
        )

    # Sort by churn tier (high first) then name alphabetically
    gate_rows.sort(key=lambda r: (r[0], r[1]))

    rows = [
        "| Priority | Gate | Role | Flaw | Auto-fix |",
        "|---|---|---|---|---|",
    ]
    for _tier, full_name, role_label, flaw_label, fix_label, tier_label in gate_rows:
        rows.append(
            f"| {tier_label} | `{full_name}` "
            f"| {role_label} | {flaw_label} | {fix_label} |"
        )
    return "\n".join(rows)


# ── Full document ─────────────────────────────────────────────────────────

_HEADER = """\
# Slop-Mop Workflow

> **Auto-generated** — do not edit by hand.
> Source of truth: `slopmop/workflow/state_machine.py`
> Re-generate: `python scripts/gen_workflow_diagrams.py`

The slop-mop development loop is a small state machine.  Every tool
invocation advances the machine; the swab/scour/buff outputs always
tell you the next step.

---

## State diagram

```mermaid
{flowchart}
```

---

## States

{state_table}

---

## Transitions

{transition_table}

---

## Issue resolution priority

When multiple gates fail, address them in this order — fix from the
outside in.  Structural gates (code-sprawl, repeated-code,
complexity-creep, dead-code) move or delete code, so fix those first.
Cosmetic gates (formatting, debugger-artifacts) run last because
structural changes would undo their fixes.

{gate_priority_table}
"""


def gen_document() -> str:
    return _HEADER.format(
        flowchart=gen_flowchart(),
        state_table=gen_state_table(),
        transition_table=gen_transition_table(),
        gate_priority_table=gen_gate_priority_table(),
    )


# ── CLI ───────────────────────────────────────────────────────────────────


def _fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if docs/WORKFLOW.md is stale (for CI).",
    )
    args = parser.parse_args()

    doc = gen_document()

    if args.check:
        if not OUTPUT_PATH.exists():
            report_missing(OUTPUT_PATH)
            return 1
        current = OUTPUT_PATH.read_text(encoding="utf-8")
        if _fingerprint(current) != _fingerprint(doc):
            report_stale(OUTPUT_PATH)
            return 1
        report_up_to_date(OUTPUT_PATH)
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(doc, encoding="utf-8")
    print(f"Written: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
