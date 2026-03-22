"""CI status checking for slop-mop CLI."""

import json
import subprocess
import time as _time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _format_elapsed(seconds: float) -> str:
    """Format seconds into human-readable elapsed time."""
    if seconds < 0:
        return ""
    minutes, secs = divmod(int(seconds), 60)
    if minutes > 0:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _parse_check_timing(check: Dict[str, Any]) -> str:
    """Extract a human-readable timing string from a check dict.

    For completed checks, returns the total duration.
    For in-progress checks, returns the elapsed time since start.
    Returns empty string if no timing data is available.
    """
    started = check.get("startedAt")
    if not started:
        return ""
    try:
        start_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return ""

    completed_at = check.get("completedAt")
    if completed_at:
        try:
            end_dt = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
            return _format_elapsed((end_dt - start_dt).total_seconds())
        except (ValueError, AttributeError):
            pass

    # In-progress: elapsed since start
    elapsed = _time.time() - start_dt.timestamp()
    return _format_elapsed(elapsed)


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
                "--state",
                "open",
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
            [
                "gh",
                "pr",
                "checks",
                str(pr_number),
                "--json",
                "name,state,bucket,link,startedAt,completedAt",
            ],
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
    """Categorize checks into completed, in_progress, and failed.

    Each list contains tuples:
    - completed: ``(name, emoji, state, timing_str)``
    - in_progress: ``(name, emoji, state, timing_str)``
    - failed: ``(name, emoji, state, url, timing_str)``
    """
    completed: List[Tuple[str, str, str, str]] = []
    in_progress: List[Tuple[str, str, str, str]] = []
    failed: List[Tuple[str, str, str, str, str]] = []

    for check in checks:
        bucket = check.get("bucket", "").lower()
        name = check.get("name", "Unknown")
        url = check.get("link", "")
        state = check.get("state", "")
        timing = _parse_check_timing(check)

        if bucket == "pass":
            completed.append((name, "✅", "passed", timing))
        elif bucket == "fail":
            failed.append((name, "❌", "failed", url, timing))
        elif bucket == "cancel":
            failed.append((name, "🚫", "cancelled", url, timing))
        elif bucket in ("neutral", "skipping") and state.upper() in (
            "NEUTRAL",
            "SKIPPED",
            "STALE",
        ):
            completed.append((name, "⬜", state or bucket, timing))
        elif bucket == "pending":
            in_progress.append((name, "🔄", state or bucket, timing))
        else:
            in_progress.append((name, "❓", state or bucket, timing))

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
    for name, _, conclusion, url, timing in failed:
        suffix = f"  ({timing})" if timing else ""
        print(f"   • {name}: {conclusion}{suffix}")
        if url:
            print(f"     └─ {url}")
    print()

    if in_progress:
        print("🔄 IN PROGRESS:")
        for name, _, state, timing in in_progress:
            suffix = f"  ({timing} elapsed)" if timing else ""
            print(f"   • {name}: {state}{suffix}")
        print()


def _print_in_progress_status(completed: List[Any], in_progress: List[Any]) -> None:
    """Print status when checks are in progress."""
    print("🔄 CI IN PROGRESS")
    print()
    print(f"   ✅ {len(completed)} passed · 🔄 {len(in_progress)} pending")
    print()
    print("🔄 IN PROGRESS:")
    for name, _, state, timing in in_progress:
        suffix = f"  ({timing} elapsed)" if timing else ""
        print(f"   • {name}: {state}{suffix}")
    print()


def _print_success_status(completed: List[Any], total: int) -> None:
    """Print status when all checks pass."""
    print(f"✨ CI CLEAN · {len(completed)}/{total} checks passed")
    print()
    for name, emoji, _conclusion, timing in completed:
        suffix = f"  ({timing})" if timing else ""
        print(f"   {emoji} {name}{suffix}")
    print()
