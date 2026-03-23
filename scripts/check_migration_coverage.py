#!/usr/bin/env python3
"""Check that gate name changes in a PR are accompanied by upgrade migrations.

Compares the set of gate full-names in ``.sb_config.json.template`` between
the merge-base (origin/main) and HEAD.  If the sets differ and
``slopmop/migrations/__init__.py`` was **not** modified, the check fails.

Exit codes:
    0  — no gate name changes, or changes accompanied by migration update
    1  — gate names changed without a corresponding migration
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Set

_TEMPLATE_PATH = ".sb_config.json.template"
_MIGRATION_PATH = "slopmop/migrations/__init__.py"
_CATEGORY_KEYS = {
    "overconfidence",
    "deceptiveness",
    "laziness",
    "myopia",
    "general",
}


def _gate_names_from_template(content: str) -> Set[str]:
    """Extract ``category:gate`` names from a config template JSON string."""
    try:
        data: Dict[str, Any] = json.loads(content)
    except json.JSONDecodeError:
        return set()

    names: Set[str] = set()
    for category in _CATEGORY_KEYS:
        cat_data = data.get(category)
        if isinstance(cat_data, dict):
            gates = cat_data.get("gates", {})
            if isinstance(gates, dict):
                for gate_name in gates:
                    names.add(f"{category}:{gate_name}")
    return names


def _git_merge_base() -> Optional[str]:
    result = subprocess.run(
        ["git", "merge-base", "origin/main", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _git_show(ref: str, path: str) -> Optional[str]:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _changed_files(base_ref: str) -> Set[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return set()
    return {line for line in result.stdout.strip().split("\n") if line}


def main() -> int:
    base_ref = _git_merge_base()
    if base_ref is None:
        print("✅ On base branch or no remote — nothing to check")
        return 0

    old_content = _git_show(base_ref, _TEMPLATE_PATH)
    template_file = Path(_TEMPLATE_PATH)
    new_content = (
        template_file.read_text(encoding="utf-8") if template_file.exists() else None
    )

    if old_content is None and new_content is None:
        print("✅ No config template found")
        return 0

    old_gates = _gate_names_from_template(old_content or "{}")
    new_gates = _gate_names_from_template(new_content or "{}")

    removed = old_gates - new_gates
    added = new_gates - old_gates

    if not removed:
        # New gates don't need migrations — the user's old config simply
        # won't reference them.  Only *removed* (or renamed) gates leave
        # stale references in existing configs.
        if added:
            print(f"✅ {len(added)} new gate(s) added (no migration needed)")
        else:
            print("✅ No gate name changes detected")
        return 0

    changed = _changed_files(base_ref)
    if _MIGRATION_PATH in changed:
        print("✅ Gate name changes accompanied by migration update")
        print(f"  Removed: {', '.join(sorted(removed))}")
        if added:
            print(f"  Added: {', '.join(sorted(added))}")
        return 0

    print("❌ Gate names removed without upgrade migration:")
    print(f"  Removed: {', '.join(sorted(removed))}")
    if added:
        print(f"  Added: {', '.join(sorted(added))}")
    print()
    print("Users with existing .sb_config.json files have stale references")
    print("to removed gates.  Add an upgrade migration to rename or clean up.")
    print()
    print(f"Add a migration to {_MIGRATION_PATH}")
    print("See docs/MIGRATIONS.md for the authoring process.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
