#!/usr/bin/env python3
"""Propagate the single-source version into the docs that state it.

The version lives in exactly one place: ``slopmop/_version.py``. This script
pushes that value into the handful of non-code files that mention the *current*
slop-mop version, and a ``--check`` mode reports drift without writing.

  python scripts/sync_version.py          # rewrite docs to match the source
  python scripts/sync_version.py --check  # exit 1 if any target is out of sync

``tests/unit/test_version_consistency.py`` calls :func:`check` so a mismatch
can never be merged.

Only *current-slop-mop-version* mentions are managed. Versions that are NOT
slop-mop's — the SARIF spec version, the Contributor Covenant version, the
``1.0.0`` stability-policy boundary, and illustrative migration examples — are
intentionally left untouched by keeping the target patterns narrow.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
_VERSION_RE = re.compile(r"__version__\s*=\s*[\"']([^\"']+)[\"']")


def source_version() -> str:
    """Read the canonical version from slopmop/_version.py (no import needed)."""
    text = (REPO_ROOT / "slopmop" / "_version.py").read_text(encoding="utf-8")
    match = _VERSION_RE.search(text)
    if not match:
        raise SystemExit("Could not find __version__ in slopmop/_version.py")
    return match.group(1)


@dataclass(frozen=True)
class Target:
    """A file + a narrow pattern whose single capture group is the version."""

    path: str
    pattern: str
    description: str


# Each pattern must have exactly ONE capture group around the version number,
# and must be specific enough to match only the current-slop-mop-version
# mention(s) in that file.
TARGETS: Tuple[Target, ...] = (
    Target(
        "README.md",
        r"slop-mop is at version (\d+\.\d+\.\d+)",
        "README project-status line",
    ),
    Target(
        "DOCS/MACHINE_INTERFACE.md",
        r'"version": "(\d+\.\d+\.\d+)"',
        "sm capabilities example envelope",
    ),
    Target(
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        r'placeholder: "(\d+\.\d+\.\d+)"',
        "bug-report version-field example",
    ),
    Target(
        ".cursor-plugin/plugin.json",
        r'"version": "(\d+\.\d+\.\d+)"',
        "Cursor plugin manifest version",
    ),
)


def _sub_version(text: str, pattern: str, version: str) -> str:
    return re.sub(pattern, lambda m: m.group(0).replace(m.group(1), version), text)


def check() -> Tuple[str, List[str]]:
    """Return (source_version, problems). Empty problems means fully in sync."""
    version = source_version()
    problems: List[str] = []
    for target in TARGETS:
        path = REPO_ROOT / target.path
        if not path.exists():
            # Tolerate targets that live on a not-yet-merged branch.
            continue
        text = path.read_text(encoding="utf-8")
        found = re.findall(target.pattern, text)
        if not found:
            problems.append(
                f"{target.path}: pattern for {target.description!r} matched nothing "
                f"(did the surrounding text change?)"
            )
            continue
        stale = sorted({v for v in found if v != version})
        if stale:
            problems.append(
                f"{target.path}: {target.description} has {stale}, expected "
                f"{version!r}"
            )
    return version, problems


def apply() -> Tuple[str, List[str]]:
    """Rewrite targets to the source version. Return (version, changed_paths)."""
    version = source_version()
    changed: List[str] = []
    for target in TARGETS:
        path = REPO_ROOT / target.path
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        updated = _sub_version(text, target.pattern, version)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed.append(target.path)
    return version, changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report drift and exit non-zero instead of rewriting.",
    )
    args = parser.parse_args()

    if args.check:
        version, problems = check()
        if problems:
            print(f"Version drift from slopmop/_version.py ({version}):", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        print(f"All version mentions are in sync at {version}.")
        return 0

    version, changed = apply()
    if changed:
        print(f"Synced {len(changed)} file(s) to {version}:")
        for path in changed:
            print(f"  - {path}")
    else:
        print(f"Already in sync at {version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
