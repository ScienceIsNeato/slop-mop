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

from slopmop.workflow.state_machine import (  # noqa: E402
    MACHINE,
    TRANSITIONS,
    WorkflowState,
)

OUTPUT_PATH = REPO_ROOT / "docs" / "WORKFLOW.md"

# ── Human-readable labels ─────────────────────────────────────────────────

STATE_LABELS: dict[WorkflowState, str] = {
    WorkflowState.CODING: "During implementation",
    WorkflowState.SWAB_CLEAN: "Swab passed",
    WorkflowState.COMMITTED: "Changes committed",
    WorkflowState.SCOUR_CLEAN: "Scour passed",
    WorkflowState.PR_OPEN: "PR open — awaiting CI/review",
    WorkflowState.BUFF_ITERATING: "Addressing feedback",
    WorkflowState.PR_READY: "PR ready to land",
}

# States shown as distinct nodes in the flowchart
FLOWCHART_NODES: list[WorkflowState] = [
    WorkflowState.CODING,
    WorkflowState.SCOUR_CLEAN,
    WorkflowState.PR_OPEN,
    WorkflowState.PR_READY,
]

# ── State diagram (replaces the hard-to-read LR flowchart) ─────────────


def _state_id(state: WorkflowState) -> str:
    return state.value


def gen_flowchart() -> str:
    """Generate a Mermaid stateDiagram-v2 from the transition table."""
    lines = ["stateDiagram-v2", "    direction LR"]

    # State aliases for readable labels
    all_states = MACHINE.all_states
    for state in all_states:
        sid = _state_id(state)
        label = STATE_LABELS.get(state, state.value.replace("_", " ").title())
        lines.append(f"    {sid} : {label}")

    lines.append("")

    # Transitions
    seen_edges: set[tuple[str, str, str]] = set()
    for t in TRANSITIONS:
        src = _state_id(t.from_state)
        dst = _state_id(t.to_state)
        key = (src, t.label, dst)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        lines.append(f"    {src} --> {dst} : {t.label}")

    return "\n".join(lines)


# ── Timeline / sequence diagram ───────────────────────────────────────────


def gen_timeline() -> str:
    """Generate a Mermaid flowchart that mirrors the timeline diagram.

    The timeline shows the top-down developer loop with decision branches,
    matching the second screenshot.
    """
    lines = [
        "flowchart TD",
        '    START["During implementation"]',
        '    SWAB["Run sm swab"]',
        '    COMMIT["Commit"]',
        '    BEFORE_PR["Before PR update/open"]',
        '    SCOUR["Run sm scour"]',
        '    OPEN_PR["Open/update PR"]',
        '    AFTER_PR["After PR opens / CI feedback"]',
        '    BUFF["Run sm buff"]',
        '    FIX["Fix findings"]',
        "",
        "    START --> SWAB",
        '    SWAB -->|"passes"| COMMIT',
        '    SWAB -->|"fails"| FIX',
        "    COMMIT --> BEFORE_PR",
        "    BEFORE_PR --> SCOUR",
        '    SCOUR -->|"passes"| OPEN_PR',
        '    SCOUR -->|"fails"| FIX',
        "    OPEN_PR --> AFTER_PR",
        "    AFTER_PR --> BUFF",
        '    BUFF -->|"actionable guidance"| FIX',
        "    FIX --> SWAB",
    ]
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
    rows = [
        "| State | Meaning | Docstring |",
        "|---|---|---|",
    ]
    for state in MACHINE.all_states:
        label = state.value
        doc = (state.__doc__ or "").strip().splitlines()[0] if state.__doc__ else ""
        desc = STATE_LABELS.get(state, label)
        rows.append(f"| `{label}` | {desc} | {doc} |")
    return "\n".join(rows)


# ── Full document ─────────────────────────────────────────────────────────

_HEADER = """\
# Slop-Mop Workflow

> **Auto-generated** — do not edit by hand.
> Source of truth: `slopmop/workflow/state_machine.py`
> Re-generate: `python scripts/gen_workflow_diagrams.py`

The slop-mop development loop is a small state machine.  Every tool
invocation advances the machine; the terminal `walk-forward` gate in
`sm scour` always tells you the next step.

---

## Relationship diagram

```mermaid
{flowchart}
```

---

## Developer timeline

```mermaid
{timeline}
```

---

## States

{state_table}

---

## Transitions

{transition_table}
"""


def gen_document() -> str:
    return _HEADER.format(
        flowchart=gen_flowchart(),
        timeline=gen_timeline(),
        state_table=gen_state_table(),
        transition_table=gen_transition_table(),
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
            print(f"STALE: {OUTPUT_PATH} does not exist — run gen_workflow_diagrams.py")
            return 1
        current = OUTPUT_PATH.read_text(encoding="utf-8")
        if _fingerprint(current) != _fingerprint(doc):
            print(f"STALE: {OUTPUT_PATH} is out of date — run gen_workflow_diagrams.py")
            return 1
        print(f"UP TO DATE: {OUTPUT_PATH}")
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(doc, encoding="utf-8")
    print(f"Written: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
