#!/usr/bin/env python3
"""Generate the workflow state-machine relationship diagram as SVG.

Usage::

    python scripts/gen_relationship_diagram.py          # writes docs/relationship_diagram.svg
    python scripts/gen_relationship_diagram.py --check   # exits non-zero if SVG is stale

Source of truth: ``slopmop.workflow.state_machine.TRANSITIONS``
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from slopmop.workflow.state_machine import (  # noqa: E402
    MACHINE,
    TRANSITIONS,
    WorkflowState,
)

OUTPUT_PATH = REPO_ROOT / "docs" / "relationship_diagram.svg"

STATE_LABELS: dict[WorkflowState, str] = {
    WorkflowState.CODING: "During implementation",
    WorkflowState.SWAB_CLEAN: "Swab passed",
    WorkflowState.COMMITTED: "Changes committed",
    WorkflowState.SCOUR_CLEAN: "Scour passed",
    WorkflowState.PR_OPEN: "PR open —\\nawaiting CI/review",
    WorkflowState.BUFF_ITERATING: "Addressing feedback",
    WorkflowState.PR_READY: "PR ready to land",
}


def gen_mermaid() -> str:
    """Generate a vertical stateDiagram-v2 from the transition table."""
    lines = ["stateDiagram-v2", "    direction TB"]

    for state in MACHINE.all_states:
        sid = state.value
        label = STATE_LABELS.get(state, state.value.replace("_", " ").title())
        lines.append(f"    {sid} : {label}")

    lines.append("")

    seen: set[tuple[str, str, str]] = set()
    for t in TRANSITIONS:
        src = t.from_state.value
        dst = t.to_state.value
        key = (src, t.label, dst)
        if key not in seen:
            seen.add(key)
            lines.append(f"    {src} --> {dst} : {t.label}")

    return "\n".join(lines)


def render_svg(mermaid_text: str, output: Path) -> None:
    """Render Mermaid text to SVG using mmdc (mermaid-cli)."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".mmd", delete=False
    ) as tmp:
        tmp.write(mermaid_text)
        tmp_path = Path(tmp.name)

    try:
        result = subprocess.run(
            [
                "npx",
                "--yes",
                "@mermaid-js/mermaid-cli",
                "-i",
                str(tmp_path),
                "-o",
                str(output),
                "--quiet",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"mmdc failed: {result.stderr}", file=sys.stderr)
            sys.exit(1)
    finally:
        tmp_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the SVG is stale (for CI).",
    )
    args = parser.parse_args()

    mermaid_text = gen_mermaid()

    if args.check:
        if not OUTPUT_PATH.exists():
            print(f"STALE: {OUTPUT_PATH} does not exist")
            return 1
        # Regenerate to temp and compare
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tmp:
            tmp_svg = Path(tmp.name)
        render_svg(mermaid_text, tmp_svg)
        new_hash = hashlib.sha256(tmp_svg.read_bytes()).hexdigest()
        cur_hash = hashlib.sha256(OUTPUT_PATH.read_bytes()).hexdigest()
        tmp_svg.unlink(missing_ok=True)
        if new_hash != cur_hash:
            print(f"STALE: {OUTPUT_PATH} is out of date")
            return 1
        print(f"UP TO DATE: {OUTPUT_PATH}")
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    render_svg(mermaid_text, OUTPUT_PATH)
    print(f"Written: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
