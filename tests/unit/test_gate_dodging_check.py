"""Tests for gate-dodging detection check."""

import json
from pathlib import Path
from unittest.mock import patch

from slopmop.checks.base import ConfigField, Flaw
from slopmop.checks.quality.gate_dodging import (
    JUSTIFICATION_PREFIX,
    GateDodgingCheck,
    _describe_change,
    _detect_loosened_gates,
    _get_base_ref,
    _is_more_permissive,
    _load_base_config,
    _load_current_config,
)
from slopmop.core.result import CheckStatus

# ---------------------------------------------------------------------------
# Metadata / properties
# ---------------------------------------------------------------------------


class TestGateDodgingCheckProperties:
    """Tests for GateDodgingCheck metadata."""

    def test_name(self):
        check = GateDodgingCheck({})
        assert check.name == "gate-dodging"

    def test_full_name(self):
        check = GateDodgingCheck({})
        assert check.full_name == "deceptiveness:gate-dodging"

    def test_display_name(self):
        check = GateDodgingCheck({})
        assert "Gate Dodging" in check.display_name

    def test_docstring_present(self):
        assert GateDodgingCheck.__doc__ is not None
        assert len(GateDodgingCheck.__doc__) > 0

    def test_config_schema_has_base_ref(self):
        check = GateDodgingCheck({})
        schema = check.config_schema
        field_names = [f.name for f in schema]
        assert "base_ref" in field_names

    def test_flaw_is_deceptiveness(self):
        check = GateDodgingCheck({})
        assert check.flaw == Flaw.DECEPTIVENESS


# ---------------------------------------------------------------------------
# _get_base_ref
# ---------------------------------------------------------------------------


class TestGetBaseRef:
    """Test base-ref resolution priority."""

    def test_default_is_origin_main(self):
        with patch.dict("os.environ", {}, clear=True):
            assert _get_base_ref() == "origin/main"

    def test_compare_branch_env_wins(self):
        with patch.dict("os.environ", {"COMPARE_BRANCH": "origin/develop"}, clear=True):
            assert _get_base_ref() == "origin/develop"

    def test_github_base_ref_fallback(self):
        with patch.dict("os.environ", {"GITHUB_BASE_REF": "main"}, clear=True):
            assert _get_base_ref() == "main"

    def test_compare_branch_over_github_base_ref(self):
        with patch.dict(
            "os.environ",
            {"COMPARE_BRANCH": "origin/develop", "GITHUB_BASE_REF": "main"},
            clear=True,
        ):
            assert _get_base_ref() == "origin/develop"


# ---------------------------------------------------------------------------
# _is_more_permissive
# ---------------------------------------------------------------------------


class TestIsMorePermissive:
    """Test permissiveness comparison logic for every type."""

    # ---- higher_is_stricter ----

    def test_higher_is_stricter_lowered(self):
        assert _is_more_permissive("higher_is_stricter", 80, 60) is True

    def test_higher_is_stricter_raised(self):
        assert _is_more_permissive("higher_is_stricter", 60, 80) is False

    def test_higher_is_stricter_unchanged(self):
        assert _is_more_permissive("higher_is_stricter", 80, 80) is False

    # ---- lower_is_stricter ----

    def test_lower_is_stricter_raised(self):
        assert _is_more_permissive("lower_is_stricter", 10, 20) is True

    def test_lower_is_stricter_lowered(self):
        assert _is_more_permissive("lower_is_stricter", 20, 10) is False

    def test_lower_is_stricter_unchanged(self):
        assert _is_more_permissive("lower_is_stricter", 10, 10) is False

    # ---- fewer_is_stricter ----

    def test_fewer_is_stricter_added_exclusion(self):
        assert _is_more_permissive("fewer_is_stricter", ["a"], ["a", "b"]) is True

    def test_fewer_is_stricter_removed_exclusion(self):
        assert _is_more_permissive("fewer_is_stricter", ["a", "b"], ["a"]) is False

    def test_fewer_is_stricter_unchanged(self):
        assert _is_more_permissive("fewer_is_stricter", ["a"], ["a"]) is False

    # ---- more_is_stricter ----

    def test_more_is_stricter_removed_inclusion(self):
        assert _is_more_permissive("more_is_stricter", ["a", "b"], ["a"]) is True

    def test_more_is_stricter_added_inclusion(self):
        assert _is_more_permissive("more_is_stricter", ["a"], ["a", "b"]) is False

    def test_more_is_stricter_unchanged(self):
        assert _is_more_permissive("more_is_stricter", ["a"], ["a"]) is False

    # ---- fail_is_stricter ----

    def test_fail_is_stricter_downgraded(self):
        assert _is_more_permissive("fail_is_stricter", "fail", "warn") is True

    def test_fail_is_stricter_upgraded(self):
        assert _is_more_permissive("fail_is_stricter", "warn", "fail") is False

    def test_fail_is_stricter_unchanged(self):
        assert _is_more_permissive("fail_is_stricter", "fail", "fail") is False

    # ---- true_is_stricter ----

    def test_true_is_stricter_disabled(self):
        assert _is_more_permissive("true_is_stricter", True, False) is True

    def test_true_is_stricter_enabled(self):
        assert _is_more_permissive("true_is_stricter", False, True) is False

    def test_true_is_stricter_unchanged(self):
        assert _is_more_permissive("true_is_stricter", True, True) is False

    # ---- unknown type ----

    def test_unknown_type_returns_false(self):
        assert _is_more_permissive("nonsense_type", 1, 2) is False

    # ---- type errors ----

    def test_higher_with_non_comparable(self):
        assert _is_more_permissive("higher_is_stricter", "x", [1]) is False

    def test_fewer_with_non_list(self):
        assert _is_more_permissive("fewer_is_stricter", 5, 10) is False


