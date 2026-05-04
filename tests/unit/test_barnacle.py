"""Tests for the barnacle GitHub issue intake CLI."""

import argparse
import subprocess
from unittest.mock import patch

from slopmop.cli.barnacle import (
    AUTO_FILE_DISABLED_ENVAR,
    DEFAULT_LABELS,
    DEFAULT_REPO,
    SCHEMA_VERSION,
    BarnacleIssue,
    _collect_metadata,
    _redact_url,
    auto_file_barnacle,
    build_barnacle_issue,
    cmd_barnacle,
    cmd_barnacle_file,
    create_barnacle_issue,
    render_issue_body,
    write_issue_body_file,
)


def _metadata() -> dict[str, object]:
    return {
        "schema": SCHEMA_VERSION,
        "repo": {
            "root": "/repo",
            "branch": "main",
            "dirty": False,
        },
        "agent": {"name": "test-agent", "source": "unit-test"},
    }


def _issue(**kwargs) -> BarnacleIssue:
    defaults = dict(
        title="[barnacle] swab output was misleading",
        command="sm swab",
        expected="clear guidance",
        actual="confusing guidance",
        output_excerpt="bad output",
        blocker_type="blocking",
        workflow="swab",
        project_root="/repo",
        gate="myopia:test.py",
        agent="test-agent",
        repo=DEFAULT_REPO,
        labels=DEFAULT_LABELS,
        reproduction_steps=["sm swab"],
        things_tried=["sm swab --no-cache"],
        metadata=_metadata(),
        include_sensitive_metadata=False,
    )
    defaults.update(kwargs)
    return BarnacleIssue(**defaults)


