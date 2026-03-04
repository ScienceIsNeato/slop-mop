#!/usr/bin/env python3
"""Generate README gate tables from check class metadata.

This is the **single source of truth** pipeline:

    Check classes (gate_description property)
       ↓
    This script (reads + formats)
       ↓
    README.md (between marker comments)

Usage:
    # Preview generated tables (stdout)
    python scripts/generate_readme_tables.py

    # Update README.md in-place
    python scripts/generate_readme_tables.py --update

    # Check if README is current (exit 1 if stale)
    python scripts/generate_readme_tables.py --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure the project root is on sys.path so slopmop is importable
# even when running as `python scripts/generate_readme_tables.py`
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from slopmop.checks import ensure_checks_registered  # noqa: E402
from slopmop.core.registry import get_registry  # noqa: E402
from slopmop.utils.readme_tables import (  # noqa: E402
    check_readme,
    generate_tables,
    splice_tables,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate README gate tables from check class metadata"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--update",
        action="store_true",
        help="Update README.md in-place between markers",
    )
    group.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if README gate tables are stale (for CI)",
    )
    parser.add_argument(
        "--readme",
        type=Path,
        default=_project_root / "README.md",
        help="Path to README.md (default: project root)",
    )
    args = parser.parse_args()

    ensure_checks_registered()
    registry = get_registry()

    if not args.update and not args.check:
        # Preview mode — print to stdout
        print(generate_tables(registry))
        return 0

    if args.check:
        is_current, message = check_readme(args.readme, registry)
        if is_current:
            print(f"✅ {message}")
            return 0
        else:
            print(f"❌ {message}", file=sys.stderr)
            return 1

    # --update
    readme_text = args.readme.read_text()
    tables = generate_tables(registry)
    try:
        new_readme = splice_tables(readme_text, tables)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    args.readme.write_text(new_readme)
    print(f"✅ Updated {args.readme}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
