"""Tests for the walk-forward terminal scour check."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slopmop.checks.workflow.walk_forward import WalkForwardCheck


@pytest.fixture
def check() -> WalkForwardCheck:
    return WalkForwardCheck(config={})


@pytest.fixture
def git_root(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    return tmp_path


class TestIsApplicable:
    def test_applicable_when_git_dir_exists(self, check, git_root):
        assert check.is_applicable(str(git_root)) is True

    def test_not_applicable_without_git_dir(self, check, tmp_path):
        assert check.is_applicable(str(tmp_path)) is False


class TestProperties:
    def test_name(self, check):
        assert check.name == "walk-forward"

    def test_display_name(self, check):
        assert "Walk-Forward" in check.display_name

    def test_gate_description(self, check):
        assert "Terminal" in check.gate_description

    def test_category(self, check):
        from slopmop.checks.base import GateCategory

        assert check.category == GateCategory.MYOPIA

    def test_flaw(self, check):
        from slopmop.checks.base import Flaw

        assert check.flaw == Flaw.MYOPIA

    def test_skip_reason(self, check, tmp_path):
        from slopmop.constants import NOT_A_GIT_REPO

        assert check.skip_reason(str(tmp_path)) == NOT_A_GIT_REPO


class TestGitHelper:
    def test_git_returns_stdout(self, check, git_root):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
            rc, out = check._git(["rev-parse", "--abbrev-ref", "HEAD"], git_root)
        assert rc == 0
        assert out == "main"

    def test_git_returns_error_on_exception(self, check, git_root):
        with patch("subprocess.run", side_effect=OSError("no git")):
            rc, out = check._git(["status"], git_root)
        assert rc == 1
        assert out == ""


class TestCheckWorkingTree:
    def test_clean_tree_returns_none(self, check, git_root):
        with patch.object(check, "_git", return_value=(0, "")):
            assert check._check_working_tree(git_root) is None

    def test_git_failure_returns_none(self, check, git_root):
        with patch.object(check, "_git", return_value=(1, "")):
            assert check._check_working_tree(git_root) is None

    def test_staged_files(self, check, git_root):
        with patch.object(check, "_git", return_value=(0, "M  foo.py")):
            result = check._check_working_tree(git_root)
        assert "staged" in result
        assert "foo.py" in result
        assert "git commit" in result

    def test_unstaged_files(self, check, git_root):
        with patch.object(check, "_git", return_value=(0, " M bar.py")):
            result = check._check_working_tree(git_root)
        assert "modified tracked" in result
        assert "bar.py" in result

    def test_untracked_files(self, check, git_root):
        with patch.object(check, "_git", return_value=(0, "?? new.py")):
            result = check._check_working_tree(git_root)
        assert "untracked" in result
        assert "new.py" in result

    def test_conflicted_files(self, check, git_root):
        with patch.object(check, "_git", return_value=(0, "UU conflict.py")):
            result = check._check_working_tree(git_root)
        assert "Merge conflicts" in result

    def test_short_line_skipped(self, check, git_root):
        with patch.object(check, "_git", return_value=(0, "??")):
            assert check._check_working_tree(git_root) is None

    def test_multiple_categories(self, check, git_root):
        porcelain = "M  staged.py\n M unstaged.py\n?? new.py"
        with patch.object(check, "_git", return_value=(0, porcelain)):
            result = check._check_working_tree(git_root)
        assert "staged" in result
        assert "modified tracked" in result
        assert "untracked" in result

    def test_truncation_for_many_files(self, check, git_root):
        lines = "\n".join(f" M file{i}.py" for i in range(10))
        with patch.object(check, "_git", return_value=(0, lines)):
            result = check._check_working_tree(git_root)
        assert "..." in result


class TestCheckPushStatus:
    def test_no_upstream_suggests_push(self, check, git_root):
        def fake_git(args, cwd):
            if "@{u}" in args:
                return 1, ""
            if "--abbrev-ref" in args:
                return 0, "feature-branch"
            return 0, ""

        with patch.object(check, "_git", side_effect=fake_git):
            result = check._check_push_status(git_root)
        assert "no upstream" in result
        assert "feature-branch" in result

    def test_detached_head_returns_none(self, check, git_root):
        def fake_git(args, cwd):
            if "@{u}" in args:
                return 1, ""
            if "--abbrev-ref" in args:
                return 0, "HEAD"
            return 0, ""

        with patch.object(check, "_git", side_effect=fake_git):
            assert check._check_push_status(git_root) is None

    def test_ahead_of_upstream(self, check, git_root):
        def fake_git(args, cwd):
            if "@{u}" in args:
                return 0, "origin/main"
            if "--count" in args:
                return 0, "3"
            return 0, ""

        with patch.object(check, "_git", side_effect=fake_git):
            result = check._check_push_status(git_root)
        assert "3 unpushed" in result

    def test_up_to_date(self, check, git_root):
        def fake_git(args, cwd):
            if "@{u}" in args:
                return 0, "origin/main"
            if "--count" in args:
                return 0, "0"
            return 0, ""

        with patch.object(check, "_git", side_effect=fake_git):
            assert check._check_push_status(git_root) is None


class TestCheckPrAlignment:
    def test_no_pr_anywhere(self, check, git_root):
        with (
            patch.object(check, "_git", return_value=(0, "feature")),
            patch(
                "slopmop.checks.workflow.walk_forward.subprocess.run",
                return_value=MagicMock(returncode=1, stdout=""),
            ),
            patch(
                "slopmop.core.config.get_current_pr_number",
                side_effect=Exception("no config"),
            ),
        ):
            warning, cfg, branch = check._check_pr_alignment(git_root)
        assert warning is None
        assert cfg is None
        assert branch is None

    def test_branch_has_pr_but_no_config(self, check, git_root):
        with (
            patch.object(check, "_git", return_value=(0, "feature")),
            patch(
                "slopmop.checks.workflow.walk_forward.subprocess.run",
                return_value=MagicMock(returncode=0, stdout="42\n"),
            ),
            patch(
                "slopmop.core.config.get_current_pr_number",
                side_effect=Exception("no config"),
            ),
        ):
            warning, cfg, branch = check._check_pr_alignment(git_root)
        assert "PR #42" in warning
        assert "not configured" in warning.lower() or "no working PR" in warning
        assert branch == 42

    def test_pr_mismatch(self, check, git_root):
        with (
            patch.object(check, "_git", return_value=(0, "feature")),
            patch(
                "slopmop.checks.workflow.walk_forward.subprocess.run",
                return_value=MagicMock(returncode=0, stdout="42\n"),
            ),
            patch(
                "slopmop.core.config.get_current_pr_number",
                return_value=99,
            ),
        ):
            warning, cfg, branch = check._check_pr_alignment(git_root)
        assert "does not match" in warning
        assert cfg == 99
        assert branch == 42

    def test_pr_aligned(self, check, git_root):
        with (
            patch.object(check, "_git", return_value=(0, "feature")),
            patch(
                "slopmop.checks.workflow.walk_forward.subprocess.run",
                return_value=MagicMock(returncode=0, stdout="92\n"),
            ),
            patch(
                "slopmop.core.config.get_current_pr_number",
                return_value=92,
            ),
        ):
            warning, cfg, branch = check._check_pr_alignment(git_root)
        assert warning is None
        assert cfg == 92
        assert branch == 92

    def test_detached_head_skips(self, check, git_root):
        with (
            patch.object(check, "_git", return_value=(0, "HEAD")),
            patch(
                "slopmop.core.config.get_current_pr_number",
                return_value=None,
            ),
        ):
            warning, _, _ = check._check_pr_alignment(git_root)
        assert warning is None

    def test_gh_exception_handled(self, check, git_root):
        with (
            patch.object(check, "_git", return_value=(0, "feature")),
            patch(
                "slopmop.checks.workflow.walk_forward.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=15),
            ),
            patch(
                "slopmop.core.config.get_current_pr_number",
                return_value=None,
            ),
        ):
            warning, cfg, branch = check._check_pr_alignment(git_root)
        assert warning is None


class TestNextAction:
    def test_returns_machine_action(self, check, git_root):
        with (
            patch("slopmop.workflow.state_store.read_state", return_value=None),
            patch(
                "slopmop.workflow.state_machine.MACHINE.advance",
                return_value=("PR_OPEN", "push and open PR"),
            ),
        ):
            result = check._next_action(git_root, 92)
        assert "push and open PR" in result

    def test_fallback_with_pr_number(self, check, git_root):
        with patch(
            "slopmop.workflow.state_store.read_state",
            side_effect=Exception("boom"),
        ):
            result = check._next_action(git_root, 42)
        assert "42" in result

    def test_fallback_without_pr_number(self, check, git_root):
        with patch(
            "slopmop.workflow.state_store.read_state",
            side_effect=Exception("boom"),
        ):
            result = check._next_action(git_root, None)
        assert "push" in result.lower() or "PR" in result


class TestRun:
    def test_clean_run_passes(self, check, git_root):
        with (
            patch.object(check, "_check_working_tree", return_value=None),
            patch.object(check, "_check_push_status", return_value=None),
            patch.object(check, "_check_pr_alignment", return_value=(None, 92, 92)),
            patch.object(check, "_next_action", return_value="run sm buff inspect 92"),
        ):
            result = check.run(str(git_root))
        assert result.status.value == "passed"
        assert "clean" in result.output.lower()

    def test_warnings_produce_warned_status(self, check, git_root):
        with (
            patch.object(
                check, "_check_working_tree", return_value="3 uncommitted files"
            ),
            patch.object(check, "_check_push_status", return_value=None),
            patch.object(check, "_check_pr_alignment", return_value=(None, 92, 92)),
            patch.object(check, "_next_action", return_value="git commit"),
        ):
            result = check.run(str(git_root))
        assert result.status.value == "warned"
        assert "3 uncommitted files" in result.output
        assert len(result.findings) >= 1

    def test_multiple_warnings_combined(self, check, git_root):
        with (
            patch.object(check, "_check_working_tree", return_value="dirty tree"),
            patch.object(
                check, "_check_push_status", return_value="2 unpushed commits"
            ),
            patch.object(
                check, "_check_pr_alignment", return_value=("PR mismatch", 99, 42)
            ),
            patch.object(check, "_next_action", return_value="fix alignment"),
        ):
            result = check.run(str(git_root))
        assert result.status.value == "warned"
        assert "dirty tree" in result.output
        assert "2 unpushed commits" in result.output
        assert "PR mismatch" in result.output
        assert len(result.findings) == 3
