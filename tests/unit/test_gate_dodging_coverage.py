"""Coverage tests for gate-dodging internal helpers.

These tests target the edge-case branches in the gate-dodging check
that are not exercised by the main functional tests in
test_gate_dodging_check.py.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from slopmop.checks.base import ConfigField, Flaw
from slopmop.checks.quality.gate_dodging import (
    JUSTIFICATION_PREFIX,
    GateDodgingCheck,
    _build_schema_lookup,
    _check_justification_comment,
    _describe_change,
    _detect_loosened_gates,
    _detect_pr_number,
    _is_more_permissive,
    _load_base_config,
)
from slopmop.core.result import CheckStatus

# ---------------------------------------------------------------------------
# _load_base_config — success & exception paths
# ---------------------------------------------------------------------------


class TestLoadBaseConfigPaths:
    """Cover the success path (returncode 0) and exception branches."""

    def test_success_returns_parsed_json(self, tmp_path):
        """When git show succeeds, parse and return the JSON."""
        config = {"laziness": {"enabled": True}}
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(config), stderr=""
        )
        with patch(
            "slopmop.checks.quality.gate_dodging.subprocess.run",
            return_value=mock_result,
        ):
            result = _load_base_config(str(tmp_path), "origin/main")
        assert result == config

    def test_nonzero_returncode_returns_none(self, tmp_path):
        """When git show fails (file missing on branch), return None."""
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=128, stdout="", stderr="fatal: not found"
        )
        with patch(
            "slopmop.checks.quality.gate_dodging.subprocess.run",
            return_value=mock_result,
        ):
            result = _load_base_config(str(tmp_path), "origin/main")
        assert result is None

    def test_timeout_returns_none(self, tmp_path):
        """TimeoutExpired → None."""
        with patch(
            "slopmop.checks.quality.gate_dodging.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=10),
        ):
            result = _load_base_config(str(tmp_path), "origin/main")
        assert result is None

    def test_invalid_json_returns_none(self, tmp_path):
        """Successful returncode but mangled JSON → None."""
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="not json {{{", stderr=""
        )
        with patch(
            "slopmop.checks.quality.gate_dodging.subprocess.run",
            return_value=mock_result,
        ):
            result = _load_base_config(str(tmp_path), "origin/main")
        assert result is None

    def test_file_not_found_returns_none(self, tmp_path):
        """git binary missing → FileNotFoundError → None."""
        with patch(
            "slopmop.checks.quality.gate_dodging.subprocess.run",
            side_effect=FileNotFoundError("git not found"),
        ):
            result = _load_base_config(str(tmp_path), "origin/main")
        assert result is None


# ---------------------------------------------------------------------------
# _is_more_permissive — edge cases
# ---------------------------------------------------------------------------


class TestIsMorePermissiveEdgeCases:
    """Cover remaining branches not hit by TestIsMorePermissive."""

    def test_lower_is_stricter_non_numeric(self):
        """Non-numeric values for lower_is_stricter → False."""
        assert _is_more_permissive("lower_is_stricter", "x", "y") is False

    def test_fewer_is_stricter_both_empty(self):
        """Empty lists for fewer_is_stricter → False."""
        assert _is_more_permissive("fewer_is_stricter", [], []) is False

    def test_more_is_stricter_both_empty(self):
        """Empty lists for more_is_stricter → False."""
        assert _is_more_permissive("more_is_stricter", [], []) is False

    def test_more_is_stricter_non_list(self):
        """Non-list values for more_is_stricter → False."""
        assert _is_more_permissive("more_is_stricter", 5, 10) is False


# ---------------------------------------------------------------------------
# _describe_change — edge cases
# ---------------------------------------------------------------------------


class TestDescribeChangeEdgeCases:
    """Cover remaining branches in _describe_change."""

    def test_fewer_is_stricter_non_list(self):
        """Non-list values for fewer_is_stricter fall through to default."""
        desc = _describe_change("fewer_is_stricter", "field", 5, 10)
        assert "5" in desc and "10" in desc

    def test_more_is_stricter_non_list(self):
        """Non-list values for more_is_stricter fall through to default."""
        desc = _describe_change("more_is_stricter", "field", 5, 10)
        assert "5" in desc and "10" in desc

    def test_unknown_permissiveness_fallthrough(self):
        """Unknown permissiveness type uses default description."""
        desc = _describe_change("unknown_type", "field", "old", "new")
        assert "old" in desc and "new" in desc


# ---------------------------------------------------------------------------
# _build_schema_lookup
# ---------------------------------------------------------------------------


class TestBuildSchemaLookup:
    """Test that _build_schema_lookup returns a populated dict."""

    def test_returns_dict_with_gates(self):
        """Schema lookup should contain at least one gate with fields."""
        lookup = _build_schema_lookup()
        assert isinstance(lookup, dict)
        assert len(lookup) > 0
        # Every entry should be a dict of field_name → ConfigField
        for gate_name, fields in lookup.items():
            assert isinstance(gate_name, str)
            assert isinstance(fields, dict)
            for field_name, cf in fields.items():
                assert isinstance(field_name, str)
                assert isinstance(cf, ConfigField)

    def test_contains_known_gate(self):
        """Should contain at least the bogus-tests check we just worked on."""
        lookup = _build_schema_lookup()
        assert "deceptiveness:bogus-tests" in lookup
        assert "deceptiveness:gate-dodging" in lookup


# ---------------------------------------------------------------------------
# _detect_loosened_gates — edge cases
# ---------------------------------------------------------------------------


class TestDetectLoosenedGatesEdgeCases:
    """Cover remaining branches in the comparison engine."""

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

    def test_non_dict_category_value_skipped(self):
        """Non-dict category value (not version/default_profile) is skipped."""
        base = {"laziness": "not_a_dict"}
        curr = {"laziness": "also_not_a_dict"}
        changes = _detect_loosened_gates(base, curr, {})
        assert len(changes) == 0

    def test_non_dict_gate_values_skipped(self):
        """Non-dict entries within gates are skipped."""
        base = {"laziness": {"gates": {"complexity": "not_a_dict"}}}
        curr = {"laziness": {"gates": {"complexity": "also_not_a_dict"}}}
        changes = _detect_loosened_gates(base, curr, {})
        assert len(changes) == 0

    def test_non_dict_gates_container_skipped(self):
        """Non-dict 'gates' value is skipped entirely."""
        base = {"laziness": {"gates": "not_a_dict"}}
        curr = {"laziness": {"gates": "also_not_a_dict"}}
        changes = _detect_loosened_gates(base, curr, {})
        assert len(changes) == 0

    def test_field_added_non_enabled_skipped(self):
        """New field that didn't exist on base (not 'enabled') is skipped."""
        base = {"laziness": {"gates": {"complexity": {}}}}
        curr = {"laziness": {"gates": {"complexity": {"max_complexity": 20}}}}
        schema = self._make_schema(
            "laziness:complexity", "max_complexity", "lower_is_stricter"
        )
        changes = _detect_loosened_gates(base, curr, schema)
        assert len(changes) == 0

    def test_field_removed_non_enabled_skipped(self):
        """Field removed (new=None, not 'enabled') is skipped."""
        base = {"laziness": {"gates": {"complexity": {"max_complexity": 20}}}}
        curr = {"laziness": {"gates": {"complexity": {}}}}
        schema = self._make_schema(
            "laziness:complexity", "max_complexity", "lower_is_stricter"
        )
        changes = _detect_loosened_gates(base, curr, schema)
        assert len(changes) == 0

    def test_enabled_field_loosened_within_gate(self):
        """Gate-level 'enabled' changed from True to False is detected."""
        base = {"laziness": {"gates": {"complexity": {"enabled": True}}}}
        curr = {"laziness": {"gates": {"complexity": {"enabled": False}}}}
        schema = {
            "laziness:complexity": {
                "enabled": ConfigField(
                    name="enabled",
                    field_type="bool",
                    default=True,
                    permissiveness="true_is_stricter",
                )
            }
        }
        changes = _detect_loosened_gates(base, curr, schema)
        assert len(changes) == 1
        assert changes[0].field == "enabled"

    def test_category_only_in_current_config(self):
        """Category appearing only in current config — no crash."""
        base: dict[str, object] = {}
        curr = {"laziness": {"enabled": True, "gates": {}}}
        changes = _detect_loosened_gates(base, curr, {})
        assert len(changes) == 0

    def test_category_only_in_base_config(self):
        """Category only in base — disappearing doesn't crash."""
        base = {"laziness": {"enabled": True, "gates": {}}}
        curr: dict[str, object] = {}
        changes = _detect_loosened_gates(base, curr, {})
        assert len(changes) == 0


