"""CI status checking for slop-mop CLI."""

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _detect_pr_number(project_root: Path) -> Optional[int]:
    """Auto-detect PR number from current branch.

    Uses ``gh pr list --head <branch>`` instead of ``gh pr view``
    because the latter can return a PR from a *different* branch.
    """
    try:
        # Get current branch name
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if branch_result.returncode != 0 or not branch_result.stdout.strip():
            return None

        current_branch = branch_result.stdout.strip()

        # Find PR for THIS branch specifically
        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--head",
                current_branch,
                "--json",
                "number",
                "--limit",
                "1",
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data:
                return data[0].get("number")
    except (subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError):
        pass
    return None


def _fetch_checks(
    project_root: Path, pr_number: int
) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """Fetch check status from GitHub.

    Returns (checks_list, error_message).
    checks_list is None on error, empty list if no checks.
    """
    try:
        result = subprocess.run(
            ["gh", "pr", "checks", str(pr_number), "--json", "name,state,bucket,link"],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None, "GitHub CLI (gh) not found. Install: https://cli.github.com/"

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "no checks" in stderr.lower():
            return [], ""
        return None, f"Failed to get check status: {stderr}"

    try:
        checks = json.loads(result.stdout)
        return checks if checks else [], ""
    except json.JSONDecodeError:
        if not result.stdout.strip():
            return [], ""
        return None, f"Failed to parse check data: {result.stdout}"


def _categorize_checks(
    checks: List[Dict[str, Any]],
) -> Tuple[List[Any], List[Any], List[Any]]:
    """Categorize checks into completed, in_progress, and failed."""
    completed: List[Tuple[str, str, str]] = []
    in_progress: List[Tuple[str, str, str]] = []
    failed: List[Tuple[str, str, str, str]] = []

    for check in checks:
        bucket = check.get("bucket", "").lower()
        name = check.get("name", "Unknown")
        url = check.get("link", "")
        state = check.get("state", "")

        if bucket == "pass":
            completed.append((name, "✅", "passed"))
        elif bucket == "fail":
            failed.append((name, "❌", "failed", url))
        elif bucket == "cancel":
            failed.append((name, "🚫", "cancelled", url))
        elif bucket in ("pending", "skipping"):
            in_progress.append((name, "🔄", state or bucket))
        else:
            in_progress.append((name, "❓", state or bucket))

    return completed, in_progress, failed


def _print_failed_status(
    completed: List[Any], in_progress: List[Any], failed: List[Any]
) -> None:
    """Print status when there are failures."""
    print("🪣 SLOP IN CI")
    print()
    print(
        f"   ✅ {len(completed)} passed · ❌ {len(failed)} failed · 🔄 {len(in_progress)} pending"
    )
    print()
    print("❌ FAILED:")
    for name, _, conclusion, url in failed:
        print(f"   • {name}: {conclusion}")
        if url:
            print(f"     └─ {url}")
    print()

    if in_progress:
        print("🔄 IN PROGRESS:")
        for name, _, state in in_progress:
            print(f"   • {name}: {state}")
        print()


def _print_in_progress_status(completed: List[Any], in_progress: List[Any]) -> None:
    """Print status when checks are in progress."""
    print("🔄 CI IN PROGRESS")
    print()
    print(f"   ✅ {len(completed)} passed · 🔄 {len(in_progress)} pending")
    print()
    print("🔄 IN PROGRESS:")
    for name, _, state in in_progress:
        print(f"   • {name}: {state}")
    print()


def _print_success_status(completed: List[Any], total: int) -> None:
    """Print status when all checks pass."""
    print(f"✨ CI CLEAN · {len(completed)}/{total} checks passed")
    print()
    for name, emoji, _conclusion in completed:
        print(f"   {emoji} {name}")
    print()
