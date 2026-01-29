"""Tests for PR comments check."""

import json
from unittest.mock import MagicMock, patch

from slopbucket.checks.pr.comments import PRCommentsCheck
from slopbucket.core.result import CheckStatus


class TestPRCommentsCheck:
    """Tests for PRCommentsCheck."""

    def test_name(self):
        """Test check name."""
        check = PRCommentsCheck({})
        assert check.name == "comments"

    def test_display_name(self):
        """Test check display name."""
        check = PRCommentsCheck({})
        assert "PR" in check.display_name or "Comment" in check.display_name

    def test_category(self):
        """Test check category."""
        from slopbucket.checks.base import GateCategory

        check = PRCommentsCheck({})
        assert check.category == GateCategory.PR

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

        with patch("subprocess.run") as mock_run:
            # gh --version succeeds
            mock_run.side_effect = [
                MagicMock(returncode=0),  # gh --version
                MagicMock(returncode=1),  # gh pr view fails
            ]
            check = PRCommentsCheck({})
            assert check.is_applicable(str(tmp_path)) is False

    def test_is_applicable_with_pr(self, tmp_path):
        """Test is_applicable returns True with valid PR context."""
        (tmp_path / ".git").mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0),  # gh --version
                MagicMock(returncode=0, stdout='{"number": 123}'),  # gh pr view
            ]
            check = PRCommentsCheck({})
            assert check.is_applicable(str(tmp_path)) is True

    def test_detect_pr_number_from_env(self, tmp_path):
        """Test PR number detection from environment variable."""
        check = PRCommentsCheck({})

        with patch.dict("os.environ", {"GITHUB_PR_NUMBER": "42"}):
            pr_num = check._detect_pr_number(str(tmp_path))
            assert pr_num == 42

    def test_detect_pr_number_from_branch(self, tmp_path):
        """Test PR number detection from current branch."""
        check = PRCommentsCheck({})

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='{"number": 99}')
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
        """Test run returns FAILED with unresolved comments."""
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

        assert result.status == CheckStatus.FAILED
        assert "1 unresolved" in result.error
        # Summary output should have category counts and file path
        assert "Logic/Correctness" in result.output
        assert "pr_123_comments_report.md" in result.output
        # Full report is in temp file, referenced in fix_suggestion
        assert "pr_123_comments_report.md" in result.fix_suggestion

    def test_run_with_fail_on_unresolved_disabled(self, tmp_path):
        """Test run returns PASSED when fail_on_unresolved is False."""
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

        assert result.status == CheckStatus.PASSED
        assert "1 unresolved" in result.output

    def test_format_guidance_includes_protocol(self, tmp_path):
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
        assert "COMMENTS BY CATEGORY" in guidance
        assert "AI AGENT WORKFLOW" in guidance
        assert "PRRT_456" in guidance
        assert "@testuser" in guidance
        assert "OUTDATED" in guidance
        assert "resolveReviewThread" in guidance

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