# ---------------------------------------------------------------------------
# _describe_change
# ---------------------------------------------------------------------------


class TestDescribeChange:
    """Test human-readable descriptions of changes."""

    def test_true_is_stricter_desc(self):
        desc = _describe_change("true_is_stricter", "strict", True, False)
        assert "enabled" in desc and "disabled" in desc

    def test_fail_is_stricter_desc(self):
        desc = _describe_change("fail_is_stricter", "severity", "fail", "warn")
        assert "fail" in desc and "warn" in desc

    def test_fewer_added_exclusions(self):
        desc = _describe_change("fewer_is_stricter", "exclude_dirs", ["a"], ["a", "b"])
        assert "added exclusions" in desc

    def test_more_removed_entries(self):
        desc = _describe_change("more_is_stricter", "test_dirs", ["a", "b"], ["a"])
        assert "removed entries" in desc

    def test_numeric_change(self):
        desc = _describe_change("higher_is_stricter", "threshold", 80, 60)
        assert "80" in desc and "60" in desc


# ---------------------------------------------------------------------------
# _load_current_config / _load_base_config
# ---------------------------------------------------------------------------


class TestConfigLoading:
    """Test config file loading functions."""

    def test_load_current_config_present(self, tmp_path):
        config = {"laziness": {"enabled": True}}
        (tmp_path / ".sb_config.json").write_text(json.dumps(config))
        result = _load_current_config(str(tmp_path))
        assert result == config

    def test_load_current_config_missing(self, tmp_path):
        result = _load_current_config(str(tmp_path))
        assert result is None

    def test_load_current_config_invalid_json(self, tmp_path):
        (tmp_path / ".sb_config.json").write_text("not json {{{")
        result = _load_current_config(str(tmp_path))
        assert result is None

    def test_load_base_config_not_in_git(self, tmp_path):
        result = _load_base_config(str(tmp_path), "origin/main")
        assert result is None


# ---------------------------------------------------------------------------
# _detect_loosened_gates
# ---------------------------------------------------------------------------


