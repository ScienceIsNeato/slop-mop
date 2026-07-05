"""Tests for the GitHub Actions hygiene gate."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from slopmop.checks import ensure_checks_registered
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
        # Registry is a process-global other test files usually populate first;
        # register explicitly so this test passes in isolation too.
        ensure_checks_registered()
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
      - uses: actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd # v5
      - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405 # v6
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
      - uses: actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd # v5
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
      - uses: actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd # v5
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
      - uses: pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b # release/v1
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
        # A deprecated tag ref is also an unpinned ref — both findings fire.
        assert {f.rule_id for f in result.findings} == {
            "deprecated-action-version",
            "unpinned-action-ref",
        }

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
      - uses: actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd # v5
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
      - uses: actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd # v5
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
      - uses: codecov/codecov-action@0fb7178a7dbf82e28a83dcf4e123a4c26e0d4f9d # v5
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
      - uses: pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b # release/v1
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

        # Detection now happens once in run(); the resolved path is passed in.
        with patch.object(check._runner, "run", return_value=mock_result):
            findings = check._actionlint_findings(
                workflow, tmp_path, "/usr/bin/actionlint"
            )

        assert findings[0].rule_id == "actionlint:syntax-check"
        assert findings[0].file == ".github/workflows/ci.yml"
        assert findings[0].line == 2

    def test_actionlint_fallback_finding_for_unstructured_output(self, tmp_path):
        workflow = _write_workflow(tmp_path, "name: CI\non: push\n")
        check = GitHubActionsHygieneCheck({"run_actionlint": True})
        mock_result = MagicMock(returncode=1, output="plain failure")

        with patch.object(check._runner, "run", return_value=mock_result):
            findings = check._actionlint_findings(
                workflow, tmp_path, "/usr/bin/actionlint"
            )

        assert findings[0].rule_id == "actionlint"
        assert findings[0].message == "plain failure"

    def test_actionlint_success_and_disabled_return_no_findings(self, tmp_path):
        workflow = _write_workflow(tmp_path, "name: CI\non: push\n")
        check = GitHubActionsHygieneCheck({"run_actionlint": True})
        mock_result = MagicMock(returncode=0, output="")

        # Exit 0 → no findings even with actionlint resolved.
        with patch.object(check._runner, "run", return_value=mock_result):
            assert (
                check._actionlint_findings(workflow, tmp_path, "/usr/bin/actionlint")
                == []
            )

        # No resolved path (unfound/disabled) → no findings, no subprocess.
        assert check._actionlint_findings(workflow, tmp_path, None) == []
        # Config-disabled gates don't resolve actionlint at all.
        assert _check()._actionlint_path(str(tmp_path)) is None

    def test_passed_note_distinguishes_all_three_states(self, tmp_path):
        # The pass note must distinguish disabled / checked / not-installed —
        # all three states, not just one (#305 review).
        _write_workflow(tmp_path, "name: CI\non: push\n")
        # Resolution flows through the shared base helper now, not the gate.
        find_tool = "slopmop.checks.base.find_tool"

        # 1. Disabled by config → "disabled".
        disabled = GitHubActionsHygieneCheck({"run_actionlint": False}).run(
            str(tmp_path)
        )
        assert disabled.status == CheckStatus.PASSED
        assert "actionlint disabled" in disabled.output

        # 2. Enabled + resolvable + clean run → "checked".
        check = GitHubActionsHygieneCheck({"run_actionlint": True})
        clean = MagicMock(returncode=0, output="")
        with (
            patch(find_tool, return_value="/usr/bin/actionlint"),
            patch.object(check._runner, "run", return_value=clean),
        ):
            checked = check.run(str(tmp_path))
        assert "actionlint checked" in checked.output

        # 3. Enabled + not resolvable → "not installed".
        with patch(find_tool, return_value=None):
            missing = GitHubActionsHygieneCheck({"run_actionlint": True}).run(
                str(tmp_path)
            )
        assert "actionlint not installed" in missing.output

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


class TestUnpinnedActionRefs:
    """The unpinned-action-ref check: mutable tags/branches vs SHA pins."""

    def _run(self, tmp_path, body, config=None):
        _write_workflow(tmp_path, body)
        cfg = {"run_actionlint": False}
        cfg.update(config or {})
        return GitHubActionsHygieneCheck(cfg).run(str(tmp_path))

    def test_tag_ref_is_flagged(self, tmp_path):
        result = self._run(
            tmp_path,
            """
name: CI
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-node@v6
""",
        )
        assert result.status == CheckStatus.FAILED
        (finding,) = result.findings
        assert finding.rule_id == "unpinned-action-ref"
        assert "actions/setup-node@v6" in finding.message

    def test_branch_ref_is_flagged(self, tmp_path):
        result = self._run(
            tmp_path,
            """
name: CI
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: someorg/some-action@main
""",
        )
        assert result.status == CheckStatus.FAILED
        assert result.findings[0].rule_id == "unpinned-action-ref"

    def test_full_sha_pin_is_clean(self, tmp_path):
        result = self._run(
            tmp_path,
            """
name: CI
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-node@48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e # v6.4.0
""",
        )
        assert result.status == CheckStatus.PASSED

    def test_short_sha_is_not_a_pin(self, tmp_path):
        # Abbreviated SHAs are forgeable — only the full 40-hex counts.
        result = self._run(
            tmp_path,
            """
name: CI
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-node@48b55a0
""",
        )
        assert result.status == CheckStatus.FAILED
        assert result.findings[0].rule_id == "unpinned-action-ref"

    def test_allowlist_exempts_exact_and_subpath(self, tmp_path):
        result = self._run(
            tmp_path,
            """
name: CI
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: ScienceIsNeato/slop-mop-action@v2
      - uses: github/codeql-action/upload-sarif@v4
""",
            config={
                "allow_unpinned": [
                    "scienceisneato/slop-mop-action",
                    "github/codeql-action",
                ]
            },
        )
        assert result.status == CheckStatus.PASSED

    def test_local_and_docker_refs_are_exempt(self, tmp_path):
        result = self._run(
            tmp_path,
            """
name: CI
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: ./.github/actions/local-thing
      - uses: docker://alpine:latest
""",
        )
        assert result.status == CheckStatus.PASSED
