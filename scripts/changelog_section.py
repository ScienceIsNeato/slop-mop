#!/usr/bin/env python3
"""Extract one version's section from CHANGELOG.md.

The release workflow uses this twice: once to *require* that the version being
cut has release notes (fail fast otherwise), and once to feed that section to
``gh release create --notes-file`` as the GitHub Release body.

Usage:
    python scripts/changelog_section.py <version> [--changelog PATH]

Prints the section body to stdout. Exits non-zero (with a message on stderr)
when CHANGELOG.md is missing or has no non-empty section for that version, so a
release can never be published without notes.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional


def extract_section(text: str, version: str) -> Optional[str]:
    """Return the body under ``## <version>`` (or ``## [<version>]``), or None.

    The body runs from just after the heading to the next ``## `` heading.
    Surrounding blank lines are stripped; an empty section returns None so it
    counts as "no notes".
    """
    heading = re.compile(r"^##\s+\[?" + re.escape(version) + r"\]?\s*$")
    next_section = re.compile(r"^##\s+")
    lines = text.splitlines()

    start: Optional[int] = None
    for i, line in enumerate(lines):
        if heading.match(line):
            start = i + 1
            break
    if start is None:
        return None

    body: list[str] = []
    for line in lines[start:]:
        if next_section.match(line):
            break
        body.append(line)

    section = "\n".join(body).strip()
    return section or None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="Version to extract, e.g. 2.6.0")
    parser.add_argument(
        "--changelog",
        default="CHANGELOG.md",
        help="Path to the changelog (default: CHANGELOG.md)",
    )
    args = parser.parse_args(argv)

    path = Path(args.changelog)
    if not path.is_file():
        print(f"{args.changelog} not found", file=sys.stderr)
        return 1

    section = extract_section(path.read_text(encoding="utf-8"), args.version)
    if not section:
        print(
            f"No release notes for {args.version} in {args.changelog} — add a "
            f"'## {args.version}' section before cutting this release.",
            file=sys.stderr,
        )
        return 1

    print(section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
