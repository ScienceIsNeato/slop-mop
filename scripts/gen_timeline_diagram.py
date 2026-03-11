#!/usr/bin/env python3
"""Generate the developer timeline diagram as SVG.

Usage::

    python scripts/gen_timeline_diagram.py          # writes docs/timeline_diagram.svg
    python scripts/gen_timeline_diagram.py --check   # exits non-zero if SVG is stale

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

OUTPUT_PATH = REPO_ROOT / "docs" / "timeline_diagram.svg"


def gen_mermaid() -> str:
    """Generate the developer-loop timeline with every rail mapped."""
    return """flowchart TD
    CODE["✏️ Edit source code"]
    SWAB["Run **sm swab**"]
    SWAB_Q{"Swab\\nresult?"}
    TASK_Q{"Task\\ncomplete?"}
    COMMIT["git commit"]
    SCOUR["Run **sm scour**"]
    SCOUR_Q{"Scour\\nresult?"}
    PUSH["git push"]
    PR_Q{"PR already\\nopen?"}
    OPEN_PR["Open PR"]
    CI_CHECK["Run **sm buff status**"]
    CI_Q{"CI\\nstatus?"}
    CI_WAIT["Wait / run **sm buff watch**"]
    INSPECT["Run **sm buff inspect**"]
    INSPECT_Q{"Inspect\\nresult?"}
    FINALIZE["Run **sm buff finalize --push**"]
    ITERATE["Run **sm buff iterate**"]
    ITER_Q{"Threads\\nto fix?"}
    MERGE["✅ Merge PR"]

    CODE --> SWAB
    SWAB --> SWAB_Q
    SWAB_Q -->|"fails"| CODE
    SWAB_Q -->|"passes"| TASK_Q
    TASK_Q -->|"Not yet"| CODE
    TASK_Q -->|"Ready to ship"| COMMIT
    COMMIT --> SCOUR
    SCOUR --> SCOUR_Q
    SCOUR_Q -->|"fails"| CODE
    SCOUR_Q -->|"passes"| PUSH
    PUSH --> PR_Q
    PR_Q -->|"No"| OPEN_PR --> CI_CHECK
    PR_Q -->|"Yes"| CI_CHECK
    CI_CHECK --> CI_Q
    CI_Q -->|"Not started"| CI_WAIT --> CI_CHECK
    CI_Q -->|"In progress,\\nno errors"| CI_WAIT
    CI_Q -->|"In progress,\\nwith errors"| CODE
    CI_Q -->|"Complete,\\nwith errors"| CODE
    CI_Q -->|"Complete,\\nno errors"| INSPECT
    INSPECT --> INSPECT_Q
    INSPECT_Q -->|"all green"| FINALIZE
    INSPECT_Q -->|"has issues"| ITERATE
    ITERATE --> ITER_Q
    ITER_Q -->|"Yes"| CODE
    ITER_Q -->|"No threads left"| INSPECT
    FINALIZE --> CI_CHECK
    INSPECT_Q -->|"still green\\n(post-finalize)"| MERGE"""


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
