"""Tests for the built-in upgrade migration registry."""

from pathlib import Path

from slopmop.migrations import (
    UpgradeMigration,
    planned_upgrade_migrations,
    run_upgrade_migrations,
)


class TestUpgradeMigration:
    def test_applies_within_version_window(self):
        migration = UpgradeMigration(
            key="m1",
            min_version="0.8.0",
            max_version="0.9.0",
            apply=lambda _root: None,
        )
        assert migration.applies("0.8.1", "0.9.0") is True
        assert migration.applies("0.9.0", "0.9.1") is False


class TestMigrationRegistry:
    def test_planned_upgrade_migrations_uses_registered_migrations(self, monkeypatch):
        migration = UpgradeMigration(
            key="m1",
            min_version="0.8.0",
            max_version="0.9.0",
            apply=lambda _root: None,
        )
        monkeypatch.setattr("slopmop.migrations._MIGRATIONS", [migration])
        assert planned_upgrade_migrations("0.8.1", "0.9.0") == ["m1"]

    def test_run_upgrade_migrations_applies_matching_steps(
        self, monkeypatch, tmp_path: Path
    ):
        seen: list[Path] = []

        def _apply(root: Path) -> None:
            seen.append(root)

        migration = UpgradeMigration(
            key="m1",
            min_version="0.8.0",
            max_version="0.9.0",
            apply=_apply,
        )
        monkeypatch.setattr("slopmop.migrations._MIGRATIONS", [migration])
        assert run_upgrade_migrations(tmp_path, "0.8.1", "0.9.0") == ["m1"]
        assert seen == [tmp_path]

    def test_run_upgrade_migrations_skips_non_matching_steps(
        self, monkeypatch, tmp_path: Path
    ):
        migration = UpgradeMigration(
            key="m1",
            min_version="0.8.0",
            max_version="0.9.0",
            apply=lambda _root: None,
        )
        monkeypatch.setattr("slopmop.migrations._MIGRATIONS", [migration])
        assert run_upgrade_migrations(tmp_path, "0.9.0", "0.9.1") == []

    def test_planned_upgrade_migrations_orders_multi_step_upgrades(self, monkeypatch):
        migration_1 = UpgradeMigration(
            key="migrate-0.9.0",
            min_version="0.8.0",
            max_version="0.9.0",
            apply=lambda _root: None,
        )
        migration_2 = UpgradeMigration(
            key="migrate-0.10.0",
            min_version="0.9.0",
            max_version="0.10.0",
            apply=lambda _root: None,
        )
        monkeypatch.setattr(
            "slopmop.migrations._MIGRATIONS", [migration_2, migration_1]
        )

        assert planned_upgrade_migrations("0.8.0", "0.10.0") == [
            "migrate-0.9.0",
            "migrate-0.10.0",
        ]

    def test_run_upgrade_migrations_applies_multi_step_upgrades_in_order(
        self, monkeypatch, tmp_path: Path
    ):
        seen: list[str] = []

        migration_1 = UpgradeMigration(
            key="migrate-0.9.0",
            min_version="0.8.0",
            max_version="0.9.0",
            apply=lambda _root: seen.append("migrate-0.9.0"),
        )
        migration_2 = UpgradeMigration(
            key="migrate-0.10.0",
            min_version="0.9.0",
            max_version="0.10.0",
            apply=lambda _root: seen.append("migrate-0.10.0"),
        )
        monkeypatch.setattr(
            "slopmop.migrations._MIGRATIONS", [migration_2, migration_1]
        )

        assert run_upgrade_migrations(tmp_path, "0.8.0", "0.10.0") == [
            "migrate-0.9.0",
            "migrate-0.10.0",
        ]
        assert seen == ["migrate-0.9.0", "migrate-0.10.0"]
