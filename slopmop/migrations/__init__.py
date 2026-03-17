"""Built-in upgrade migrations for slop-mop installs.

The first implementation keeps the framework intentionally small: upgrades can
preview and run deterministic Python migrations keyed by version transitions,
even if no concrete migrations are needed yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List

from packaging.version import Version


@dataclass(frozen=True)
class UpgradeMigration:
    """A deterministic built-in migration keyed by version range."""

    key: str
    min_version: str
    max_version: str
    apply: Callable[[Path], None]

    @property
    def sort_key(self) -> tuple[Version, Version, str]:
        """Deterministic ordering for stepwise upgrade execution."""
        return (Version(self.max_version), Version(self.min_version), self.key)

    def applies(self, from_version: str, to_version: str) -> bool:
        from_v = Version(from_version)
        to_v = Version(to_version)
        return from_v < Version(self.max_version) <= to_v and from_v >= Version(
            self.min_version
        )


_MIGRATIONS: List[UpgradeMigration] = []


def _ordered_applicable_migrations(
    from_version: str, to_version: str
) -> Iterable[UpgradeMigration]:
    """Return applicable migrations in deterministic stepwise order."""
    current_version = Version(from_version)
    target_version = Version(to_version)
    applied: List[UpgradeMigration] = []

    for migration in sorted(_MIGRATIONS, key=lambda item: item.sort_key):
        migration_max = Version(migration.max_version)
        migration_min = Version(migration.min_version)
        if (
            current_version < migration_max <= target_version
            and current_version >= migration_min
        ):
            applied.append(migration)
            current_version = migration_max

    return applied


def planned_upgrade_migrations(from_version: str, to_version: str) -> List[str]:
    """Return the migration keys that would run for a version change."""
    return [m.key for m in _ordered_applicable_migrations(from_version, to_version)]


def run_upgrade_migrations(
    project_root: str | Path, from_version: str, to_version: str
) -> List[str]:
    """Run any built-in upgrade migrations and return the keys applied."""
    root = Path(project_root)
    applied: List[str] = []
    for migration in _ordered_applicable_migrations(from_version, to_version):
        migration.apply(root)
        applied.append(migration.key)
    return applied
