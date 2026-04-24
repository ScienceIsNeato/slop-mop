"""Tests for the built-in upgrade migration registry."""

import json
from pathlib import Path

from slopmop.migrations import (
    UpgradeMigration,
    _rename_dart_gates,
    _rename_source_duplication,
    _rename_swabbing_time,
    _sync_built_in_gate_applicability,
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

    def test_rename_source_duplication_is_registered(self):
        keys = planned_upgrade_migrations("0.11.0", "0.11.1")
        assert "rename-source-duplication-gates" in keys

    def test_sync_built_in_gate_applicability_is_registered(self):
        keys = planned_upgrade_migrations("0.15.0", "0.15.1")
        assert "sync-built-in-gate-applicability" in keys


class TestRenameSourceDuplication:
    """Tests for the 0.11.0→0.11.1 gate rename migration."""

    def _write_config(self, root: Path, data: dict) -> Path:
        cfg = root / ".sb_config.json"
        cfg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return cfg

    def _read_config(self, root: Path) -> dict:
        return json.loads((root / ".sb_config.json").read_text(encoding="utf-8"))

    def test_hierarchical_config_split(self, tmp_path: Path):
        self._write_config(
            tmp_path,
            {
                "myopia": {
                    "enabled": True,
                    "gates": {
                        "source-duplication": {
                            "enabled": True,
                            "threshold": 6,
                            "include_dirs": ["."],
                            "min_tokens": 50,
                            "min_lines": 5,
                            "exclude_dirs": [],
                        }
                    },
                }
            },
        )
        _rename_source_duplication(tmp_path)
        result = self._read_config(tmp_path)

        # Old gate gone
        assert "source-duplication" not in result["myopia"]["gates"]

        # ambiguity-mines.py stays in myopia
        amb = result["myopia"]["gates"]["ambiguity-mines.py"]
        assert amb["enabled"] is True
        assert amb["include_dirs"] == ["."]
        assert amb["exclude_dirs"] == []
        assert "threshold" not in amb
        assert "min_tokens" not in amb

        # repeated-code moves to laziness
        rep = result["laziness"]["gates"]["repeated-code"]
        assert rep["enabled"] is True
        assert rep["threshold"] == 6
        assert rep["min_tokens"] == 50
        assert rep["min_lines"] == 5
        assert rep["include_dirs"] == ["."]

    def test_flat_config_format(self, tmp_path: Path):
        self._write_config(
            tmp_path,
            {
                "myopia:source-duplication": {
                    "enabled": True,
                    "threshold": 10,
                    "include_dirs": ["src"],
                }
            },
        )
        _rename_source_duplication(tmp_path)
        result = self._read_config(tmp_path)

        assert "myopia:source-duplication" not in result
        assert result["myopia:ambiguity-mines.py"]["enabled"] is True
        assert result["laziness:repeated-code"]["threshold"] == 10

    def test_disabled_gates_list_renamed(self, tmp_path: Path):
        self._write_config(
            tmp_path,
            {
                "disabled_gates": [
                    "myopia:source-duplication",
                    "laziness:dead-code.py",
                ],
                "myopia": {
                    "enabled": True,
                    "gates": {
                        "source-duplication": {"enabled": True},
                    },
                },
            },
        )
        _rename_source_duplication(tmp_path)
        result = self._read_config(tmp_path)

        disabled = result["disabled_gates"]
        assert "myopia:source-duplication" not in disabled
        assert "myopia:ambiguity-mines.py" in disabled
        assert "laziness:repeated-code" in disabled
        assert "laziness:dead-code.py" in disabled

    def test_no_config_file_is_noop(self, tmp_path: Path):
        _rename_source_duplication(tmp_path)
        assert not (tmp_path / ".sb_config.json").exists()

    def test_config_without_source_duplication_is_noop(self, tmp_path: Path):
        original = {
            "myopia": {
                "enabled": True,
                "gates": {
                    "ambiguity-mines.py": {"enabled": True},
                },
            },
        }
        self._write_config(tmp_path, original)
        _rename_source_duplication(tmp_path)
        result = self._read_config(tmp_path)
        assert result == original

    def test_preserves_other_gates(self, tmp_path: Path):
        self._write_config(
            tmp_path,
            {
                "myopia": {
                    "enabled": True,
                    "gates": {
                        "source-duplication": {"enabled": True, "threshold": 5},
                        "string-duplication.py": {"enabled": True},
                    },
                },
            },
        )
        _rename_source_duplication(tmp_path)
        result = self._read_config(tmp_path)

        assert "string-duplication.py" in result["myopia"]["gates"]
        assert "ambiguity-mines.py" in result["myopia"]["gates"]
        assert "source-duplication" not in result["myopia"]["gates"]

    def test_end_to_end_via_registry(self, tmp_path: Path):
        self._write_config(
            tmp_path,
            {
                "myopia": {
                    "enabled": True,
                    "gates": {
                        "source-duplication": {"enabled": True},
                    },
                },
            },
        )
        applied = run_upgrade_migrations(tmp_path, "0.11.0", "0.11.1")
        assert "rename-source-duplication-gates" in applied
        result = self._read_config(tmp_path)
        assert "source-duplication" not in result["myopia"]["gates"]
        assert "ambiguity-mines.py" in result["myopia"]["gates"]


class TestRenameSwabbingTime:
    def _write_config(self, tmp_path: Path, data: dict) -> None:
        (tmp_path / ".sb_config.json").write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )

    def _read_config(self, tmp_path: Path) -> dict:
        return json.loads((tmp_path / ".sb_config.json").read_text(encoding="utf-8"))

    def test_renames_swabbing_time_key(self, tmp_path: Path):
        self._write_config(tmp_path, {"swabbing_time": 30, "enabled": True})
        _rename_swabbing_time(tmp_path)
        result = self._read_config(tmp_path)
        assert "swabbing_time" not in result
        assert result["swabbing_timeout"] == 30
        assert result["enabled"] is True

    def test_no_op_when_key_absent(self, tmp_path: Path):
        self._write_config(tmp_path, {"swabbing_timeout": 30})
        _rename_swabbing_time(tmp_path)
        result = self._read_config(tmp_path)
        assert result == {"swabbing_timeout": 30}

    def test_no_op_when_config_missing(self, tmp_path: Path):
        _rename_swabbing_time(tmp_path)  # should not raise
        assert not (tmp_path / ".sb_config.json").exists()

    def test_no_op_when_config_invalid_json(self, tmp_path: Path):
        (tmp_path / ".sb_config.json").write_text("not json!", encoding="utf-8")
        _rename_swabbing_time(tmp_path)  # should not raise
        # File should be unchanged
        assert (tmp_path / ".sb_config.json").read_text() == "not json!"

    def test_end_to_end_via_registry(self, tmp_path: Path):
        self._write_config(tmp_path, {"swabbing_time": 15})
        applied = run_upgrade_migrations(tmp_path, "0.14.1", "0.15.0")
        assert "rename-swabbing-time-to-timeout" in applied
        result = self._read_config(tmp_path)
        assert "swabbing_time" not in result
        assert result["swabbing_timeout"] == 15


