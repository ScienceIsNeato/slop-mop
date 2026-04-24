"""Tests for laziness:silenced-gates check."""

import json
from pathlib import Path

from slopmop.checks.base import Flaw, GateCategory
from slopmop.checks.quality.config_debt import (
    ConfigDebtCheck,
    _load_config_json,
    check_disabled_gates,
    check_stale_applicability,
)
from slopmop.core.result import CheckStatus

CONFIG_FILE = ".sb_config.json"


def _write_test_config(root: Path, config: dict) -> None:
    """Write a config dict as .sb_config.json."""
    (root / CONFIG_FILE).write_text(json.dumps(config))


def _make_python_project(root: Path) -> None:
    """Place a Python project marker."""
    (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n")


def _make_javascript_project(root: Path) -> None:
    """Place a JavaScript project marker."""
    (root / "package.json").write_text('{"name": "demo"}')


def _make_dart_project(root: Path) -> None:
    """Place a Dart/Flutter project marker."""
    (root / "pubspec.yaml").write_text("name: demo\n")


# ---------------------------------------------------------------------------
# Metadata / properties
# ---------------------------------------------------------------------------


class TestConfigDebtCheckProperties:
    """Tests for ConfigDebtCheck metadata."""

    def test_name(self):
        check = ConfigDebtCheck({})
        assert check.name == "silenced-gates"

    def test_full_name(self):
        check = ConfigDebtCheck({})
        assert check.full_name == "laziness:silenced-gates"

    def test_display_name(self):
        check = ConfigDebtCheck({})
        assert "Config Debt" in check.display_name

    def test_category(self):
        check = ConfigDebtCheck({})
        assert check.category == GateCategory.LAZINESS

    def test_flaw(self):
        check = ConfigDebtCheck({})
        assert check.flaw == Flaw.LAZINESS

    def test_docstring_present(self):
        assert ConfigDebtCheck.__doc__ is not None
        assert len(ConfigDebtCheck.__doc__) > 0


# ---------------------------------------------------------------------------
# is_applicable / skip_reason
# ---------------------------------------------------------------------------


class TestApplicability:
    def test_applicable_when_config_exists(self, tmp_path: Path):
        _write_test_config(tmp_path, {"version": "1.0"})
        check = ConfigDebtCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_not_applicable_when_no_config(self, tmp_path: Path):
        check = ConfigDebtCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_skip_reason(self, tmp_path: Path):
        check = ConfigDebtCheck({})
        reason = check.skip_reason(str(tmp_path))
        assert "sb_config" in reason.lower() or "config" in reason.lower()


# ---------------------------------------------------------------------------
# _load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_loads_valid_config(self, tmp_path: Path):
        _write_test_config(tmp_path, {"version": "1.0", "laziness": {"enabled": True}})
        config = _load_config_json(tmp_path)
        assert config is not None
        assert config["version"] == "1.0"

    def test_returns_none_for_bad_json(self, tmp_path: Path):
        (tmp_path / CONFIG_FILE).write_text("not json {{{")
        assert _load_config_json(tmp_path) is None

    def test_returns_none_for_missing_file(self, tmp_path: Path):
        assert _load_config_json(tmp_path) is None


# ---------------------------------------------------------------------------
# check_stale_applicability
# ---------------------------------------------------------------------------


class TestStaleApplicability:
    """Scenario 1: language gates disabled but language exists in project."""

    def test_python_gates_disabled_python_present(self, tmp_path: Path):
        """Python gates disabled but pyproject.toml exists → findings."""
        _make_python_project(tmp_path)
        config = {
            "laziness": {
                "enabled": True,
                "gates": {"sloppy-formatting.py": {"enabled": False}},
            },
        }
        findings = check_stale_applicability(tmp_path, config, set())
        assert len(findings) == 1
        assert "python" in findings[0].lower()
        assert "sloppy-formatting.py" in findings[0]

    def test_js_gates_disabled_js_present(self, tmp_path: Path):
        """JavaScript gates disabled but package.json exists → findings."""
        _make_javascript_project(tmp_path)
        config = {
            "overconfidence": {
                "enabled": True,
                "gates": {
                    "untested-code.js": {"enabled": False},
                    "type-blindness.js": {"enabled": False},
                },
            },
        }
        findings = check_stale_applicability(tmp_path, config, set())
        assert len(findings) == 1
        assert "javascript" in findings[0].lower()
        assert "2 javascript gate(s)" in findings[0]

    def test_no_finding_when_language_absent(self, tmp_path: Path):
        """JS gates disabled, no JS in project → nothing to flag."""
        config = {
            "laziness": {
                "enabled": True,
                "gates": {"sloppy-formatting.js": {"enabled": False}},
            },
        }
        findings = check_stale_applicability(tmp_path, config, set())
        assert findings == []

    def test_requirements_only_does_not_trigger_python_stale_warning(
        self, tmp_path: Path
    ):
        """requirements.txt alone should not count as Python for stale config debt."""
        (tmp_path / "requirements.txt").write_text("pytest\n")
        config = {
            "laziness": {
                "enabled": True,
                "gates": {"sloppy-formatting.py": {"enabled": False}},
            },
        }
        findings = check_stale_applicability(tmp_path, config, set())
        assert findings == []

    def test_requirements_with_python_only_in_excluded_dir_stays_absent(
        self, tmp_path: Path
    ):
        """Excluded dirs should not make config debt think Python is present."""
        (tmp_path / "requirements.txt").write_text("pytest\n")
        nested = tmp_path / "node_modules" / "pkg"
        nested.mkdir(parents=True)
        (nested / "tool.py").write_text("print('hi')\n")
        config = {
            "laziness": {
                "enabled": True,
                "gates": {"sloppy-formatting.py": {"enabled": False}},
            },
        }
        findings = check_stale_applicability(tmp_path, config, set())
        assert findings == []

    def test_no_finding_when_gate_enabled(self, tmp_path: Path):
        """Gate is enabled → no debt."""
        _make_python_project(tmp_path)
        config = {
            "laziness": {
                "enabled": True,
                "gates": {"sloppy-formatting.py": {"enabled": True}},
            },
        }
        findings = check_stale_applicability(tmp_path, config, set())
        assert findings == []

    def test_category_disabled_flags_lang_gates(self, tmp_path: Path):
        """Category disabled but language exists → flag language gates."""
        _make_python_project(tmp_path)
        config = {
            "laziness": {
                "enabled": False,
                "gates": {"sloppy-formatting.py": {"enabled": True}},
            },
        }
        findings = check_stale_applicability(tmp_path, config, set())
        assert len(findings) == 1
        assert "sloppy-formatting.py" in findings[0]

    def test_skips_explicitly_disabled_gates(self, tmp_path: Path):
        """Gates in disabled_gates set are not double-counted."""
        _make_python_project(tmp_path)
        config = {
            "laziness": {
                "enabled": True,
                "gates": {"sloppy-formatting.py": {"enabled": False}},
            },
        }
        findings = check_stale_applicability(
            tmp_path, config, {"laziness:sloppy-formatting.py"}
        )
        assert findings == []

    def test_non_language_gates_ignored(self, tmp_path: Path):
        """Gates without a language suffix are not flagged here."""
        _make_python_project(tmp_path)
        config = {
            "laziness": {
                "enabled": True,
                "gates": {
                    "silenced-gates": {"enabled": False},
                },
            },
            "myopia": {
                "enabled": True,
                "gates": {
                    "code-sprawl": {"enabled": False},
                },
            },
        }
        findings = check_stale_applicability(tmp_path, config, set())
        assert findings == []

    def test_groups_by_language(self, tmp_path: Path):
        """Multiple gates for the same language → single grouped finding."""
        _make_python_project(tmp_path)
        config = {
            "laziness": {
                "enabled": True,
                "gates": {"sloppy-formatting.py": {"enabled": False}},
            },
            "overconfidence": {
                "enabled": True,
                "gates": {"untested-code.py": {"enabled": False}},
            },
        }
        findings = check_stale_applicability(tmp_path, config, set())
        assert len(findings) == 1
        assert "2 python gate(s)" in findings[0]

    def test_multiple_languages(self, tmp_path: Path):
        """Both Python and JS present/disabled → two findings."""
        _make_python_project(tmp_path)
        _make_javascript_project(tmp_path)
        config = {
            "laziness": {
                "enabled": True,
                "gates": {
                    "sloppy-formatting.py": {"enabled": False},
                    "sloppy-formatting.js": {"enabled": False},
                },
            },
        }
        findings = check_stale_applicability(tmp_path, config, set())
        assert len(findings) == 2
        langs = [f.split()[1] for f in findings]
        assert "javascript" in langs
        assert "python" in langs

    def test_dart_gates_disabled_dart_present(self, tmp_path: Path):
        """Dart gates disabled but pubspec.yaml exists → findings."""
        _make_dart_project(tmp_path)
        config = {
            "laziness": {
                "enabled": True,
                "gates": {"sloppy-formatting.dart": {"enabled": False}},
            },
        }
        findings = check_stale_applicability(tmp_path, config, set())
        assert len(findings) == 1
        assert "dart" in findings[0].lower()
        assert "sloppy-formatting.dart" in findings[0]


# ---------------------------------------------------------------------------
# check_disabled_gates
# ---------------------------------------------------------------------------


class TestDisabledGates:
    """Scenario 2: gates in the disabled_gates top-level list."""

    def test_reports_disabled_gates(self):
        findings = check_disabled_gates(
            {"laziness:complexity-creep.py", "myopia:vulnerability-blindness.py"}
        )
        assert len(findings) == 2
        # Sorted alphabetically
        assert "laziness:complexity-creep.py" in findings[0]
        assert "myopia:vulnerability-blindness.py" in findings[1]
        assert "explicitly disabled" in findings[0]

    def test_empty_set_no_findings(self):
        assert check_disabled_gates(set()) == []


# ---------------------------------------------------------------------------
# Full run() integration
# ---------------------------------------------------------------------------


class TestConfigDebtRun:
    """Integration tests for the full run() method."""

    def test_clean_config_passes(self, tmp_path: Path):
        """No debt → PASSED."""
        _write_test_config(
            tmp_path,
            {
                "version": "1.0",
                "laziness": {
                    "enabled": True,
                    "gates": {"sloppy-formatting.py": {"enabled": True}},
                },
            },
        )
        check = ConfigDebtCheck({})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED
        assert "healthy" in result.output.lower()

    def test_stale_config_warns(self, tmp_path: Path):
        """Stale applicability → WARNED."""
        _make_python_project(tmp_path)
        _write_test_config(
            tmp_path,
            {
                "laziness": {
                    "enabled": True,
                    "gates": {"sloppy-formatting.py": {"enabled": False}},
                },
            },
        )
        check = ConfigDebtCheck({})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.WARNED
        assert "sloppy-formatting.py" in result.output

    def test_disabled_gate_warns(self, tmp_path: Path):
        """Explicit disabled_gates → WARNED."""
        _write_test_config(
            tmp_path,
            {
                "version": "1.0",
                "disabled_gates": ["laziness:complexity-creep.py"],
            },
        )
        check = ConfigDebtCheck({})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.WARNED
        assert "laziness:complexity-creep.py" in result.output

    def test_multiple_findings_combined(self, tmp_path: Path):
        """Multiple debt items → single WARNED with count."""
        _make_python_project(tmp_path)
        _write_test_config(
            tmp_path,
            {
                "disabled_gates": ["myopia:vulnerability-blindness.py"],
                "laziness": {
                    "enabled": True,
                    "gates": {"sloppy-formatting.py": {"enabled": False}},
                },
            },
        )
        check = ConfigDebtCheck({})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.WARNED
        # Should have 2 findings: stale + disabled
        assert "2 config debt item(s)" in result.output

    def test_never_fails(self, tmp_path: Path):
        """Even with lots of debt, status is WARNED not FAILED."""
        _make_python_project(tmp_path)
        _make_javascript_project(tmp_path)
        _write_test_config(
            tmp_path,
            {
                "disabled_gates": ["a:b", "c:d", "e:f"],
                "laziness": {
                    "enabled": True,
                    "gates": {
                        "sloppy-formatting.py": {"enabled": False},
                        "sloppy-formatting.js": {"enabled": False},
                    },
                },
            },
        )
        check = ConfigDebtCheck({})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.WARNED
        assert result.status != CheckStatus.FAILED

    def test_unparseable_config_passes(self, tmp_path: Path):
        """If config can't be parsed, gracefully pass."""
        (tmp_path / CONFIG_FILE).write_text("not json")
        check = ConfigDebtCheck({})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_has_duration(self, tmp_path: Path):
        """Result always includes a duration."""
        _write_test_config(tmp_path, {"version": "1.0"})
        check = ConfigDebtCheck({})
        result = check.run(str(tmp_path))
        assert result.duration >= 0

    def test_error_field_set_on_warn(self, tmp_path: Path):
        """WARNED result populates the error field for display."""
        _write_test_config(
            tmp_path,
            {"disabled_gates": ["laziness:complexity-creep.py"]},
        )
        check = ConfigDebtCheck({})
        result = check.run(str(tmp_path))
        assert result.error is not None
        assert "config debt" in result.error.lower()
