"""Target registry for ``sm agent install``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class InstallTarget:
    """One installable agent integration target."""

    key: str
    display_name: str
    template_dir: str


TARGETS: Dict[str, InstallTarget] = {
    "cursor": InstallTarget(
        key="cursor",
        display_name="Cursor rules",
        template_dir="cursor",
    ),
    "claude": InstallTarget(
        key="claude",
        display_name="Claude Code commands",
        template_dir="claude",
    ),
    "copilot": InstallTarget(
        key="copilot",
        display_name="GitHub Copilot instructions",
        template_dir="copilot",
    ),
    "windsurf": InstallTarget(
        key="windsurf",
        display_name="Windsurf rules",
        template_dir="windsurf",
    ),
    "cline": InstallTarget(
        key="cline",
        display_name="Cline rules",
        template_dir="cline",
    ),
    "roo": InstallTarget(
        key="roo",
        display_name="Roo Code workspace rules",
        template_dir="roo",
    ),
    "aider": InstallTarget(
        key="aider",
        display_name="Aider repo config + conventions",
        template_dir="aider",
    ),
}

ALL_KEYS: Tuple[str, ...] = tuple(TARGETS.keys())
INSTALL_HELP_PREVIEW_ROOT = PurePosixPath(".slopmop/tmp")

ALIASES: Dict[str, List[str]] = {
    "all": list(ALL_KEYS),
}


def cli_choices() -> List[str]:
    """Strings accepted by ``sm agent install --target``."""
    return sorted(set(list(TARGETS.keys()) + list(ALIASES.keys())))


def expand_target(target: str) -> List[str]:
    """Expand an alias or single target into concrete target keys."""
    if target in ALIASES:
        return list(ALIASES[target])
    if target in TARGETS:
        return [target]
    raise ValueError(f"Unknown agent install target: {target}")


def preview_install_paths(
    target: str,
    preview_root: PurePosixPath = INSTALL_HELP_PREVIEW_ROOT,
) -> List[str]:
    """Return preview install destinations for one target.

    The CLI help uses a repo-local preview root instead of OS temp paths so the
    displayed destinations are deterministic and easy to reason about.
    """
    from slopmop.agent_install.loader import load_assets

    if target not in TARGETS:
        return []

    return [
        str(preview_root / PurePosixPath(asset.destination_relpath))
        for asset in load_assets(TARGETS[target].template_dir)
    ]
