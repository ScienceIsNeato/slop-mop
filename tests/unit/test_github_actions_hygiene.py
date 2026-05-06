"""Tests for the GitHub Actions hygiene gate."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from slopmop.checks.workflow import GitHubActionsHygieneCheck
from slopmop.checks.workflow.github_actions import (
    _action_ref,
    _extract_python_heredocs,
    _major,
    _workflow_files,
)
from slopmop.core.registry import get_registry
from slopmop.core.result import CheckStatus, Finding


def _write_workflow(root: Path, body: str, name: str = "ci.yml") -> Path:
    workflow_dir = root / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
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

    def test_empty_and_non_mapping_workflows_are_safe_noops(self, tmp_path):
        _write_workflow(tmp_path, "", "empty.yml")
        _write_workflow(tmp_path, "- not\n- a\n- mapping\n", "list.yaml")

        result = _check().run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_ignores_workflows_without_job_and_step_mappings(self, tmp_path):
        _write_workflow(
            tmp_path,
            """
name: Odd but valid
on: push
jobs:
  123:
    runs-on: ubuntu-latest
  empty:
    steps: nope
  mixed:
    steps:
      - plain string
""",
        )

        result = _check().run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_write_all_and_read_all_permissions_allow_checkout(self, tmp_path):
        for permission_value in ("write-all", "read-all"):
            workflow_dir = tmp_path / permission_value
            _write_workflow(
                workflow_dir,
                f"""
name: CI
on: push
permissions: {permission_value}
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
""",
            )

            result = _check().run(str(workflow_dir))

            assert result.status == CheckStatus.PASSED

    def test_job_permissions_override_workflow_permissions(self, tmp_path):
        _write_workflow(
            tmp_path,
            """
name: CI
on: push
permissions: {}
jobs:
  test:
    permissions:
      contents: read
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
""",
        )

        result = _check().run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_code_publish_patterns_require_id_token_write(self, tmp_path):
        _write_workflow(
            tmp_path,
            """
name: Publish
on: push
permissions:
  contents: read
jobs:
  codecov:
    runs-on: ubuntu-latest
    steps:
      - uses: codecov/codecov-action@v5
        with:
          use_oidc: true
  npm:
    runs-on: ubuntu-latest
    steps:
      - run: npm publish --provenance
""",
        )

        result = _check().run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert [finding.rule_id for finding in result.findings] == [
            "oidc-publish-missing-id-token-write",
            "oidc-publish-missing-id-token-write",
        ]

    def test_oidc_publish_passes_with_job_level_id_token(self, tmp_path):
        _write_workflow(
            tmp_path,
            """
name: Release
on: workflow_dispatch
permissions: {}
jobs:
  publish:
    permissions:
      id-token: write
    runs-on: ubuntu-latest
    steps:
      - uses: pypa/gh-action-pypi-publish@release/v1
""",
        )

        result = _check().run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_action_references_without_version_are_not_deprecated(self, tmp_path):
        _write_workflow(
            tmp_path,
            """
name: CI
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout
      - uses: docker://alpine:latest
""",
        )

        result = _check().run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert _action_ref("actions/checkout") == ("actions/checkout", "")
        assert _major("release/v1") is None

    def test_python_heredoc_without_matching_workflow_line_has_no_location(self):
        check = _check()

        findings = check._python_heredoc_findings(
            "python <<'PY'\nif True:\nprint('x')\nPY",
            ".github/workflows/ci.yml",
            [],
        )

        assert findings[0].line is None

    def test_extracts_multiple_python_heredocs(self):
        heredocs = list(
            _extract_python_heredocs(
                "python <<'PY'\nprint('one')\nPY\npython3 <<EOF\nprint('two')\nEOF"
            )
        )

        assert [code for _offset, code in heredocs] == [
            "print('one')",
            "print('two')",
        ]

    def test_actionlint_findings_parse_structured_output(self, tmp_path):
        workflow = _write_workflow(tmp_path, "name: CI\non: push\n")
        check = GitHubActionsHygieneCheck({"run_actionlint": True})
        mock_result = MagicMock(
            returncode=1,
            output=f"{workflow}:2:5: bad event [syntax-check]\n",
        )

        with patch("shutil.which", return_value="/usr/bin/actionlint"):
            with patch.object(check._runner, "run", return_value=mock_result):
                findings = check._actionlint_findings(workflow, tmp_path)

        assert findings[0].rule_id == "actionlint:syntax-check"
        assert findings[0].file == ".github/workflows/ci.yml"
        assert findings[0].line == 2

    def test_actionlint_fallback_finding_for_unstructured_output(self, tmp_path):
        workflow = _write_workflow(tmp_path, "name: CI\non: push\n")
        check = GitHubActionsHygieneCheck({"run_actionlint": True})
        mock_result = MagicMock(returncode=1, output="plain failure")

        with patch("shutil.which", return_value="/usr/bin/actionlint"):
            with patch.object(check._runner, "run", return_value=mock_result):
                findings = check._actionlint_findings(workflow, tmp_path)

        assert findings[0].rule_id == "actionlint"
        assert findings[0].message == "plain failure"

    def test_actionlint_success_and_disabled_return_no_findings(self, tmp_path):
        workflow = _write_workflow(tmp_path, "name: CI\non: push\n")
        check = GitHubActionsHygieneCheck({"run_actionlint": True})
        mock_result = MagicMock(returncode=0, output="")

        with patch("shutil.which", return_value="/usr/bin/actionlint"):
            with patch.object(check._runner, "run", return_value=mock_result):
                assert check._actionlint_findings(workflow, tmp_path) == []

        assert _check()._actionlint_findings(workflow, tmp_path) == []

    def test_with_repo_relative_file_handles_no_file_and_outside_root(self, tmp_path):
        check = _check()
        no_file = check._with_repo_relative_file(Finding(message="x"), tmp_path)
        outside = check._with_repo_relative_file(
            Finding(message="x", file="/outside/workflow.yml"),
            tmp_path,
        )

        assert no_file.file is None
        assert outside.file == "/outside/workflow.yml"

    def test_workflow_files_only_scans_workflow_yaml_files(self, tmp_path):
        workflow_dir = tmp_path / ".github" / "workflows"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "ci.yml").write_text("name: CI\n", encoding="utf-8")
        (workflow_dir / "ci.yaml").write_text("name: CI\n", encoding="utf-8")
        (workflow_dir / "notes.txt").write_text("nope", encoding="utf-8")

        files = _workflow_files(tmp_path, [".github/workflows", "missing"])

        assert [path.name for path in files] == ["ci.yaml", "ci.yml"]