class TestRenameDartGates:
    def _write_config(self, tmp_path: Path, data: dict) -> None:
        (tmp_path / ".sb_config.json").write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )

    def _read_config(self, tmp_path: Path) -> dict:
        return json.loads((tmp_path / ".sb_config.json").read_text(encoding="utf-8"))

    def test_renames_flutter_analyze_in_disabled_gates(self, tmp_path: Path):
        self._write_config(
            tmp_path,
            {"disabled_gates": ["overconfidence:flutter-analyze", "other-gate"]},
        )
        _rename_dart_gates(tmp_path)
        result = self._read_config(tmp_path)
        assert "overconfidence:flutter-analyze" not in result["disabled_gates"]
        assert "overconfidence:missing-annotations.dart" in result["disabled_gates"]
        assert "other-gate" in result["disabled_gates"]

    def test_renames_all_three_dart_gates_in_disabled(self, tmp_path: Path):
        self._write_config(
            tmp_path,
            {
                "disabled_gates": [
                    "overconfidence:flutter-analyze",
                    "overconfidence:flutter-test",
                    "laziness:dart-format-check",
                ]
            },
        )
        _rename_dart_gates(tmp_path)
        result = self._read_config(tmp_path)
        assert result["disabled_gates"] == [
            "overconfidence:missing-annotations.dart",
            "overconfidence:untested-code.dart",
            "laziness:sloppy-formatting.dart",
        ]

    def test_renames_flat_gate_config_key(self, tmp_path: Path):
        self._write_config(
            tmp_path,
            {"overconfidence:flutter-analyze": {"enabled": False}},
        )
        _rename_dart_gates(tmp_path)
        result = self._read_config(tmp_path)
        assert "overconfidence:flutter-analyze" not in result
        assert result["overconfidence:missing-annotations.dart"] == {"enabled": False}

    def test_no_op_when_no_dart_refs(self, tmp_path: Path):
        original = {"disabled_gates": ["myopia:ambiguity-mines.py"]}
        self._write_config(tmp_path, original)
        _rename_dart_gates(tmp_path)
        assert self._read_config(tmp_path) == original

    def test_no_op_when_config_missing(self, tmp_path: Path):
        _rename_dart_gates(tmp_path)  # should not raise
        assert not (tmp_path / ".sb_config.json").exists()

    def test_no_op_when_config_invalid_json(self, tmp_path: Path):
        (tmp_path / ".sb_config.json").write_text("{{bad json}}", encoding="utf-8")
        _rename_dart_gates(tmp_path)  # should not raise
        assert (tmp_path / ".sb_config.json").read_text() == "{{bad json}}"

    def test_end_to_end_via_registry(self, tmp_path: Path):
        self._write_config(
            tmp_path,
            {"disabled_gates": ["overconfidence:flutter-test"]},
        )
        applied = run_upgrade_migrations(tmp_path, "0.11.1", "0.12.0")
        assert "rename-dart-gates" in applied
        result = self._read_config(tmp_path)
        assert result["disabled_gates"] == ["overconfidence:untested-code.dart"]


