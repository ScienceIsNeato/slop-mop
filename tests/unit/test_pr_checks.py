"""Tests for PR comments check."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from slopmop.checks.pr.comments import PRCommentsCheck
from slopmop.core.result import CheckStatus


class TestPRCommentsCheck:
    """Tests for PRCommentsCheck."""

    def test_name(self):
        """Test check name."""
        check = PRCommentsCheck({})
        assert check.name == "ignored-feedback"

    def test_display_name(self):
        """Test check display name."""
        check = PRCommentsCheck({})
        assert "PR" in check.display_name or "Comment" in check.display_name

    def test_category(self):
        """Test check category."""
        from slopmop.checks.base import GateCategory

        check = PRCommentsCheck({})
        assert check.category == GateCategory.MYOPIA

    def test_role_is_diagnostic(self):
        """PR comments check is diagnostic, not foundational."""
        from slopmop.checks.base import CheckRole

        check = PRCommentsCheck({})
        assert check.role == CheckRole.DIAGNOSTIC

    def test_is_applicable_no_git_dir(self, tmp_path):
        """Test is_applicable returns False without .git directory."""
        check = PRCommentsCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_is_applicable_no_gh_cli(self, tmp_path):
        """Test is_applicable returns False without gh CLI."""
        (tmp_path / ".git").mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            check = PRCommentsCheck({})
            assert check.is_applicable(str(tmp_path)) is False

    def test_is_applicable_no_pr_context(self, tmp_path):
        """Test is_applicable returns False without PR context."""
        (tmp_path / ".git").mkdir()

        # Clear all PR-related environment variables
        env_overrides = {
            "GITHUB_PR_NUMBER": "",
            "PR_NUMBER": "",
            "PULL_REQUEST_NUMBER": "",
            "GITHUB_REF": "",
            "GITHUB_EVENT_PATH": "",
        }

        with (
            patch("subprocess.run") as mock_run,
            patch.dict("os.environ", env_overrides, clear=False),
        ):
            # gh --version succeeds, then git branch + gh pr list return no PR
            mock_run.side_effect = [
                MagicMock(returncode=0),  # gh --version
                MagicMock(
                    returncode=0, stdout="feature/no-pr\n"
                ),  # git branch --show-current
                MagicMock(returncode=0, stdout="[]"),  # gh pr list --head (empty)
            ]
            check = PRCommentsCheck({})
            assert check.is_applicable(str(tmp_path)) is False

    def test_is_applicable_with_pr(self, tmp_path):
        """Test is_applicable returns True with valid PR context."""
        (tmp_path / ".git").mkdir()

        # Clear PR-related env vars so the test exercises the branch/gh path
        env_overrides = {
            "GITHUB_PR_NUMBER": "",
            "PR_NUMBER": "",
            "PULL_REQUEST_NUMBER": "",
            "GITHUB_REF": "",
            "GITHUB_EVENT_PATH": "",
        }

        with (
            patch.dict("os.environ", env_overrides, clear=False),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                MagicMock(returncode=0),  # gh --version
                MagicMock(
                    returncode=0, stdout="feature/my-branch\n"
                ),  # git branch --show-current
                MagicMock(
                    returncode=0, stdout='[{"number": 123}]'
                ),  # gh pr list --head
            ]
            check = PRCommentsCheck({})
            assert check.is_applicable(str(tmp_path)) is True

    def test_detect_pr_number_from_env(self, tmp_path):
        """Test PR number detection from environment variable."""
        check = PRCommentsCheck({})

        with patch.dict("os.environ", {"GITHUB_PR_NUMBER": "42"}, clear=False):
            pr_num = check._detect_pr_number(str(tmp_path))
            assert pr_num == 42

    def test_detect_pr_number_from_github_ref(self, tmp_path):
        """Test PR number detection from GITHUB_REF (refs/pull/N/merge format)."""
        check = PRCommentsCheck({})

        env_overrides = {
            "GITHUB_PR_NUMBER": "",
            "PR_NUMBER": "",
            "PULL_REQUEST_NUMBER": "",
            "GITHUB_REF": "refs/pull/123/merge",
            "GITHUB_EVENT_PATH": "",
        }

        with patch.dict("os.environ", env_overrides, clear=False):
            pr_num = check._detect_pr_number(str(tmp_path))
            assert pr_num == 123

    def test_detect_pr_number_from_branch(self, tmp_path):
        """Test PR number detection from current branch via gh pr list --head."""
        check = PRCommentsCheck({})

        # Clear all PR-related environment variables to ensure gh pr list is used
        env_overrides = {
            "GITHUB_PR_NUMBER": "",
            "PR_NUMBER": "",
            "PULL_REQUEST_NUMBER": "",
            "GITHUB_REF": "",
            "GITHUB_EVENT_PATH": "",
        }

        # Two subprocess calls: git branch --show-current, then gh pr list --head
        git_branch_result = MagicMock(returncode=0, stdout="feature/my-branch\n")
        gh_pr_list_result = MagicMock(returncode=0, stdout='[{"number": 99}]')

        with (
            patch("subprocess.run") as mock_run,
            patch.dict("os.environ", env_overrides, clear=False),
        ):
            mock_run.side_effect = [git_branch_result, gh_pr_list_result]
            pr_num = check._detect_pr_number(str(tmp_path))
            assert pr_num == 99

    def test_run_no_pr_context(self, tmp_path):
        """Test run returns SKIPPED when no PR context."""
        (tmp_path / ".git").mkdir()

        check = PRCommentsCheck({})
        with patch.object(check, "_detect_pr_number", return_value=None):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.SKIPPED
        assert "No PR context" in result.output

    def test_run_no_repo_info(self, tmp_path):
        """Test run returns ERROR when repo info unavailable."""
        (tmp_path / ".git").mkdir()

        check = PRCommentsCheck({})
        with (
            patch.object(check, "_detect_pr_number", return_value=123),
            patch.object(check, "_get_repo_info", return_value=("", "")),
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.ERROR
        assert "repository" in result.error.lower()

    def test_run_no_unresolved_comments(self, tmp_path):
        """Test run returns PASSED when no unresolved comments."""
        (tmp_path / ".git").mkdir()

        check = PRCommentsCheck({})
        with (
            patch.object(check, "_detect_pr_number", return_value=123),
            patch.object(check, "_get_repo_info", return_value=("owner", "repo")),
            patch.object(check, "_get_unresolved_threads", return_value=[]),
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert "no unresolved" in result.output.lower()

    def test_run_with_unresolved_comments(self, tmp_path):
        """Test run returns WARNED with unresolved comments (default behaviour)."""
        (tmp_path / ".git").mkdir()

        threads = [
            {
                "thread_id": "PRRT_123",
                "is_outdated": False,
                "body": "Please fix this issue",
                "author": "reviewer",
                "path": "src/file.py",
                "line": 42,
                "created_at": "2024-01-01T00:00:00Z",
            }
        ]

        check = PRCommentsCheck({})
        with (
            patch.object(check, "_detect_pr_number", return_value=123),
            patch.object(check, "_get_repo_info", return_value=("owner", "repo")),
            patch.object(check, "_get_unresolved_threads", return_value=threads),
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.WARNED
        assert "1 unresolved" in result.output
        assert result.status_detail == "1 unresolved"
        # Summary output should have category counts and file path
        assert "pr_123_comments_report.md" in result.output

    def test_run_with_fail_on_unresolved_enabled(self, tmp_path):
        """Test run returns FAILED when fail_on_unresolved is True."""
        (tmp_path / ".git").mkdir()

        threads = [
            {
                "thread_id": "PRRT_123",
                "is_outdated": False,
                "body": "Please fix this issue",
                "author": "reviewer",
                "path": "src/file.py",
                "line": 42,
                "created_at": "2024-01-01T00:00:00Z",
            }
        ]

        check = PRCommentsCheck({"fail_on_unresolved": True})
        with (
            patch.object(check, "_detect_pr_number", return_value=123),
            patch.object(check, "_get_repo_info", return_value=("owner", "repo")),
            patch.object(check, "_get_unresolved_threads", return_value=threads),
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "1 unresolved" in result.error
        assert result.status_detail == "1 unresolved"
        assert "pr_123_comments_report.md" in result.fix_suggestion

    def test_run_with_fail_on_unresolved_disabled(self, tmp_path):
        """Test run returns WARNED when fail_on_unresolved is False."""
        (tmp_path / ".git").mkdir()

        threads = [
            {
                "thread_id": "PRRT_123",
                "is_outdated": False,
                "body": "Comment",
                "author": "reviewer",
                "path": "file.py",
                "line": 1,
                "created_at": "2024-01-01T00:00:00Z",
            }
        ]

        check = PRCommentsCheck({"fail_on_unresolved": False})
        with (
            patch.object(check, "_detect_pr_number", return_value=123),
            patch.object(check, "_get_repo_info", return_value=("owner", "repo")),
            patch.object(check, "_get_unresolved_threads", return_value=threads),
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.WARNED
        assert "1 unresolved" in result.output
        assert result.status_detail == "1 unresolved"
        """Test format_guidance includes AI agent instructions."""
        threads = [
            {
                "thread_id": "PRRT_456",
                "is_outdated": True,
                "body": "This is a test comment that is outdated",
                "author": "testuser",
                "path": "src/main.py",
                "line": 100,
                "created_at": "2024-01-01T00:00:00Z",
            }
        ]

        check = PRCommentsCheck({})
        guidance = check._format_guidance(threads, 42, "owner", "repo")

        # Check key elements are present
        assert "PR COMMENT RESOLUTION PROTOCOL" in guidance
        assert "LOCKED RESOLUTION ORDER" in guidance
        assert "AI AGENT WORKFLOW" in guidance
        assert "PRRT_456" in guidance
        assert "no_longer_applicable" in guidance
        assert "SCENARIO COMMAND MAPPING" in guidance
        assert "fixed_in_code" in guidance

    def test_get_unresolved_threads_parses_response(self, tmp_path):
        """Test _get_unresolved_threads correctly parses GraphQL response."""
        check = PRCommentsCheck({})

        graphql_response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [
                                {
                                    "id": "PRRT_abc",
                                    "isResolved": False,
                                    "isOutdated": False,
                                    "comments": {
                                        "nodes": [
                                            {
                                                "body": "Fix this",
                                                "path": "file.py",
                                                "line": 10,
                                                "author": {"login": "user1"},
                                                "createdAt": "2024-01-01",
                                            }
                                        ]
                                    },
                                },
                                {
                                    "id": "PRRT_def",
                                    "isResolved": True,  # This one is resolved
                                    "isOutdated": False,
                                    "comments": {
                                        "nodes": [
                                            {
                                                "body": "Already done",
                                                "path": "other.py",
                                                "line": 20,
                                                "author": {"login": "user2"},
                                                "createdAt": "2024-01-02",
                                            }
                                        ]
                                    },
                                },
                            ]
                        }
                    }
                }
            }
        }

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=json.dumps(graphql_response)
            )

            threads = check._get_unresolved_threads(str(tmp_path), 1, "owner", "repo")

        # Should only return unresolved threads
        assert len(threads) == 1
        assert threads[0]["thread_id"] == "PRRT_abc"
        assert threads[0]["body"] == "Fix this"
        assert threads[0]["author"] == "user1"

    def test_get_repo_info_from_github_env(self, tmp_path):
        """Test _get_repo_info picks up GITHUB_REPOSITORY env var."""
        check = PRCommentsCheck({})
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "ScienceIsNeato/slop-mop"}):
            owner, repo = check._get_repo_info(str(tmp_path))
        assert owner == "ScienceIsNeato"
        assert repo == "slop-mop"

    def test_get_repo_info_falls_through_to_git_remote(self, tmp_path):
        """Test _get_repo_info falls back to git remote URL parsing."""
        check = PRCommentsCheck({})

        with (
            patch.dict("os.environ", {"GITHUB_REPOSITORY": ""}, clear=False),
            patch("subprocess.run") as mock_run,
        ):
            # gh repo view fails (no auth)
            gh_fail = MagicMock(returncode=1, stdout="", stderr="auth required")
            # git remote get-url origin succeeds
            git_remote = MagicMock(
                returncode=0,
                stdout="https://github.com/ScienceIsNeato/slop-mop.git\n",
            )
            mock_run.side_effect = [gh_fail, git_remote]

            owner, repo = check._get_repo_info(str(tmp_path))

        assert owner == "ScienceIsNeato"
        assert repo == "slop-mop"

    def test_parse_repo_from_git_remote_https(self, tmp_path):
        """Test parsing HTTPS remote URL."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://github.com/owner/repo-name.git\n",
            )
            owner, repo = PRCommentsCheck._parse_repo_from_git_remote(str(tmp_path))
        assert owner == "owner"
        assert repo == "repo-name"

    def test_parse_repo_from_git_remote_https_no_suffix(self, tmp_path):
        """Test parsing HTTPS remote URL without .git suffix."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://github.com/owner/repo-name\n",
            )
            owner, repo = PRCommentsCheck._parse_repo_from_git_remote(str(tmp_path))
        assert owner == "owner"
        assert repo == "repo-name"

    def test_parse_repo_from_git_remote_ssh(self, tmp_path):
        """Test parsing SSH remote URL."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="git@github.com:ScienceIsNeato/slop-mop.git\n",
            )
            owner, repo = PRCommentsCheck._parse_repo_from_git_remote(str(tmp_path))
        assert owner == "ScienceIsNeato"
        assert repo == "slop-mop"

    def test_parse_repo_from_git_remote_non_github(self, tmp_path):
        """Test parsing non-GitHub remote returns empty."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://gitlab.com/owner/repo.git\n",
            )
            owner, repo = PRCommentsCheck._parse_repo_from_git_remote(str(tmp_path))
        assert owner == ""
        assert repo == ""

    def test_parse_repo_from_git_remote_command_fails(self, tmp_path):
        """Test git remote failure returns empty."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=128, stdout="", stderr="not a git repo"
            )
            owner, repo = PRCommentsCheck._parse_repo_from_git_remote(str(tmp_path))
        assert owner == ""
        assert repo == ""

    def test_full_comment_in_report(self, tmp_path):
        """Test that full comments are included in the report file."""
        long_comment = "x" * 300  # 300 character comment

        threads = [
            {
                "thread_id": "PRRT_long",
                "is_outdated": False,
                "body": long_comment,
                "author": "reviewer",
                "path": "file.py",
                "line": 1,
                "created_at": "2024-01-01T00:00:00Z",
            }
        ]

        check = PRCommentsCheck({})
        guidance = check._format_guidance(threads, 1, "owner", "repo")

        # The full report should contain the complete comment (normalized)
        # since it's written to a file, not shown in gate output
        normalized_comment = " ".join(long_comment.split())
        assert normalized_comment in guidance

    def test_run_writes_persistent_protocol_artifacts(self, tmp_path):
        """Run should emit protocol artifacts under .slopmop/buff-persistent-memory."""
        (tmp_path / ".git").mkdir()

        threads = [
            {
                "thread_id": "PRRT_abc",
                "is_outdated": False,
                "body": "Please fix this issue",
                "author": "reviewer",
                "path": "src/file.py",
                "line": 42,
                "created_at": "2024-01-01T00:00:00Z",
            }
        ]

        check = PRCommentsCheck({"fail_on_unresolved": True})
        with (
            patch.object(check, "_detect_pr_number", return_value=123),
            patch.object(check, "_get_repo_info", return_value=("owner", "repo")),
            patch.object(check, "_get_unresolved_threads", return_value=threads),
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED

        base = tmp_path / ".slopmop" / "buff-persistent-memory" / "pr-123"
        loop_dir = base / "loop-001"
        assert loop_dir.is_dir()
        assert (loop_dir / "protocol.json").exists()
        assert (loop_dir / "classified_threads.json").exists()
        assert (loop_dir / "threads_raw.json").exists()
        assert (loop_dir / "commands.sh").exists()
        assert (loop_dir / "execution_log.md").exists()
        assert (loop_dir / "outcomes.json").exists()
        assert (loop_dir / "pr_123_comments_report.md").exists()

    def test_commands_script_uses_expandable_fixed_in_code_comment(self):
        """Fixed-in-code rail should allow shell command substitution expansion."""
        check = PRCommentsCheck({})

        script = check._build_commands_script(
            [
                {
                    "thread_id": "PRRT_abc",
                    "resolution_scenario": "fixed_in_code",
                    "resolution_priority_rank": 1,
                    "resolution_priority_reason": "logic issue",
                }
            ],
            pr_number=85,
            owner="owner",
            repo="repo",
        )

        assert 'echo "Fixed in commit $(git rev-parse --short HEAD).' in script
        assert 'threadId: "PRRT_abc"' in script
        assert '\\"PRRT_abc\\"' not in script

    def test_group_threads_by_category_uses_preclassified_category(self):
        """Grouping should reuse the classifier output when category is preset."""
        check = PRCommentsCheck({})
        threads = [
            {
                "thread_id": "PRRT_abc",
                "body": "this text would normally look like a question?",
                "category": "🐛 Logic/Correctness",
            }
        ]

        grouped = check._group_threads_by_category(threads)

        assert list(grouped) == ["🐛 Logic/Correctness"]
        assert grouped["🐛 Logic/Correctness"][0]["thread_id"] == "PRRT_abc"

    def test_format_guidance_preserves_explicit_empty_ordered_threads(self):
        """Explicit empty ordered_threads should not trigger reclassification."""
        check = PRCommentsCheck({})
        threads = [
            {
                "thread_id": "PRRT_abc",
                "body": "Please fix this issue",
                "author": "reviewer",
                "path": "src/file.py",
                "line": 42,
                "created_at": "2024-01-01T00:00:00Z",
            }
        ]

        with patch.object(check, "_classify_and_order_threads") as classify:
            guidance = check._format_guidance(
                threads,
                85,
                "owner",
                "repo",
                ordered_threads=[],
            )

        classify.assert_not_called()
        assert "LOCKED RESOLUTION ORDER" in guidance

    def test_protocol_loop_directory_increments(self, tmp_path):
        """Protocol loop directory should increment per run for same PR."""
        check = PRCommentsCheck({})
        first = check._next_protocol_loop_dir(str(tmp_path), 85)
        second = check._next_protocol_loop_dir(str(tmp_path), 85)

        assert first.name == "loop-001"
        assert second.name == "loop-002"

    def test_protocol_loop_directory_retries_after_race(self, tmp_path, monkeypatch):
        """Loop directory allocation should retry if another process creates it first."""
        check = PRCommentsCheck({})
        original_mkdir = Path.mkdir
        collided = False

        def racing_mkdir(self, mode=0o777, parents=False, exist_ok=False):
            nonlocal collided
            original_mkdir(self, mode=mode, parents=parents, exist_ok=exist_ok)
            if self.name == "loop-001" and not collided:
                collided = True
                raise FileExistsError(str(self))

        monkeypatch.setattr(Path, "mkdir", racing_mkdir)

        loop_dir = check._next_protocol_loop_dir(str(tmp_path), 85)

        assert loop_dir.name == "loop-002"
