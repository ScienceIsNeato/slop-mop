"""Tests for config generation utility."""

import json
import os
import tempfile
from pathlib import Path

from slopmop.checks.base import BaseCheck, ConfigField, Flaw, GateCategory
from slopmop.core.registry import CheckRegistry
from slopmop.core.result import CheckResult, CheckStatus
from slopmop.utils.generate_base_config import (
    backup_config,
    generate_base_config,
    generate_config_schema,
    generate_gate_config,
    generate_language_config,
    generate_template_config,
    main,
    write_config,
    write_template_config,
)


class MockCheck(BaseCheck):
    """Mock check for testing config generation."""

    @property
    def name(self) -> str:
        return "mock-check"

    @property
    def display_name(self) -> str:
        return "🧪 Mock Check"

    @property
    def category(self) -> GateCategory:
        return GateCategory.OVERCONFIDENCE

    @property
    def flaw(self) -> Flaw:
        return Flaw.OVERCONFIDENCE

    @property
    def config_schema(self):
        return [
            ConfigField(
                name="threshold",
                field_type="integer",
                default=80,
                description="Test threshold",
                min_value=0,
                max_value=100,
            ),
            ConfigField(
                name="enabled_features",
                field_type="string[]",
                default=["feature1", "feature2"],
                description="Enabled features",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        return True

    def run(self, project_root: str) -> CheckResult:
        return CheckResult(
            name=self.name,
            status=CheckStatus.PASSED,
            duration=0.1,
        )


class TestGenerateGateConfig:
    """Tests for generate_gate_config function."""

    def test_includes_standard_fields(self):
        """Test that standard fields (enabled, auto_fix) are included."""
        check = MockCheck({})
        config = generate_gate_config(check)

        assert "enabled" in config
        assert "auto_fix" in config
        assert config["enabled"] is False
        assert config["auto_fix"] is False

    def test_includes_check_specific_fields(self):
        """Test that check-specific config fields are included."""
        check = MockCheck({})
        config = generate_gate_config(check)

        assert "threshold" in config
        assert config["threshold"] == 80
        assert "enabled_features" in config
        assert config["enabled_features"] == ["feature1", "feature2"]


class TestGenerateLanguageConfig:
    """Tests for generate_language_config function."""

    def test_language_config_structure(self):
        """Test that language config has expected structure."""
        check = MockCheck({})
        config = generate_language_config([check], GateCategory.OVERCONFIDENCE)

        assert "enabled" in config
        assert config["enabled"] is False
        assert "include_dirs" in config
        assert config["include_dirs"] == []
        assert "exclude_dirs" in config
        assert config["exclude_dirs"] == ["slop-mop"]
        assert "gates" in config
        assert "mock-check" in config["gates"]

    def test_language_config_all_enabled(self):
        """Test that all_enabled=True sets category and gates to enabled."""
        check = MockCheck({})
        config = generate_language_config(
            [check], GateCategory.OVERCONFIDENCE, all_enabled=True
        )

        assert config["enabled"] is True
        assert config["gates"]["mock-check"]["enabled"] is True

    def test_gates_contain_check_configs(self):
        """Test that gates dictionary contains check configurations."""
        check = MockCheck({})
        config = generate_language_config([check], GateCategory.OVERCONFIDENCE)

        gate_config = config["gates"]["mock-check"]
        assert "enabled" in gate_config
        assert "threshold" in gate_config


class TestGenerateBaseConfig:
    """Tests for generate_base_config function."""

    def test_base_config_structure(self):
        """Test that base config has expected top-level structure."""
        # Create a registry with a mock check
        registry = CheckRegistry()
        registry.register(MockCheck)

        config = generate_base_config(registry)

        assert "version" in config
        assert config["version"] == "1.0"
        assert "default_profile" in config
        assert config["default_profile"] == "commit"
        assert "overconfidence" in config

    def test_base_config_all_disabled_by_default(self):
        """Test that base config has everything disabled by default."""
        registry = CheckRegistry()
        registry.register(MockCheck)

        config = generate_base_config(registry)

        assert config["overconfidence"]["enabled"] is False
        assert config["overconfidence"]["gates"]["mock-check"]["enabled"] is False

    def test_base_config_all_enabled_when_requested(self):
        """Test that all_enabled=True enables everything."""
        registry = CheckRegistry()
        registry.register(MockCheck)

        config = generate_base_config(registry, all_enabled=True)

        assert config["overconfidence"]["enabled"] is True
        assert config["overconfidence"]["gates"]["mock-check"]["enabled"] is True

    def test_categories_are_included(self):
        """Test that all categories with checks are included."""
        registry = CheckRegistry()
        registry.register(MockCheck)

        config = generate_base_config(registry)

        # Python should be included because MockCheck is registered
        assert "overconfidence" in config
        assert "mock-check" in config["overconfidence"]["gates"]


class TestGenerateConfigSchema:
    """Tests for generate_config_schema function."""

    def test_schema_includes_field_info(self):
        """Test that schema includes field type and description."""
        registry = CheckRegistry()
        registry.register(MockCheck)

        schema = generate_config_schema(registry)

        assert "overconfidence:mock-check" in schema
        check_schema = schema["overconfidence:mock-check"]

        assert "display_name" in check_schema
        assert "category" in check_schema
        assert "fields" in check_schema

        fields = check_schema["fields"]
        assert "threshold" in fields
        assert fields["threshold"]["type"] == "integer"
        assert fields["threshold"]["min"] == 0
        assert fields["threshold"]["max"] == 100


class TestBackupConfig:
    """Tests for backup_config function."""

    def test_backup_creates_timestamped_file(self):
        """Test that backup creates a timestamped backup file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".sb_config.json"
            config_path.write_text('{"test": true}')

            backup_path = backup_config(config_path)

            assert backup_path is not None
            assert backup_path.exists()
            assert ".sb_config.json.backup." in backup_path.name
            assert backup_path.read_text() == '{"test": true}'

    def test_backup_returns_none_if_no_file(self):
        """Test that backup returns None if config doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".sb_config.json"

            result = backup_config(config_path)

            assert result is None


class TestWriteConfig:
    """Tests for write_config function."""

    def test_writes_json_with_formatting(self):
        """Test that config is written as formatted JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".sb_config.json"
            config = {"version": "1.0", "laziness": {"enabled": True}}

            write_config(config_path, config, backup=False)

            content = config_path.read_text()
            # Should be formatted with indentation
            assert "  " in content
            # Should end with newline
            assert content.endswith("\n")
            # Should be valid JSON
            loaded = json.loads(content)
            assert loaded == config

    def test_creates_backup_when_enabled(self):
        """Test that backup is created when enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".sb_config.json"
            config_path.write_text('{"old": true}')

            new_config = {"new": True}
            write_config(config_path, new_config, backup=True)

            # Original file should have new content
            assert json.loads(config_path.read_text()) == new_config
            # Backup should exist
            backups = list(Path(tmpdir).glob(".sb_config.json.backup.*"))
            assert len(backups) == 1


class TestMain:
    """Tests for main function."""

    def test_main_generates_config(self):
        """Test that main function generates a config file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / ".sb_config.json"

            result = main(str(output_path), backup=False)

            assert result == output_path
            assert output_path.exists()
            config = json.loads(output_path.read_text())
            assert "version" in config

    def test_main_defaults_to_cwd(self):
        """Test that main defaults to current directory when no path given."""
        with tempfile.TemporaryDirectory() as tmpdir:
            real_tmpdir = os.path.realpath(tmpdir)
            original_cwd = os.getcwd()
            try:
                os.chdir(real_tmpdir)
                result = main(backup=False)
                assert result == Path(real_tmpdir) / ".sb_config.json"
                assert result.exists()
            finally:
                os.chdir(original_cwd)


class TestTemplateConfig:
    """Tests for template config generation."""

    def test_generate_template_config_has_all_categories(self):
        """Test that template config includes all primary categories."""
        config = generate_template_config()

        assert "overconfidence" in config
        assert "deceptiveness" in config
        assert "laziness" in config
        assert "myopia" in config
        # general category is legacy — deploy/template checks moved to overconfidence/laziness
        assert "general" not in config

    def test_generate_template_config_all_gates_enabled(self):
        """Test that template config has all gates enabled."""
        config = generate_template_config()

        # Check all category-level enabled flags are True
        for category in [
            "overconfidence",
            "deceptiveness",
            "laziness",
            "myopia",
        ]:
            if category in config:
                assert (
                    config[category]["enabled"] is True
                ), f"{category} should be enabled"

                # Check all gates are also enabled
                for gate_name, gate_config in config[category].get("gates", {}).items():
                    assert (
                        gate_config["enabled"] is True
                    ), f"{category}:{gate_name} should be enabled"

    def test_write_template_config_creates_file(self):
        """Test that write_template_config creates the template file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            result = write_template_config(project_root)

            expected_path = project_root / ".sb_config.json.template"
            assert result == expected_path
            assert expected_path.exists()

            # Should be valid JSON
            config = json.loads(expected_path.read_text())
            assert "version" in config

    def test_write_template_config_does_not_create_backup(self):
        """Test that template file is overwritten without backup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            template_path = project_root / ".sb_config.json.template"
            template_path.write_text('{"old": true}')

            write_template_config(project_root)

            # No backup should be created for template
            backups = list(project_root.glob("*.backup.*"))
            assert len(backups) == 0

            # Template should have new content
            config = json.loads(template_path.read_text())
            assert "version" in config
            assert "old" not in config