def _args(**kwargs) -> argparse.Namespace:
    defaults = dict(
        barnacle_action="file",
        title="swab output was misleading",
        command="sm swab",
        gate="myopia:test.py",
        expected="clear guidance",
        actual="confusing guidance",
        output_excerpt="bad output",
        blocker_type="blocking",
        project_root=".",
        reproduction_steps=["sm swab"],
        things_tried=["sm swab --no-cache"],
        workflow="swab",
        agent="test-agent",
        repo=DEFAULT_REPO,
        labels=list(DEFAULT_LABELS),
        dry_run=False,
        body_file=None,
        json_output=False,
        include_sensitive_metadata=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestRedactUrl:
    def test_strips_user_and_password_from_https(self):
        url = "https://oauth2:TOKEN@github.com/owner/repo.git"
        assert _redact_url(url) == "https://github.com/owner/repo.git"

    def test_strips_token_only_from_https(self):
        url = "https://TOKEN@github.com/owner/repo.git"
        assert _redact_url(url) == "https://github.com/owner/repo.git"

    def test_preserves_https_without_credentials(self):
        url = "https://github.com/owner/repo.git"
        assert _redact_url(url) == url

    def test_preserves_ssh_url_unchanged(self):
        url = "git@github.com:owner/repo.git"
        assert _redact_url(url) == url

    def test_preserves_unknown_on_error(self):
        assert _redact_url("unknown") == "unknown"

    def test_preserves_port_when_present(self):
        url = "https://user:pass@github.example.com:8443/owner/repo.git"
        assert _redact_url(url) == "https://github.example.com:8443/owner/repo.git"


class TestCollectMetadata:
    def test_default_omits_sensitive_fields(self, tmp_path):
        with (
            patch("slopmop.cli.barnacle._run_git", return_value="unknown"),
            patch("slopmop.cli.barnacle._git_dirty", return_value=False),
            patch("slopmop.cli.barnacle.git_current_branch", return_value="main"),
        ):
            meta = _collect_metadata(str(tmp_path), "agent")

        repo = meta["repo"]
        assert repo["root"].startswith("(redacted")
        assert repo["remote"].startswith("(redacted")
        assert repo["branch"].startswith("(redacted")
        assert repo["commit"].startswith("(redacted")
        assert meta["cwd"].startswith("(redacted")

    def test_include_sensitive_adds_remote_commit_cwd(self, tmp_path):
        with (
            patch(
                "slopmop.cli.barnacle._run_git",
                side_effect=[
                    "https://github.com/owner/repo.git",  # remote.origin.url
                    "abc123",  # rev-parse HEAD
                ],
            ),
            patch("slopmop.cli.barnacle._git_dirty", return_value=False),
            patch("slopmop.cli.barnacle.git_current_branch", return_value="main"),
        ):
            meta = _collect_metadata(str(tmp_path), "agent", include_sensitive=True)

        assert "remote" in meta["repo"]
        assert "commit" in meta["repo"]
        assert "cwd" in meta

    def test_include_sensitive_redacts_remote_credentials(self, tmp_path):
        with (
            patch(
                "slopmop.cli.barnacle._run_git",
                return_value="https://user:TOKEN@github.com/owner/repo.git",
            ),
            patch("slopmop.cli.barnacle._git_dirty", return_value=False),
            patch("slopmop.cli.barnacle.git_current_branch", return_value="main"),
        ):
            meta = _collect_metadata(str(tmp_path), "agent", include_sensitive=True)

        assert "TOKEN" not in meta["repo"]["remote"]
        assert "user" not in meta["repo"]["remote"]
        assert meta["repo"]["remote"] == "https://github.com/owner/repo.git"


class TestBuildBarnacleIssue:
    def test_prefixes_title_and_collects_metadata(self):
        with patch(
            "slopmop.cli.barnacle._collect_metadata", return_value=_metadata()
        ) as collect:
            issue = build_barnacle_issue(_args(project_root="/repo"))

        assert issue.title == "[barnacle] swab output was misleading"
        assert issue.repo == DEFAULT_REPO
        assert issue.labels == DEFAULT_LABELS
        assert issue.reproduction_steps == ["sm swab"]
        collect.assert_called_once_with("/repo", "test-agent", False)

    def test_keeps_existing_barnacle_prefix_case_insensitively(self):
        with patch("slopmop.cli.barnacle._collect_metadata", return_value=_metadata()):
            issue = build_barnacle_issue(_args(title="[BARNACLE] already tagged"))

        assert issue.title == "[BARNACLE] already tagged"

    def test_sensitive_metadata_requires_explicit_opt_in(self):
        with patch(
            "slopmop.cli.barnacle._collect_metadata", return_value=_metadata()
        ) as collect:
            issue = build_barnacle_issue(
                _args(project_root="/repo", include_sensitive_metadata=True)
            )

        assert issue.include_sensitive_metadata is True
        collect.assert_called_once_with("/repo", "test-agent", True)


class TestRenderIssueBody:
    def test_renders_structured_markdown(self):
        body = render_issue_body(_issue())

        assert "### Barnacle Summary" in body
        assert "### Current Behavior" in body
        assert "### Expected Behavior" in body
        assert "### Reproduction Steps" in body
        assert "### Environment Metadata" in body
        assert "- Barnacle: true" in body
        assert "myopia:test.py" in body
        assert SCHEMA_VERSION in body
        assert "Source Repository: (redacted" in body

    def test_strips_barnacle_summary_case_insensitively(self):
        body = render_issue_body(_issue(title="[BARNACLE] noisy prefix"))

        assert "### Barnacle Summary\nnoisy prefix" in body
        assert "[BARNACLE] noisy prefix" not in body

    def test_defaults_empty_lists_to_placeholders(self):
        body = render_issue_body(_issue(reproduction_steps=[], things_tried=[]))

        assert "1. (none provided)" in body
        assert "- (none provided)" in body


class TestBodyFile:
    def test_writes_retryable_issue_body(self, tmp_path):
        body_path = write_issue_body_file(
            _issue(project_root=str(tmp_path)), str(tmp_path / "barnacle.md")
        )

        assert body_path == tmp_path / "barnacle.md"
        assert "### Barnacle Summary" in body_path.read_text()


class TestCreateBarnacleIssue:
    def test_invokes_gh_issue_create_with_body_file_and_labels(self, tmp_path):
        completed = subprocess.CompletedProcess(
            args=["gh"], returncode=0, stdout="https://example.test/1\n", stderr=""
        )
        with patch(
            "slopmop.cli.barnacle.subprocess.run", return_value=completed
        ) as run:
            result, body_path = create_barnacle_issue(
                _issue(project_root=str(tmp_path)), str(tmp_path / "issue.md")
            )

        assert result.returncode == 0
        assert body_path == tmp_path / "issue.md"
        assert body_path.exists()
        command = run.call_args.args[0]
        assert command[:3] == ["gh", "issue", "create"]
        assert "--repo" in command
        assert DEFAULT_REPO in command
        assert "--body-file" in command
        assert str(body_path) in command
        assert command.count("--label") == 2
        assert "barnacle" in command
        assert "bug" in command

    def test_retries_without_barnacle_label_when_missing(self, tmp_path):
        missing = subprocess.CompletedProcess(
            args=["gh"], returncode=1, stdout="", stderr="label barnacle not found"
        )
        success = subprocess.CompletedProcess(
            args=["gh"], returncode=0, stdout="https://example.test/1\n", stderr=""
        )
        with patch(
            "slopmop.cli.barnacle.subprocess.run", side_effect=[missing, success]
        ) as run:
            result, _body_path = create_barnacle_issue(
                _issue(project_root=str(tmp_path))
            )

        assert result.returncode == 0
        fallback_command = run.call_args_list[1].args[0]
        assert "barnacle" not in fallback_command
        assert "bug" in fallback_command

    def test_missing_gh_raises_runtime_error(self, tmp_path):
        with patch(
            "slopmop.cli.barnacle.subprocess.run", side_effect=FileNotFoundError
        ):
            try:
                create_barnacle_issue(_issue(project_root=str(tmp_path)))
            except RuntimeError as exc:
                assert "GitHub CLI" in str(exc)
            else:
                raise AssertionError("expected RuntimeError")


class TestCmdBarnacleFile:
    def test_dry_run_prints_body_without_creating_issue(self, capsys, tmp_path):
        with (
            patch("slopmop.cli.barnacle._collect_metadata", return_value=_metadata()),
            patch("slopmop.cli.barnacle.create_barnacle_issue") as create,
        ):
            rc = cmd_barnacle_file(
                _args(dry_run=True, project_root=str(tmp_path), body_file=None)
            )

        assert rc == 0
        out = capsys.readouterr().out
        assert "Title: [barnacle]" in out
        assert "Body file:" in out
        create.assert_not_called()

    def test_dry_run_json_prints_machine_readable_payload(self, capsys, tmp_path):
        with patch("slopmop.cli.barnacle._collect_metadata", return_value=_metadata()):
            rc = cmd_barnacle_file(
                _args(dry_run=True, json_output=True, project_root=str(tmp_path))
            )

        assert rc == 0
        assert '"body_file"' in capsys.readouterr().out

    def test_success_prints_issue_url(self, capsys, tmp_path):
        result = subprocess.CompletedProcess(
            args=["gh"], returncode=0, stdout="https://example.test/1\n", stderr=""
        )
        with (
            patch("slopmop.cli.barnacle._collect_metadata", return_value=_metadata()),
            patch(
                "slopmop.cli.barnacle.create_barnacle_issue",
                return_value=(result, tmp_path / "issue.md"),
            ),
        ):
            rc = cmd_barnacle_file(_args())

        assert rc == 0
        out = capsys.readouterr().out
        assert "Barnacle issue filed" in out
        assert "https://example.test/1" in out
        assert "Body file:" in out

    def test_success_json_prints_url_payload(self, capsys, tmp_path):
        result = subprocess.CompletedProcess(
            args=["gh"], returncode=0, stdout="https://example.test/1\n", stderr=""
        )
        with (
            patch("slopmop.cli.barnacle._collect_metadata", return_value=_metadata()),
            patch(
                "slopmop.cli.barnacle.create_barnacle_issue",
                return_value=(result, tmp_path / "issue.md"),
            ),
        ):
            rc = cmd_barnacle_file(_args(json_output=True))

        assert rc == 0
        out = capsys.readouterr().out
        assert '"url": "https://example.test/1"' in out

    def test_failure_reports_retryable_body_file(self, capsys, tmp_path):
        result = subprocess.CompletedProcess(
            args=["gh"], returncode=1, stdout="", stderr="auth failed"
        )
        with (
            patch("slopmop.cli.barnacle._collect_metadata", return_value=_metadata()),
            patch(
                "slopmop.cli.barnacle.create_barnacle_issue",
                return_value=(result, tmp_path / "issue.md"),
            ),
        ):
            rc = cmd_barnacle_file(_args())

        assert rc == 1
        err = capsys.readouterr().err
        assert "Failed to file" in err
        assert "Issue body preserved" in err


class TestAutoFileBarnacle:
    def test_best_effort_returns_issue_url(self, tmp_path, monkeypatch):
        monkeypatch.delenv(AUTO_FILE_DISABLED_ENVAR, raising=False)
        result = subprocess.CompletedProcess(
            args=["gh"], returncode=0, stdout="https://example.test/1\n", stderr=""
        )
        with (
            patch("slopmop.cli.barnacle._collect_metadata", return_value=_metadata()),
            patch(
                "slopmop.cli.barnacle.create_barnacle_issue",
                return_value=(result, tmp_path / "issue.md"),
            ),
        ):
            url = auto_file_barnacle(
                command="sm upgrade",
                expected="swab passes",
                actual="swab failed",
                output_excerpt="failure",
                workflow="upgrade",
            )

        assert url == "https://example.test/1"

    def test_returns_none_when_issue_create_prints_no_url(self, tmp_path, monkeypatch):
        monkeypatch.delenv(AUTO_FILE_DISABLED_ENVAR, raising=False)
        result = subprocess.CompletedProcess(
            args=["gh"], returncode=0, stdout="", stderr=""
        )
        with (
            patch("slopmop.cli.barnacle._collect_metadata", return_value=_metadata()),
            patch(
                "slopmop.cli.barnacle.create_barnacle_issue",
                return_value=(result, tmp_path / "issue.md"),
            ),
        ):
            url = auto_file_barnacle(
                command="sm upgrade",
                expected="swab passes",
                actual="swab failed",
                output_excerpt="failure",
                workflow="upgrade",
            )

        assert url is None

    def test_never_raises_on_failure(self, monkeypatch):
        monkeypatch.delenv(AUTO_FILE_DISABLED_ENVAR, raising=False)
        with patch(
            "slopmop.cli.barnacle.create_barnacle_issue", side_effect=OSError("boom")
        ):
            result = auto_file_barnacle(
                command="sm upgrade",
                expected="ok",
                actual="fail",
                output_excerpt="",
            )

        assert result is None

    def test_auto_file_disabled_by_env(self):
        result = auto_file_barnacle(
            command="sm upgrade",
            expected="ok",
            actual="fail",
            output_excerpt="",
        )

        assert result is None


class TestCmdBarnacleDispatcher:
    def test_no_action_returns_nonzero(self):
        rc = cmd_barnacle(_args(barnacle_action=None))
        assert rc == 2

    def test_file_action_dispatches(self):
        with patch(
            "slopmop.cli.barnacle.cmd_barnacle_file", return_value=0
        ) as file_cmd:
            rc = cmd_barnacle(_args(barnacle_action="file"))

        assert rc == 0
        file_cmd.assert_called_once()

    def test_describe_alias_dispatches_with_deprecation_notice(self, capsys):
        with patch("slopmop.cli.barnacle.cmd_barnacle_file", return_value=0):
            rc = cmd_barnacle(_args(barnacle_action="describe"))

        assert rc == 0
        captured = capsys.readouterr()
        assert "deprecated" in captured.err
        assert captured.out == ""
