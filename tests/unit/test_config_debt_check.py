"""Tests for laziness:config-debt check."""

import json
from pathlib import Path

import pytest

from slopmop.checks.base import Flaw, GateCategory
from slopmop.checks.quality.config_debt import (
    ConfigDebtCheck,
    _load_config,
    check_disabled_gates,
    check_scope_drift,
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
# check_scope_drift
# ---------------------------------------------------------------------------


class TestScopeDrift:
    """Scenario 3: include/exclude dirs differ from generated baseline."""

    def test_extra_excludes_flagged(self):
        """Excludes in current but not baseline → finding."""
        config = {
            "laziness": {"exclude_dirs": ["slop-mop", "vendor", "legacy"]},
        }
        baseline = {
            "laziness": {"exclude_dirs": ["slop-mop"]},
        }
        findings = check_scope_drift(config, baseline)
        assert len(findings) == 1
        assert "2 extra exclude_dirs" in findings[0]
        assert "legacy" in findings[0]
        assert "vendor" in findings[0]

    def test_no_finding_when_excludes_match(self):
        """Excludes identical to baseline → no finding."""
        config = {
            "laziness": {"exclude_dirs": ["slop-mop"]},
        }
        baseline = {
            "laziness": {"exclude_dirs": ["slop-mop"]},
        }
        findings = check_scope_drift(config, baseline)
        assert findings == []

    def test_missing_includes_flagged(self):
        """Includes in baseline but missing from current → finding."""
        config = {
            "laziness": {"include_dirs": []},
        }
        baseline = {
            "laziness": {"include_dirs": ["src", "lib"]},
        }
        findings = check_scope_drift(config, baseline)
        assert len(findings) == 1
        assert "2 include_dirs removed" in findings[0]
        assert "src" in findings[0]
        assert "lib" in findings[0]

    def test_no_finding_when_includes_match(self):
        """Includes identical to baseline → no finding."""
        config = {
            "laziness": {"include_dirs": ["src"]},
        }
        baseline = {
            "laziness": {"include_dirs": ["src"]},
        }
        findings = check_scope_drift(config, baseline)
        assert findings == []

    def test_extra_includes_not_flagged(self):
        """More includes than baseline is fine (not narrowing scope)."""
        config = {
            "laziness": {"include_dirs": ["src", "lib", "extra"]},
        }
        baseline = {
            "laziness": {"include_dirs": ["src"]},
        }
        findings = check_scope_drift(config, baseline)
        assert findings == []

    def test_fewer_excludes_not_flagged(self):
        """Fewer excludes than baseline is fine (widening scope)."""
        config = {
            "laziness": {"exclude_dirs": []},
        }
        baseline = {
            "laziness": {"exclude_dirs": ["slop-mop"]},
        }
        findings = check_scope_drift(config, baseline)
        assert findings == []

    def test_multiple_categories(self):
        """Drift in multiple categories → separate findings."""
        config = {
            "laziness": {"exclude_dirs": ["slop-mop", "vendor"]},
            "myopia": {"exclude_dirs": ["slop-mop", "old_code"]},
        }
        baseline = {
            "laziness": {"exclude_dirs": ["slop-mop"]},
            "myopia": {"exclude_dirs": ["slop-mop"]},
        }
        findings = check_scope_drift(config, baseline)
        assert len(findings) == 2

    def test_category_missing_from_baseline(self):
        """Category in current but not baseline → skipped."""
        config = {
            "laziness": {"exclude_dirs": ["slop-mop", "vendor"]},
        }
        baseline = {}  # no laziness category
        findings = check_scope_drift(config, baseline)
        assert findings == []

    def test_category_missing_from_current(self):
        """Category in baseline but not current → skipped."""
        config = {}
        baseline = {
            "laziness": {"include_dirs": ["src"]},
        }
        findings = check_scope_drift(config, baseline)
        assert findings == []

    def test_both_excludes_and_includes_drift(self):
        """Both extra excludes and missing includes in same category."""
        config = {
            "laziness": {
                "exclude_dirs": ["slop-mop", "vendor"],
                "include_dirs": [],
            },
        }
        baseline = {
            "laziness": {
                "exclude_dirs": ["slop-mop"],
                "include_dirs": ["src"],
            },
        }
        findings = check_scope_drift(config, baseline)
        assert len(findings) == 2


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

    def test_scope_drift_warns(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Extra excludes beyond baseline → WARNED."""
        _write_config(
            tmp_path,
            {
                "laziness": {"exclude_dirs": ["slop-mop", "vendor"]},
            },
        )
        monkeypatch.setattr(
            "slopmop.utils.generate_base_config.generate_base_config",
            lambda: {"laziness": {"exclude_dirs": ["slop-mop"]}},
        )
        check = ConfigDebtCheck({})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.WARNED
        assert "vendor" in result.output

    def test_multiple_findings_combined(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Multiple debt items → single WARNED with count."""
        _make_python_project(tmp_path)
        _write_config(
            tmp_path,
            {
                "disabled_gates": ["myopia:security-scan"],
                "laziness": {
                    "enabled": True,
                    "exclude_dirs": ["slop-mop", "vendor"],
                    "gates": {"py-lint": {"enabled": False}},
                },
            },
        )
        monkeypatch.setattr(
            "slopmop.utils.generate_base_config.generate_base_config",
            lambda: {"laziness": {"exclude_dirs": ["slop-mop"]}},
        )
        check = ConfigDebtCheck({})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.WARNED
        # Should have 3 findings: stale, disabled, scope drift
        assert "3 config debt item(s)" in result.output

    def test_never_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Even with lots of debt, status is WARNED not FAILED."""
        _make_python_project(tmp_path)
        _make_javascript_project(tmp_path)
        _write_config(
            tmp_path,
            {
                "disabled_gates": ["a:b", "c:d", "e:f"],
                "laziness": {
                    "enabled": True,
                    "exclude_dirs": ["slop-mop", "hidden_code"],
                    "gates": {
                        "py-lint": {"enabled": False},
                        "js-lint": {"enabled": False},
                    },
                },
            },
        )
        monkeypatch.setattr(
            "slopmop.utils.generate_base_config.generate_base_config",
            lambda: {"laziness": {"exclude_dirs": ["slop-mop"]}},
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