# ---------------------------------------------------------------------------
# _detect_pr_number
# ---------------------------------------------------------------------------


class TestDetectPrNumber:
    """Cover all PR number detection paths."""

    def test_github_pr_number_env(self, tmp_path):
        """GITHUB_PR_NUMBER env var is used first."""
        with patch.dict("os.environ", {"GITHUB_PR_NUMBER": "42"}, clear=True):
            assert _detect_pr_number(str(tmp_path)) == 42

    def test_pr_number_env(self, tmp_path):
        """PR_NUMBER env var works."""
        with patch.dict("os.environ", {"PR_NUMBER": "99"}, clear=True):
            assert _detect_pr_number(str(tmp_path)) == 99

    def test_pull_request_number_env(self, tmp_path):
        """PULL_REQUEST_NUMBER env var works."""
        with patch.dict("os.environ", {"PULL_REQUEST_NUMBER": "7"}, clear=True):
            assert _detect_pr_number(str(tmp_path)) == 7

    def test_invalid_env_var_skipped(self, tmp_path):
        """Non-integer env var is skipped."""
        with (
            patch.dict("os.environ", {"GITHUB_PR_NUMBER": "not-a-number"}, clear=True),
            patch(
                "slopmop.checks.quality.gate_dodging.subprocess.run",
                side_effect=FileNotFoundError,
            ),
        ):
            assert _detect_pr_number(str(tmp_path)) is None

    def test_github_ref_pulls(self, tmp_path):
        """GITHUB_REF=refs/pull/123/merge extracts PR number."""
        with patch.dict(
            "os.environ", {"GITHUB_REF": "refs/pull/123/merge"}, clear=True
        ):
            assert _detect_pr_number(str(tmp_path)) == 123

    def test_github_ref_non_pull(self, tmp_path):
        """GITHUB_REF not matching refs/pull/ falls through."""
        with (
            patch.dict("os.environ", {"GITHUB_REF": "refs/heads/main"}, clear=True),
            patch(
                "slopmop.checks.quality.gate_dodging.subprocess.run",
                side_effect=FileNotFoundError,
            ),
        ):
            assert _detect_pr_number(str(tmp_path)) is None

    def test_github_ref_invalid_number(self, tmp_path):
        """GITHUB_REF with non-int PR number falls through."""
        with (
            patch.dict("os.environ", {"GITHUB_REF": "refs/pull/abc/merge"}, clear=True),
            patch(
                "slopmop.checks.quality.gate_dodging.subprocess.run",
                side_effect=FileNotFoundError,
            ),
        ):
            assert _detect_pr_number(str(tmp_path)) is None

    def test_gh_cli_fallback_success(self, tmp_path):
        """Falls back to gh pr list when env vars missing."""
        branch_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="feat/my-branch\n", stderr=""
        )
        pr_list_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps([{"number": 55}]), stderr=""
        )
        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "slopmop.checks.quality.gate_dodging.subprocess.run",
                side_effect=[branch_result, pr_list_result],
            ),
        ):
            assert _detect_pr_number(str(tmp_path)) == 55

    def test_gh_cli_empty_pr_list(self, tmp_path):
        """gh pr list returns empty array → None."""
        branch_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="feat/my-branch\n", stderr=""
        )
        pr_list_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr=""
        )
        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "slopmop.checks.quality.gate_dodging.subprocess.run",
                side_effect=[branch_result, pr_list_result],
            ),
        ):
            assert _detect_pr_number(str(tmp_path)) is None

    def test_gh_cli_branch_fails(self, tmp_path):
        """git branch --show-current fails → None."""
        branch_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="not a repo"
        )
        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "slopmop.checks.quality.gate_dodging.subprocess.run",
                return_value=branch_result,
            ),
        ):
            assert _detect_pr_number(str(tmp_path)) is None

    def test_gh_cli_timeout(self, tmp_path):
        """Subprocess timeout during gh pr list → None."""
        branch_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="feat/my-branch\n", stderr=""
        )
        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "slopmop.checks.quality.gate_dodging.subprocess.run",
                side_effect=[branch_result, subprocess.TimeoutExpired("gh", 10)],
            ),
        ):
            assert _detect_pr_number(str(tmp_path)) is None

    def test_gh_cli_pr_list_nonzero(self, tmp_path):
        """gh pr list returns non-zero → None."""
        branch_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="feat/my-branch\n", stderr=""
        )
        pr_list_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error"
        )
        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "slopmop.checks.quality.gate_dodging.subprocess.run",
                side_effect=[branch_result, pr_list_result],
            ),
        ):
            assert _detect_pr_number(str(tmp_path)) is None


