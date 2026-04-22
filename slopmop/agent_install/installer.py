"""Install agent templates into a project repository."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from slopmop.agent_install.loader import load_assets
from slopmop.agent_install.registry import (
    TARGETS,
    expand_target,
    uses_user_home_destination,
)
from slopmop.utils import posix_relpath_to_path


@dataclass
class InstallReport:
    """Summary of what was installed, skipped, or errored."""

    project_root: Path
    installed: List[Path] = field(default_factory=lambda: [])
    skipped: List[Path] = field(default_factory=lambda: [])
    errors: List[str] = field(default_factory=lambda: [])


def install_agent_templates(
    *, target: str, project_root: Path, force: bool
) -> InstallReport:
    """Install template files for the given target into *project_root*."""
    project_root = project_root.resolve()
    try:
        user_home: Path | None = Path.home().resolve()
    except RuntimeError:
        user_home = None
    report = InstallReport(project_root=project_root)

    target_keys = expand_target(target)

    for key in target_keys:
        info = TARGETS[key]
        try:
            assets = load_assets(info.template_dir)
        except FileNotFoundError as exc:
            report.errors.append(str(exc))
            continue

        for asset in assets:
            if uses_user_home_destination(key, asset.destination_relpath):
                if user_home is None:
                    report.errors.append(
                        f"{asset.destination_relpath}: skipped — cannot resolve "
                        "user home directory (HOME may be unset)"
                    )
                    continue
                destination = user_home / posix_relpath_to_path(
                    asset.destination_relpath
                )
            else:
                destination = project_root / posix_relpath_to_path(
                    asset.destination_relpath
                )
            try:
                if destination.exists() and not force:
                    report.skipped.append(destination)
                    continue

                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(asset.content)
                report.installed.append(destination)
            except Exception as exc:
                report.errors.append(f"{destination}: {exc}")

    return report
