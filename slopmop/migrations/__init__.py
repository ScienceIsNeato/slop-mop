"""Built-in upgrade migrations for slop-mop installs.

The first implementation keeps the framework intentionally small: upgrades can
preview and run deterministic Python migrations keyed by version transitions,
even if no concrete migrations are needed yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List

from packaging.version import Version


@dataclass(frozen=True)
class UpgradeMigration:
    """A deterministic built-in migration keyed by version range."""

    key: str
    min_version: str
    max_version: str
    apply: Callable[[Path], None]

    def applies(self, from_version: str, to_version: str) -> bool:
        from_v = Version(from_version)
        to_v = Version(to_version)
        return from_v < Version(self.max_version) <= to_v and from_v >= Version(
            self.min_version
        )


def _noop(_project_root: Path) -> None:
    return None


_MIGRATIONS: List[UpgradeMigration] = []


def planned_upgrade_migrations(from_version: str, to_version: str) -> List[str]:
    """Return the migration keys that would run for a version change."""
    return [m.key for m in _MIGRATIONS if m.applies(from_version, to_version)]


def run_upgrade_migrations(
    project_root: str | Path, from_version: str, to_version: str
) -> List[str]:
    """Run any built-in upgrade migrations and return the keys applied."""
    root = Path(project_root)
    applied: List[str] = []
    for migration in _MIGRATIONS:
        if migration.applies(from_version, to_version):
            migration.apply(root)
            applied.append(migration.key)
    return applied