# ---------------------------------------------------------------------------
# _check_justification_comment
# ---------------------------------------------------------------------------


class TestCheckJustificationComment:
    """Test justification comment detection via mocked gh CLI."""

    def test_justification_in_regular_comment(self, tmp_path):
        """Found in regular PR comments → True."""
        comments_result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "comments": [
                        {"body": f"{JUSTIFICATION_PREFIX} increased complexity limit"}
                    ]
                }
            ),
            stderr="",
        )
        with patch(
            "slopmop.checks.quality.gate_dodging.subprocess.run",
            return_value=comments_result,
        ):
            assert _check_justification_comment(str(tmp_path), 42) is True

    def test_justification_in_review_body(self, tmp_path):
        """Found in review body → True."""
        # Regular comments — no match
        comments_result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"comments": [{"body": "looks good"}]}),
            stderr="",
        )
        # Reviews — match
        reviews_result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {"reviews": [{"body": f"{JUSTIFICATION_PREFIX} threshold change"}]}
            ),
            stderr="",
        )
        with patch(
            "slopmop.checks.quality.gate_dodging.subprocess.run",
            side_effect=[comments_result, reviews_result],
        ):
            assert _check_justification_comment(str(tmp_path), 42) is True

    def test_no_justification_found(self, tmp_path):
        """No matching comments → False."""
        comments_result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"comments": [{"body": "plain comment"}]}),
            stderr="",
        )
        reviews_result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"reviews": [{"body": "approved"}]}),
            stderr="",
        )
        with patch(
            "slopmop.checks.quality.gate_dodging.subprocess.run",
            side_effect=[comments_result, reviews_result],
        ):
            assert _check_justification_comment(str(tmp_path), 42) is False

    def test_gh_cli_failure(self, tmp_path):
        """gh CLI returns non-zero → False."""
        fail_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error"
        )
        with patch(
            "slopmop.checks.quality.gate_dodging.subprocess.run",
            return_value=fail_result,
        ):
            assert _check_justification_comment(str(tmp_path), 42) is False

    def test_timeout_returns_false(self, tmp_path):
        """Timeout during gh calls → False."""
        with patch(
            "slopmop.checks.quality.gate_dodging.subprocess.run",
            side_effect=subprocess.TimeoutExpired("gh", 15),
        ):
            assert _check_justification_comment(str(tmp_path), 42) is False

    def test_comments_returncode_0_reviews_nonzero(self, tmp_path):
        """Comments check passes (no match), reviews call fails → False."""
        comments_result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"comments": []}),
            stderr="",
        )
        reviews_fail = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error"
        )
        with patch(
            "slopmop.checks.quality.gate_dodging.subprocess.run",
            side_effect=[comments_result, reviews_fail],
        ):
            assert _check_justification_comment(str(tmp_path), 42) is False


