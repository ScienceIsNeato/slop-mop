"""Agent integration helpers for slop-mop CLI."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import List

from slopmop.agent_install.installer import install_agent_templates
from slopmop.agent_install.registry import ALL_KEYS, TARGETS, expand_target

ALL_TARGETS = list(ALL_KEYS)


@dataclass(frozen=True)
class AgentTemplate:
    """Template artifact written by ``sm agent install``."""

    relative_path: str
    content: str


def _templates_for_target(target: str) -> List[AgentTemplate]:
    """Return templates for one install target (used by tests)."""
    from slopmop.agent_install.loader import load_assets

    if target not in TARGETS:
        return []
    assets = load_assets(TARGETS[target].template_dir)
    return [
        AgentTemplate(
            relative_path=a.destination_relpath, content=a.content.decode("utf-8")
        )
        for a in assets
    ]


def _expand_targets(target: str) -> List[str]:
    """Expand CLI target option into concrete targets."""
    return expand_target(target)


def cmd_agent(args: argparse.Namespace) -> int:
    """Handle the ``sm agent`` command."""
    if args.agent_action != "install":
        targets_str = "|".join(["all"] + ALL_TARGETS)
        print(
            f"Usage: sm agent install "
            f"[--target {targets_str}] "
            f"[--project-root PATH] [--force]"
        )
        return 2

    project_root = Path(args.project_root).resolve()
    if not project_root.exists():
        print(f"❌ Agent install project root not found: {project_root}")
        return 2

    report = install_agent_templates(
        target=args.target, project_root=project_root, force=args.force
    )

    if report.errors:
        print("❌ Agent templates failed:")
        for err in report.errors:
            print(f"  - {err}")
        return 2

    print()
    print("✅ Agent templates processed")
    print(f"📁 Project: {report.project_root}")
    if report.installed:
        print("Installed/updated:")
        for path in report.installed:
            print(f"  - {path.relative_to(report.project_root)}")
    if report.skipped:
        print("Skipped (already exists, use --force to overwrite):")
        for path in report.skipped:
            print(f"  - {path.relative_to(report.project_root)}")
    print()
    print("Next steps:")
    print("  1. Restart your agent session if it caches command/rule discovery")
    print("  2. Use `sm swab` routinely during implementation")
    print("  3. Use `sm scour` before opening/updating PRs")
    print("  4. Use `sm buff` after PR feedback lands or CI completes")
    print()
    return 0
