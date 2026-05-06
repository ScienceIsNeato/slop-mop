"""Tests for the GitHub Actions hygiene gate."""

from __future__ import annotations

from pathlib import Path

from slopmop.checks.workflow import GitHubActionsHygieneCheck
from slopmop.core.registry import get_registry
from slopmop.core.result import CheckStatus


def _write_workflow(root: Path, body: str, name: str = "ci.yml") -> Path:
    workflow_dir = root / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    path = workflow_dir / name
    path.write_text(body, encoding="utf-8")
    return path


def _check() -> GitHubActionsHygieneCheck:
    return GitHubActionsHygieneCheck({"run_actionlint": False})


class TestGitHubActionsHygieneCheck:
    def test_name_and_registration(self):
        check = _check()

        assert check.full_name == "myopia:github-actions-hygiene"
        assert check.full_name in get_registry().list_checks()

    def test_not_applicable_without_workflows(self, tmp_path):
        assert _check().is_applicable(str(tmp_path)) is False

    def test_valid_modern_workflow_passes(self, tmp_path):
        _write_workflow(
            tmp_path,
            """
name: CI
on: push
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
      - run: python --version
""",
        )

        result = _check().run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_broken_workflow_yaml_fails_before_runtime(self, tmp_path):
        _write_workflow(tmp_path, "name: [\njobs:\n  test: {}\n")

        result = _check().run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert result.findings[0].rule_id == "workflow-yaml-parse"

    def test_embedded_python_heredoc_syntax_error_fails(self, tmp_path):
        _write_workflow(
            tmp_path,
            """
name: Release
on: workflow_dispatch
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - run: |
          python <<'PY'
          if True:
          print('not indented')
          PY
""",
        )

        result = _check().run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert {finding.rule_id for finding in result.findings} == {
            "embedded-python-parse"
        }

    def test_restrictive_permissions_require_contents_for_checkout(self, tmp_path):
        _write_workflow(
            tmp_path,
            """
name: CI
on: push
permissions: {}
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
""",
        )

        result = _check().run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert result.findings[0].rule_id == "checkout-missing-contents-read"

    def test_checkout_without_explicit_permissions_does_not_guess(self, tmp_path):
        _write_workflow(
            tmp_path,
            """
name: CI
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
""",
        )

        result = _check().run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_oidc_publish_pattern_requires_id_token_write(self, tmp_path):
        _write_workflow(
            tmp_path,
            """
name: Release
on: workflow_dispatch
permissions:
  contents: read
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: pypa/gh-action-pypi-publish@release/v1
""",
        )

        result = _check().run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert result.findings[0].rule_id == "oidc-publish-missing-id-token-write"

    def test_deprecated_github_action_major_fails(self, tmp_path):
        _write_workflow(
            tmp_path,
            """
name: CI
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
""",
        )

        result = _check().run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert result.findings[0].rule_id == "deprecated-action-version"
        assert "actions/checkout@v5" in result.findings[0].fix_strategy