# ---------------------------------------------------------------------------
# GateDodgingCheck.skip_reason — fallback branch
# ---------------------------------------------------------------------------


class TestSkipReasonFallback:
    """Cover the default fallback return in skip_reason."""

    def test_skip_reason_when_both_exist(self, tmp_path):
        """When .git AND config exist, skip_reason still returns something."""
        (tmp_path / ".git").mkdir()
        (tmp_path / ".sb_config.json").write_text("{}")
        check = GateDodgingCheck({})
        reason = check.skip_reason(str(tmp_path))
        assert "not applicable" in reason.lower()


# ---------------------------------------------------------------------------
# GateDodgingCheck.flaw property
# ---------------------------------------------------------------------------


class TestGateDodgingFlaw:
    """Test the flaw property returns deceptiveness."""

    def test_flaw_is_deceptiveness(self):
        """GateDodgingCheck.flaw should be Flaw.DECEPTIVENESS."""
        check = GateDodgingCheck({})
        assert check.flaw == Flaw.DECEPTIVENESS


# ---------------------------------------------------------------------------
# GateDodgingCheck.run() — additional integration paths
# ---------------------------------------------------------------------------


class TestRunAdditionalPaths:
    """Cover run() paths not yet exercised by TestRunIntegration."""

    def _write_config(self, tmp_path: Path, config: dict) -> None:
        (tmp_path / ".sb_config.json").write_text(json.dumps(config))

    def test_run_uses_auto_base_ref_when_empty(self, tmp_path):
        """Empty base_ref config triggers _get_base_ref() auto-detection."""
        config = {"laziness": {"gates": {}}}
        self._write_config(tmp_path, config)
        check = GateDodgingCheck({})  # no base_ref → empty string

        with (
            patch(
                "slopmop.checks.quality.gate_dodging._get_base_ref",
                return_value="origin/main",
            ) as mock_ref,
            patch(
                "slopmop.checks.quality.gate_dodging._load_base_config",
                return_value=config,
            ),
            patch(
                "slopmop.checks.quality.gate_dodging._build_schema_lookup",
                return_value={},
            ),
        ):
            result = check.run(str(tmp_path))

        mock_ref.assert_called_once()
        assert result.status == CheckStatus.PASSED

    def test_run_with_changes_and_no_pr(self, tmp_path):
        """Loosened gates + no PR context → WARNED with fix suggestion."""
        base_config = {"laziness": {"gates": {"complexity": {"max_complexity": 10}}}}
        curr_config = {"laziness": {"gates": {"complexity": {"max_complexity": 30}}}}
        self._write_config(tmp_path, curr_config)
        check = GateDodgingCheck({"base_ref": "origin/main"})

        schema_lookup = {
            "laziness:complexity": {
                "max_complexity": ConfigField(
                    name="max_complexity",
                    field_type="int",
                    default=10,
                    permissiveness="lower_is_stricter",
                )
            }
        }

        with (
            patch(
                "slopmop.checks.quality.gate_dodging._load_base_config",
                return_value=base_config,
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
        assert "max_complexity" in result.output
        assert result.fix_suggestion is not None
        assert JUSTIFICATION_PREFIX in result.fix_suggestion
