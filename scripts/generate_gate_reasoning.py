#!/usr/bin/env python3
"""Generate the standalone gate-reasoning doc from gate metadata."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from slopmop.checks import ensure_checks_registered  # noqa: E402
from slopmop.core.registry import get_registry  # noqa: E402
from slopmop.utils.gate_reasoning_docs import (  # noqa: E402
    check_reasoning_doc,
    generate_reasoning_doc,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the standalone gate-reasoning doc from gate metadata"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--update",
        action="store_true",
        help="Update DOCS/GATE_REASONING.md in-place",
    )
    group.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if DOCS/GATE_REASONING.md is stale",
    )
    parser.add_argument(
        "--doc",
        type=Path,
        default=_project_root / "DOCS" / "GATE_REASONING.md",
        help="Path to the generated gate-reasoning doc",
    )
    args = parser.parse_args()

    ensure_checks_registered()
    registry = get_registry()

    if not args.update and not args.check:
        print(generate_reasoning_doc(registry))
        return 0

    if args.check:
        is_current, message = check_reasoning_doc(args.doc, registry)
        if is_current:
            print(f"OK {message}")
            return 0
        print(f"STALE {message}", file=sys.stderr)
        return 1

    args.doc.parent.mkdir(parents=True, exist_ok=True)
    args.doc.write_text(generate_reasoning_doc(registry))
    print(f"Updated {args.doc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())