class TestSyncBuiltInGateApplicability:
    def _write_config(self, tmp_path: Path, data: dict) -> None:
        (tmp_path / ".sb_config.json").write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )

    def _read_config(self, tmp_path: Path) -> dict:
        return json.loads((tmp_path / ".sb_config.json").read_text(encoding="utf-8"))

    def test_disables_python_gates_for_requirements_only_repo(self, tmp_path: Path):
        (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
        self._write_config(
            tmp_path,
            {
                "laziness": {
                    "enabled": True,
                    "gates": {
                        "sloppy-formatting.py": {"enabled": True},
                        "sloppy-formatting.js": {"enabled": True},
                    },
                },
                "overconfidence": {
                    "enabled": True,
                    "gates": {
                        "untested-code.py": {"enabled": True, "test_dirs": ["tests"]},
                    },
                },
            },
        )

        _sync_built_in_gate_applicability(tmp_path)
        result = self._read_config(tmp_path)

        assert result["laziness"]["gates"]["sloppy-formatting.py"]["enabled"] is False
        assert result["overconfidence"]["gates"]["untested-code.py"]["enabled"] is False
        assert result["laziness"]["gates"]["sloppy-formatting.js"]["enabled"] is True

    def test_preserves_python_gates_for_real_python_repo(self, tmp_path: Path):
        (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
        self._write_config(
            tmp_path,
            {
                "laziness": {
                    "enabled": True,
                    "gates": {
                        "sloppy-formatting.py": {"enabled": True},
                    },
                },
            },
        )

        _sync_built_in_gate_applicability(tmp_path)
        result = self._read_config(tmp_path)

        assert result["laziness"]["gates"]["sloppy-formatting.py"]["enabled"] is True

    def test_end_to_end_via_registry(self, tmp_path: Path):
        (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        self._write_config(
            tmp_path,
            {
                "laziness": {
                    "enabled": True,
                    "gates": {
                        "sloppy-formatting.py": {"enabled": True},
                    },
                },
            },
        )

        applied = run_upgrade_migrations(tmp_path, "0.15.0", "0.15.1")

        assert "sync-built-in-gate-applicability" in applied
        result = self._read_config(tmp_path)
        assert result["laziness"]["gates"]["sloppy-formatting.py"]["enabled"] is False
