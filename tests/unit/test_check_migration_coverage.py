"""Tests for scripts/check_migration_coverage.py."""

# Import the script as a module — it uses __name__ == "__main__" guard
import importlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture()
def script_module():
    """Import the check_migration_coverage script as a module."""
    scripts_dir = Path(__file__).resolve().parent.parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        mod = importlib.import_module("check_migration_coverage")
        yield mod
    finally:
        sys.path.pop(0)
        sys.modules.pop("check_migration_coverage", None)


class TestGateNamesFromTemplate:
    def test_extracts_gate_names(self, script_module):
        template = json.dumps(
            {
                "version": "1.0",
                "laziness": {
                    "enabled": True,
                    "gates": {
                        "repeated-code": {"enabled": True},
                        "dead-code.py": {"enabled": True},
                    },
                },
                "myopia": {
                    "enabled": True,
                    "gates": {
                        "ambiguity-mines.py": {"enabled": True},
                    },
                },
            }
        )
        names = script_module._gate_names_from_template(template)
        assert names == {
            "laziness:repeated-code",
            "laziness:dead-code.py",
            "myopia:ambiguity-mines.py",
        }

    def test_empty_json(self, script_module):
        assert script_module._gate_names_from_template("{}") == set()

    def test_invalid_json(self, script_module):
        assert script_module._gate_names_from_template("not json") == set()


class TestMainFunction:
    def _mock_git_show(self, ref, path):
        """Default mock that returns None (file not found)."""
        return None

    def test_pass_when_no_gate_changes(self, script_module, tmp_path, monkeypatch):
        template = json.dumps(
            {
                "laziness": {"enabled": True, "gates": {"foo": {"enabled": True}}},
            }
        )
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".sb_config.json.template").write_text(template)

        with (
            patch.object(script_module, "_git_merge_base", return_value="abc123"),
            patch.object(script_module, "_git_show", return_value=template),
        ):
            assert script_module.main() == 0

    def test_pass_when_names_changed_and_migration_updated(
        self, script_module, tmp_path, monkeypatch
    ):
        old = json.dumps(
            {
                "myopia": {"enabled": True, "gates": {"source-duplication": {}}},
            }
        )
        new = json.dumps(
            {
                "myopia": {"enabled": True, "gates": {"ambiguity-mines.py": {}}},
                "laziness": {"enabled": True, "gates": {"repeated-code": {}}},
            }
        )
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".sb_config.json.template").write_text(new)

        with (
            patch.object(script_module, "_git_merge_base", return_value="abc123"),
            patch.object(script_module, "_git_show", return_value=old),
            patch.object(
                script_module,
                "_changed_files",
                return_value={
                    "slopmop/migrations/__init__.py",
                    ".sb_config.json.template",
                },
            ),
        ):
            assert script_module.main() == 0

    def test_fail_when_names_changed_but_no_migration(
        self, script_module, tmp_path, monkeypatch
    ):
        old = json.dumps(
            {
                "myopia": {"enabled": True, "gates": {"source-duplication": {}}},
            }
        )
        new = json.dumps(
            {
                "myopia": {"enabled": True, "gates": {"ambiguity-mines.py": {}}},
            }
        )
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".sb_config.json.template").write_text(new)

        with (
            patch.object(script_module, "_git_merge_base", return_value="abc123"),
            patch.object(script_module, "_git_show", return_value=old),
            patch.object(
                script_module,
                "_changed_files",
                return_value={".sb_config.json.template"},
            ),
        ):
            assert script_module.main() == 1

    def test_pass_on_base_branch(self, script_module, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch.object(script_module, "_git_merge_base", return_value=None):
            assert script_module.main() == 0

    def test_pass_when_no_template_exists(self, script_module, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with (
            patch.object(script_module, "_git_merge_base", return_value="abc123"),
            patch.object(script_module, "_git_show", return_value=None),
        ):
            assert script_module.main() == 0

    def test_pass_when_only_gates_added(self, script_module, tmp_path, monkeypatch):
        old = json.dumps(
            {
                "laziness": {"enabled": True, "gates": {"foo": {}}},
            }
        )
        new = json.dumps(
            {
                "laziness": {"enabled": True, "gates": {"foo": {}, "bar": {}}},
            }
        )
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".sb_config.json.template").write_text(new)

        with (
            patch.object(script_module, "_git_merge_base", return_value="abc123"),
            patch.object(script_module, "_git_show", return_value=old),
        ):
            assert script_module.main() == 0
