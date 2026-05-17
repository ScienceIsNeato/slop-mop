"""Shared helpers for buff subcommands."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from slopmop.checks.pr.comments import PRCommentsCheck
from slopmop.core.result import CheckResult


def project_root_from_cwd() -> str:
    """Resolve the git project root for the current working directory."""

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return os.getcwd()

    root = (result.stdout or "").strip()
    if result.returncode != 0 or not root:
        return os.getcwd()
    return str(Path(root))


def get_repo_owner_name(project_root: str) -> tuple[str, str]:
    """Return owner/name for the current repository."""

    check = PRCommentsCheck({})
    return check._get_repo_info(project_root)


def get_repo_slug(project_root: str) -> str:
    """Return owner/repo slug for the current repository."""

    from slopmop.cli.scan_triage import TriageError

    owner, repo = get_repo_owner_name(project_root)
    if not owner or not repo:
        raise TriageError("Could not determine repository owner/name")
    return f"{owner}/{repo}"


def get_current_branch(project_root: Path) -> str | None:
    """Return the current git branch name, if it can be resolved."""

    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
            stdin=subprocess.DEVNULL,
            cwd=project_root,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None


def get_branch_pr_number(repo: str) -> int | None:
    """Return the open PR number for the current branch, or None."""

    try:
        from slopmop.cli.scan_triage import current_pr_number

        return current_pr_number(repo)
    except Exception:
        return None


def run_pr_feedback_gate(pr_number: int | None, project_root: str) -> CheckResult:
    """Run ignored-feedback gate in blocking mode for buff semantics."""

    check = PRCommentsCheck({"fail_on_unresolved": True})
    original_pr_env = os.environ.get("GITHUB_PR_NUMBER")

    try:
        if pr_number is not None:
            os.environ["GITHUB_PR_NUMBER"] = str(pr_number)
        return check.run(project_root)
    finally:
        if pr_number is not None:
            if original_pr_env is None:
                os.environ.pop("GITHUB_PR_NUMBER", None)
            else:
                os.environ["GITHUB_PR_NUMBER"] = original_pr_env


def fire_buff_hook(has_issues: bool) -> None:
    """Notify workflow hooks that buff completed."""

    try:
        from slopmop.workflow.hooks import on_buff_complete

        on_buff_complete(project_root_from_cwd(), has_issues=has_issues)
    except Exception:
        pass