class TestDetectLoosenedGates:
    """Test the core config comparison engine."""

    def _make_schema(
        self, gate: str, field: str, perm: str
    ) -> dict[str, dict[str, ConfigField]]:
        return {
            gate: {
                field: ConfigField(
                    name=field, field_type="int", default=0, permissiveness=perm
                )
            }
        }

    def test_detects_threshold_lowered(self):
        """Lowering a higher_is_stricter threshold is more permissive."""
        base = {"deceptiveness": {"gates": {"py-coverage": {"threshold": 80}}}}
        curr = {"deceptiveness": {"gates": {"py-coverage": {"threshold": 60}}}}
        schema = self._make_schema(
            "deceptiveness:py-coverage", "threshold", "higher_is_stricter"
        )
        changes = _detect_loosened_gates(base, curr, schema)
        assert len(changes) == 1
        assert changes[0].gate == "deceptiveness:py-coverage"
        assert changes[0].field == "threshold"

    def test_no_false_positive_on_tightened(self):
        """Raising a higher_is_stricter threshold is tighter, not looser."""
        base = {"deceptiveness": {"gates": {"py-coverage": {"threshold": 60}}}}
        curr = {"deceptiveness": {"gates": {"py-coverage": {"threshold": 80}}}}
        schema = self._make_schema(
            "deceptiveness:py-coverage", "threshold", "higher_is_stricter"
        )
        changes = _detect_loosened_gates(base, curr, schema)
        assert len(changes) == 0

    def test_detects_category_disabled(self):
        """Disabling an entire category is more permissive."""
        base = {"laziness": {"enabled": True, "gates": {}}}
        curr = {"laziness": {"enabled": False, "gates": {}}}
        schema: dict[str, dict[str, ConfigField]] = {}
        changes = _detect_loosened_gates(base, curr, schema)
        assert len(changes) == 1
        assert changes[0].field == "enabled"
        assert "disabled" in changes[0].description

    def test_detects_complexity_raised(self):
        """Raising max_complexity (lower_is_stricter) is more permissive."""
        base = {"laziness": {"gates": {"complexity": {"max_complexity": 10}}}}
        curr = {"laziness": {"gates": {"complexity": {"max_complexity": 20}}}}
        schema = self._make_schema(
            "laziness:complexity", "max_complexity", "lower_is_stricter"
        )
        changes = _detect_loosened_gates(base, curr, schema)
        assert len(changes) == 1

    def test_detects_exclusion_added(self):
        """Adding an exclude pattern (fewer_is_stricter) is more permissive."""
        base = {"myopia": {"gates": {"security-scan": {"exclude_dirs": ["vendor"]}}}}
        curr = {
            "myopia": {
                "gates": {"security-scan": {"exclude_dirs": ["vendor", "legacy"]}}
            }
        }
        schema = self._make_schema(
            "myopia:security-scan", "exclude_dirs", "fewer_is_stricter"
        )
        changes = _detect_loosened_gates(base, curr, schema)
        assert len(changes) == 1

    def test_detects_severity_downgraded(self):
        """Downgrading from fail to warn (fail_is_stricter) is more permissive."""
        base = {
            "deceptiveness": {"gates": {"bogus-tests": {"short_test_severity": "fail"}}}
        }
        curr = {
            "deceptiveness": {"gates": {"bogus-tests": {"short_test_severity": "warn"}}}
        }
        schema = self._make_schema(
            "deceptiveness:bogus-tests", "short_test_severity", "fail_is_stricter"
        )
        changes = _detect_loosened_gates(base, curr, schema)
        assert len(changes) == 1

    def test_no_change_passes(self):
        """Identical configs produce no changes."""
        config = {"laziness": {"gates": {"complexity": {"max_complexity": 10}}}}
        schema = self._make_schema(
            "laziness:complexity", "max_complexity", "lower_is_stricter"
        )
        changes = _detect_loosened_gates(config, config, schema)
        assert len(changes) == 0

    def test_unknown_gate_ignored(self):
        """Fields in gates not in schema (no permissiveness) are ignored."""
        base = {"laziness": {"gates": {"unknown": {"foo": 1}}}}
        curr = {"laziness": {"gates": {"unknown": {"foo": 100}}}}
        schema: dict[str, dict[str, ConfigField]] = {}
        changes = _detect_loosened_gates(base, curr, schema)
        assert len(changes) == 0

    def test_field_without_permissiveness_ignored(self):
        """Fields whose ConfigField has no permissiveness are skipped."""
        base = {"laziness": {"gates": {"complexity": {"max_complexity": 10}}}}
        curr = {"laziness": {"gates": {"complexity": {"max_complexity": 20}}}}
        schema = {
            "laziness:complexity": {
                "max_complexity": ConfigField(
                    name="max_complexity",
                    field_type="int",
                    default=0,
                    permissiveness=None,
                )
            }
        }
        changes = _detect_loosened_gates(base, curr, schema)
        assert len(changes) == 0

    def test_skips_non_dict_category(self):
        """Non-dict category values (like 'version') don't crash."""
        base = {"version": "1.0", "laziness": {"gates": {}}}
        curr = {"version": "2.0", "laziness": {"gates": {}}}
        changes = _detect_loosened_gates(base, curr, {})
        assert len(changes) == 0

    def test_multiple_changes_detected(self):
        """Multiple loosened fields across gates are all caught."""
        base = {
            "laziness": {
                "gates": {
                    "complexity": {"max_complexity": 10},
                }
            },
            "deceptiveness": {
                "gates": {
                    "py-coverage": {"threshold": 80},
                }
            },
        }
        curr = {
            "laziness": {
                "gates": {
                    "complexity": {"max_complexity": 20},
                }
            },
            "deceptiveness": {
                "gates": {
                    "py-coverage": {"threshold": 50},
                }
            },
        }
        schema = {
            "laziness:complexity": {
                "max_complexity": ConfigField(
                    name="max_complexity",
                    field_type="int",
                    default=10,
                    permissiveness="lower_is_stricter",
                )
            },
            "deceptiveness:py-coverage": {
                "threshold": ConfigField(
                    name="threshold",
                    field_type="float",
                    default=80,
                    permissiveness="higher_is_stricter",
                )
            },
        }
        changes = _detect_loosened_gates(base, curr, schema)
        assert len(changes) == 2


