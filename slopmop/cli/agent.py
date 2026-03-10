"""Agent integration helpers for slop-mop CLI."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List


@dataclass(frozen=True)
class AgentTemplate:
    """Template artifact written by ``sm agent install``."""

    relative_path: str
    content: str


_IMPLEMENTATION_LOOP = (
    "1. Run `sm swab` after meaningful code changes.\n"
    "2. If swab fails, fix the reported findings before continuing.\n"
    "3. Re-run `sm swab` until green.\n"
    "4. Before opening or updating a PR, run `sm scour`.\n"
    "5. After PR feedback lands or CI finishes on the PR branch, run `sm buff`."
)

_CURSOR_RULE = """---
description: Slop-mop workflow guardrails
globs:
alwaysApply: false
---

Use slop-mop as the repo quality loop:
{workflow_steps}

Do not bypass or silence failing gates as a shortcut.
"""

_CLAUDE_COMMAND = """# /sm-swab

Run slop-mop quick validation for this repository.

Workflow:
1. Run `sm swab`.
2. Summarize failing gates and the concrete fix strategies.
3. Apply fixes.
4. Re-run `sm swab` until the run is clean.
5. Before opening or updating a PR, run `sm scour`.
6. After PR feedback lands or CI finishes on the PR branch, run `sm buff`.

Do not bypass or silence failing gates as a shortcut.
"""


def _cursor_rule() -> str:
    """Render Cursor workflow guidance."""

    return _CURSOR_RULE.format(workflow_steps=_IMPLEMENTATION_LOOP)


def _claude_command() -> str:
    """Render Claude workflow guidance."""

    return _CLAUDE_COMMAND


def _templates_for_target(target: str) -> List[AgentTemplate]:
    """Return templates for one install target."""
    if target == "cursor":
        return [
            AgentTemplate(
                relative_path=".cursor/rules/slopmop-swab.mdc",
                content=_cursor_rule(),
            )
        ]
    if target == "claude":
        return [
            AgentTemplate(
                relative_path=".claude/commands/sm-swab.md",
                content=_claude_command(),
            )
        ]
    return []


def _expand_targets(target: str) -> List[str]:
    """Expand CLI target option into concrete targets."""
    if target == "all":
        return ["cursor", "claude"]
    return [target]


def _install_templates(
    project_root: Path, templates: Iterable[AgentTemplate], force: bool
) -> tuple[List[Path], List[Path]]:
    """Write templates to disk and return installed/skipped paths."""
    installed: List[Path] = []
    skipped: List[Path] = []

    for template in templates:
        destination = project_root / template.relative_path
        if destination.exists() and not force:
            skipped.append(destination)
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(template.content, encoding="utf-8")
        installed.append(destination)

    return installed, skipped


def cmd_agent(args: argparse.Namespace) -> int:
    """Handle the ``sm agent`` command."""
    if args.agent_action != "install":
        print(
            "Usage: sm agent install "
            "[--target all|cursor|claude] [--project-root PATH] [--force]"
        )
        return 2

    project_root = Path(args.project_root).resolve()
    if not project_root.exists():
        print(f"❌ Agent install project root not found: {project_root}")
        return 2

    targets = _expand_targets(args.target)
    templates: List[AgentTemplate] = []
    for target in targets:
        templates.extend(_templates_for_target(target))

    installed, skipped = _install_templates(project_root, templates, args.force)

    print()
    print("✅ Agent templates processed")
    print(f"📁 Project: {project_root}")
    if installed:
        print("Installed/updated:")
        for path in installed:
            print(f"  - {path.relative_to(project_root)}")
    if skipped:
        print("Skipped (already exists, use --force to overwrite):")
        for path in skipped:
            print(f"  - {path.relative_to(project_root)}")
    print()
    print("Next steps:")
    print("  1. Restart your agent session if it caches command/rule discovery")
    print("  2. Use `sm swab` routinely during implementation")
    print("  3. Use `sm scour` before opening/updating PRs")
    print("  4. Use `sm buff` after PR feedback lands or CI completes")
    print()
    return 0
