"""Tests for laziness:config-debt check."""

import json
from pathlib import Path

from slopmop.checks.base import Flaw, GateCategory
from slopmop.checks.quality.config_debt import (
    _BENIGN_EXCLUDES,
    _EXCLUDE_FILE_THRESHOLD,
    ConfigDebtCheck,
    _load_config,
    check_disabled_gates,
    check_exclude_drift,
    check_stale_applicability,
)
from slopmop.core.result import CheckStatus

CONFIG_FILE = ".sb_config.json"


def _write_config(root: Path, config: dict) -> None:
    """Write a config dict as .sb_config.json."""
    (root / CONFIG_FILE).write_text(json.dumps(config))


def _make_python_project(root: Path) -> None:
    """Place a Python project marker."""
    (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n")


def _make_javascript_project(root: Path) -> None:
    """Place a JavaScript project marker."""
    (root / "package.json").write_text('{"name": "demo"}')


def _populate_source_files(directory: Path, count: int, ext: str = ".py") -> None:
    """Create *count* dummy source files in *directory*."""
    directory.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (directory / f"file_{i}{ext}").write_text(f"# file {i}\n")


# ---------------------------------------------------------------------------
# Metadata / properties
# ---------------------------------------------------------------------------


class TestConfigDebtCheckProperties:
    """Tests for ConfigDebtCheck metadata."""

    def test_name(self):
        check = ConfigDebtCheck({})
        assert check.name == "config-debt"

    def test_full_name(self):
        check = ConfigDebtCheck({})
        assert check.full_name == "laziness:config-debt"

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
        _write_config(tmp_path, {"version": "1.0"})
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
        _write_config(tmp_path, {"version": "1.0", "laziness": {"enabled": True}})
        config = _load_config(tmp_path)
        assert config is not None
        assert config["version"] == "1.0"

    def test_returns_none_for_bad_json(self, tmp_path: Path):
        (tmp_path / CONFIG_FILE).write_text("not json {{{")
        assert _load_config(tmp_path) is None

    def test_returns_none_for_missing_file(self, tmp_path: Path):
        assert _load_config(tmp_path) is None


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
                "gates": {"py-lint": {"enabled": False}},
            },
        }
        findings = check_stale_applicability(tmp_path, config, set())
        assert len(findings) == 1
        assert "python" in findings[0].lower()
        assert "py-lint" in findings[0]

    def test_js_gates_disabled_js_present(self, tmp_path: Path):
        """JavaScript gates disabled but package.json exists → findings."""
        _make_javascript_project(tmp_path)
        config = {
            "overconfidence": {
                "enabled": True,
                "gates": {
                    "js-tests": {"enabled": False},
                    "js-types": {"enabled": False},
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
                "gates": {"js-lint": {"enabled": False}},
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
                "gates": {"py-lint": {"enabled": True}},
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
                "gates": {"py-lint": {"enabled": True}},
            },
        }
        findings = check_stale_applicability(tmp_path, config, set())
        assert len(findings) == 1
        assert "py-lint" in findings[0]

    def test_skips_explicitly_disabled_gates(self, tmp_path: Path):
        """Gates in disabled_gates set are not double-counted."""
        _make_python_project(tmp_path)
        config = {
            "laziness": {
                "enabled": True,
                "gates": {"py-lint": {"enabled": False}},
            },
        }
        findings = check_stale_applicability(tmp_path, config, {"laziness:py-lint"})
        assert findings == []

    def test_non_language_gates_ignored(self, tmp_path: Path):
        """Gates without a language prefix are not flagged here."""
        _make_python_project(tmp_path)
        config = {
            "laziness": {
                "enabled": True,
                "gates": {
                    "complexity": {"enabled": False},
                    "dead-code": {"enabled": False},
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
                "gates": {"py-lint": {"enabled": False}},
            },
            "overconfidence": {
                "enabled": True,
                "gates": {"py-tests": {"enabled": False}},
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
                    "py-lint": {"enabled": False},
                    "js-lint": {"enabled": False},
                },
            },
        }
        findings = check_stale_applicability(tmp_path, config, set())
        assert len(findings) == 2
        langs = [f.split()[1] for f in findings]
        assert "javascript" in langs
        assert "python" in langs


# ---------------------------------------------------------------------------
# check_disabled_gates
# ---------------------------------------------------------------------------


class TestDisabledGates:
    """Scenario 2: gates in the disabled_gates top-level list."""

    def test_reports_disabled_gates(self):
        findings = check_disabled_gates({"laziness:complexity", "myopia:security-scan"})
        assert len(findings) == 2
        # Sorted alphabetically
        assert "laziness:complexity" in findings[0]
        assert "myopia:security-scan" in findings[1]
        assert "explicitly disabled" in findings[0]

    def test_empty_set_no_findings(self):
        assert check_disabled_gates(set()) == []


# ---------------------------------------------------------------------------
# check_exclude_drift
# ---------------------------------------------------------------------------


class TestExcludeDrift:
    """Scenario 3: exclude_dirs containing source files."""

    def test_flags_dir_with_source_files(self, tmp_path: Path):
        """Excluded dir with many source files → flag it."""
        _populate_source_files(tmp_path / "my_module", _EXCLUDE_FILE_THRESHOLD)
        config = {
            "laziness": {
                "exclude_dirs": ["my_module"],
            },
        }
        findings = check_exclude_drift(tmp_path, config)
        assert len(findings) == 1
        assert "my_module" in findings[0]
        assert "source files" in findings[0]

    def test_no_flag_below_threshold(self, tmp_path: Path):
        """Few source files → not interesting enough to flag."""
        _populate_source_files(tmp_path / "my_module", _EXCLUDE_FILE_THRESHOLD - 1)
        config = {
            "laziness": {
                "exclude_dirs": ["my_module"],
            },
        }
        findings = check_exclude_drift(tmp_path, config)
        assert findings == []

    def test_benign_dirs_skipped(self, tmp_path: Path):
        """Well-known dirs like node_modules are not flagged."""
        for benign in ("node_modules", ".venv", "slop-mop"):
            assert benign in _BENIGN_EXCLUDES
        config = {
            "laziness": {
                "exclude_dirs": ["node_modules", ".venv", "slop-mop"],
            },
        }
        # Even if they exist with source files, skip
        _populate_source_files(tmp_path / "node_modules", 100)
        findings = check_exclude_drift(tmp_path, config)
        assert findings == []

    def test_dot_dirs_skipped(self, tmp_path: Path):
        """Dot-prefixed dirs are skipped."""
        _populate_source_files(tmp_path / ".hidden", _EXCLUDE_FILE_THRESHOLD)
        config = {
            "laziness": {
                "exclude_dirs": [".hidden"],
            },
        }
        findings = check_exclude_drift(tmp_path, config)
        assert findings == []

    def test_glob_patterns_skipped(self, tmp_path: Path):
        """Glob patterns in exclude_dirs are skipped."""
        config = {
            "laziness": {
                "exclude_dirs": ["**/test_*", "*.egg-info"],
            },
        }
        findings = check_exclude_drift(tmp_path, config)
        assert findings == []

    def test_nonexistent_dir_skipped(self, tmp_path: Path):
        """Excluded dir that doesn't exist is silently ignored."""
        config = {
            "laziness": {
                "exclude_dirs": ["does_not_exist"],
            },
        }
        findings = check_exclude_drift(tmp_path, config)
        assert findings == []

    def test_deduplicates_across_categories(self, tmp_path: Path):
        """Same dir excluded by two categories → one finding."""
        _populate_source_files(tmp_path / "shared_exclude", _EXCLUDE_FILE_THRESHOLD)
        config = {
            "laziness": {"exclude_dirs": ["shared_exclude"]},
            "myopia": {"exclude_dirs": ["shared_exclude"]},
        }
        findings = check_exclude_drift(tmp_path, config)
        assert len(findings) == 1

    def test_js_source_files_detected(self, tmp_path: Path):
        """JavaScript/TypeScript files also count."""
        _populate_source_files(
            tmp_path / "legacy_module", _EXCLUDE_FILE_THRESHOLD, ext=".ts"
        )
        config = {
            "overconfidence": {
                "exclude_dirs": ["legacy_module"],
            },
        }
        findings = check_exclude_drift(tmp_path, config)
        assert len(findings) == 1


# ---------------------------------------------------------------------------
# Full run() integration
# ---------------------------------------------------------------------------


class TestConfigDebtRun:
    """Integration tests for the full run() method."""

    def test_clean_config_passes(self, tmp_path: Path):
        """No debt → PASSED."""
        _write_config(
            tmp_path,
            {
                "version": "1.0",
                "laziness": {
                    "enabled": True,
                    "gates": {"py-lint": {"enabled": True}},
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
        _write_config(
            tmp_path,
            {
                "laziness": {
                    "enabled": True,
                    "gates": {"py-lint": {"enabled": False}},
                },
            },
        )
        check = ConfigDebtCheck({})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.WARNED
        assert "py-lint" in result.output

    def test_disabled_gate_warns(self, tmp_path: Path):
        """Explicit disabled_gates → WARNED."""
        _write_config(
            tmp_path,
            {
                "version": "1.0",
                "disabled_gates": ["laziness:complexity"],
            },
        )
        check = ConfigDebtCheck({})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.WARNED
        assert "laziness:complexity" in result.output

    def test_exclude_drift_warns(self, tmp_path: Path):
        """Exclude dir with source files → WARNED."""
        _populate_source_files(tmp_path / "my_module", _EXCLUDE_FILE_THRESHOLD)
        _write_config(
            tmp_path,
            {
                "laziness": {"exclude_dirs": ["my_module"]},
            },
        )
        check = ConfigDebtCheck({})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.WARNED
        assert "my_module" in result.output

    def test_multiple_findings_combined(self, tmp_path: Path):
        """Multiple debt items → single WARNED with count."""
        _make_python_project(tmp_path)
        _populate_source_files(tmp_path / "excluded", _EXCLUDE_FILE_THRESHOLD)
        _write_config(
            tmp_path,
            {
                "disabled_gates": ["myopia:security-scan"],
                "laziness": {
                    "enabled": True,
                    "exclude_dirs": ["excluded"],
                    "gates": {"py-lint": {"enabled": False}},
                },
            },
        )
        check = ConfigDebtCheck({})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.WARNED
        # Should have 3 findings: stale, disabled, exclude
        assert "3 config debt item(s)" in result.output

    def test_never_fails(self, tmp_path: Path):
        """Even with lots of debt, status is WARNED not FAILED."""
        _make_python_project(tmp_path)
        _make_javascript_project(tmp_path)
        _populate_source_files(tmp_path / "hidden_code", _EXCLUDE_FILE_THRESHOLD)
        _write_config(
            tmp_path,
            {
                "disabled_gates": ["a:b", "c:d", "e:f"],
                "laziness": {
                    "enabled": True,
                    "exclude_dirs": ["hidden_code"],
                    "gates": {
                        "py-lint": {"enabled": False},
                        "js-lint": {"enabled": False},
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
        _write_config(tmp_path, {"version": "1.0"})
        check = ConfigDebtCheck({})
        result = check.run(str(tmp_path))
        assert result.duration >= 0

    def test_error_field_set_on_warn(self, tmp_path: Path):
        """WARNED result populates the error field for display."""
        _write_config(
            tmp_path,
            {"disabled_gates": ["laziness:complexity"]},
        )
        check = ConfigDebtCheck({})
        result = check.run(str(tmp_path))
        assert result.error is not None
        assert "config debt" in result.error.lower()