# ---------------------------------------------------------------------------
# is_applicable / skip_reason
# ---------------------------------------------------------------------------


class TestApplicability:
    """Test when the check should/shouldn't run."""

    def test_applicable_with_git_and_config(self, tmp_path):
        """Applicable when .git dir and .sb_config.json both exist."""
        (tmp_path / ".git").mkdir()
        (tmp_path / ".sb_config.json").write_text("{}")
        check = GateDodgingCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_not_applicable_without_git(self, tmp_path):
        """Not applicable outside a git repo."""
        (tmp_path / ".sb_config.json").write_text("{}")
        check = GateDodgingCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_not_applicable_without_config(self, tmp_path):
        """Not applicable if no config file exists."""
        (tmp_path / ".git").mkdir()
        check = GateDodgingCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_skip_reason_no_git(self, tmp_path):
        check = GateDodgingCheck({})
        assert "git" in check.skip_reason(str(tmp_path)).lower()

    def test_skip_reason_no_config(self, tmp_path):
        (tmp_path / ".git").mkdir()
        check = GateDodgingCheck({})
        reason = check.skip_reason(str(tmp_path))
        assert "config" in reason.lower() or "defaults" in reason.lower()


# ---------------------------------------------------------------------------
# run() integration tests (mocked subprocess/registry)
# ---------------------------------------------------------------------------


class TestRunIntegration:
    """Integration tests for the run() method with mocked dependencies."""

    def _write_config(self, tmp_path: Path, config: dict) -> None:
        """Write .sb_config.json to tmp_path."""
        (tmp_path / ".sb_config.json").write_text(json.dumps(config))

    def _make_check(self, **extra_config) -> GateDodgingCheck:
        return GateDodgingCheck(extra_config)

    def test_passes_when_no_config_file(self, tmp_path):
        """No config → PASSED (project uses defaults)."""
        check = self._make_check()
        with (
            patch(
                "slopmop.checks.quality.gate_dodging._load_current_config",
                return_value=None,
            ),
            patch(
                "slopmop.checks.quality.gate_dodging._get_base_ref",
                return_value="origin/main",
            ),
        ):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_passes_when_config_new(self, tmp_path):
        """Config exists locally but not on base branch → initial setup."""
        self._write_config(tmp_path, {"laziness": {"gates": {}}})
        check = self._make_check()
        with (
            patch(
                "slopmop.checks.quality.gate_dodging._load_base_config",
                return_value=None,
            ),
            patch(
                "slopmop.checks.quality.gate_dodging._get_base_ref",
                return_value="origin/main",
            ),
        ):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED
        assert "initial" in result.output.lower()

    def test_passes_when_no_loosening(self, tmp_path):
        """Identical config on both sides → PASSED."""
        config = {"laziness": {"gates": {"complexity": {"max_complexity": 10}}}}
        self._write_config(tmp_path, config)
        check = self._make_check()

        with (
            patch(
                "slopmop.checks.quality.gate_dodging._load_base_config",
                return_value=config,
            ),
            patch(
                "slopmop.checks.quality.gate_dodging._get_base_ref",
                return_value="origin/main",
            ),
            patch(
                "slopmop.checks.quality.gate_dodging._build_schema_lookup",
                return_value={},
            ),
        ):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_warns_when_gate_loosened(self, tmp_path):
        """Loosened threshold → WARNED with helpful output."""
        base_config = {"deceptiveness": {"gates": {"py-coverage": {"threshold": 80}}}}
        curr_config = {"deceptiveness": {"gates": {"py-coverage": {"threshold": 50}}}}
        self._write_config(tmp_path, curr_config)
        check = self._make_check()

        schema_lookup = {
            "deceptiveness:py-coverage": {
                "threshold": ConfigField(
                    name="threshold",
                    field_type="float",
                    default=80,
                    permissiveness="higher_is_stricter",
                )
            }
        }

        with (
            patch(
                "slopmop.checks.quality.gate_dodging._load_base_config",
                return_value=base_config,
            ),
            patch(
                "slopmop.checks.quality.gate_dodging._get_base_ref",
                return_value="origin/main",
            ),
            patch(
                "slopmop.checks.quality.gate_dodging._build_schema_lookup",
                return_value=schema_lookup,
            ),
            patch(
                "slopmop.checks.quality.gate_dodging._detect_pr_number",
                return_value=None,
            ),
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.WARNED
        assert "threshold" in result.output
        assert JUSTIFICATION_PREFIX in result.output

    def test_passes_with_justification_comment(self, tmp_path):
        """Loosened gate + justification comment → PASSED."""
        base_config = {"deceptiveness": {"gates": {"py-coverage": {"threshold": 80}}}}
        curr_config = {"deceptiveness": {"gates": {"py-coverage": {"threshold": 50}}}}
        self._write_config(tmp_path, curr_config)
        check = self._make_check()

        schema_lookup = {
            "deceptiveness:py-coverage": {
                "threshold": ConfigField(
                    name="threshold",
                    field_type="float",
                    default=80,
                    permissiveness="higher_is_stricter",
                )
            }
        }

        with (
            patch(
                "slopmop.checks.quality.gate_dodging._load_base_config",
                return_value=base_config,
            ),
            patch(
                "slopmop.checks.quality.gate_dodging._get_base_ref",
                return_value="origin/main",
            ),
            patch(
                "slopmop.checks.quality.gate_dodging._build_schema_lookup",
                return_value=schema_lookup,
            ),
            patch(
                "slopmop.checks.quality.gate_dodging._detect_pr_number",
                return_value=42,
            ),
            patch(
                "slopmop.checks.quality.gate_dodging._check_justification_comment",
                return_value=True,
            ),
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert "justified" in result.output.lower()

    def test_warns_without_justification_comment(self, tmp_path):
        """Loosened gate + PR but no justification → WARNED."""
        base_config = {"deceptiveness": {"gates": {"py-coverage": {"threshold": 80}}}}
        curr_config = {"deceptiveness": {"gates": {"py-coverage": {"threshold": 50}}}}
        self._write_config(tmp_path, curr_config)
        check = self._make_check()

        schema_lookup = {
            "deceptiveness:py-coverage": {
                "threshold": ConfigField(
                    name="threshold",
                    field_type="float",
                    default=80,
                    permissiveness="higher_is_stricter",
                )
            }
        }

        with (
            patch(
                "slopmop.checks.quality.gate_dodging._load_base_config",
                return_value=base_config,
            ),
            patch(
                "slopmop.checks.quality.gate_dodging._get_base_ref",
                return_value="origin/main",
            ),
            patch(
                "slopmop.checks.quality.gate_dodging._build_schema_lookup",
                return_value=schema_lookup,
            ),
            patch(
                "slopmop.checks.quality.gate_dodging._detect_pr_number",
                return_value=42,
            ),
            patch(
                "slopmop.checks.quality.gate_dodging._check_justification_comment",
                return_value=False,
            ),
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.WARNED

    def test_uses_configured_base_ref(self, tmp_path):
        """base_ref config overrides automatic detection."""
        config = {"laziness": {"gates": {}}}
        self._write_config(tmp_path, config)
        check = self._make_check(base_ref="origin/develop")

        with (
            patch(
                "slopmop.checks.quality.gate_dodging._load_base_config",
                return_value=config,
            ) as mock_load,
            patch(
                "slopmop.checks.quality.gate_dodging._build_schema_lookup",
                return_value={},
            ),
        ):
            result = check.run(str(tmp_path))

        # Should have been called with the configured ref
        mock_load.assert_called_once_with(str(tmp_path), "origin/develop")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    """Verify the check is properly registered."""

    def test_registered_in_registry(self):
        """Gate-dodging check appears in the global registry."""
        from slopmop.checks import ensure_checks_registered
        from slopmop.core.registry import get_registry

        ensure_checks_registered()
        registry = get_registry()
        assert "deceptiveness:gate-dodging" in registry._check_classes
