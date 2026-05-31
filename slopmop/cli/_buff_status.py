"""PR CI status handler for ``sm buff status``."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from slopmop.cli.buff_common import fire_buff_hook as _fire_buff_hook
from slopmop.cli.buff_common import get_current_branch as _get_current_branch
from slopmop.cli.buff_common import get_repo_slug as _get_repo_slug
from slopmop.cli.buff_common import project_root_from_cwd as _project_root_from_cwd
from slopmop.cli.buff_common import run_pr_feedback_gate as _run_pr_feedback_gate
from slopmop.cli.buff_common import suggest_stale_pr_fix as _suggest_stale_pr_fix
from slopmop.cli.buff_narration import (
    format_feedback_state,
    print_ci_state_summary,
    print_pr_selection_trace,
)
from slopmop.cli.ci import (
    _categorize_checks,
    _fetch_checks,
    _format_elapsed,
    _print_failed_status,
    _print_in_progress_status,
    _print_success_status,
)
from slopmop.cli.scan_triage import TriageError, resolve_pr_number_with_source
from slopmop.core.result import CheckResult, CheckStatus

_POLL_WAIT_MSG = "⏳ Waiting {interval}s before next check..."
_POST_CI_FEEDBACK_CHECK_NAMES = {"cursor bugbot"}


def _has_post_ci_feedback_check(checks: list[dict[str, Any]]) -> bool:
    """Return whether a late-comment review bot is present in the check set."""

    return any(
        str(check.get("name", "")).strip().lower() in _POST_CI_FEEDBACK_CHECK_NAMES
        for check in checks
    )


def _render_status_feedback_blocker(
    feedback_result: CheckResult, *, no_checks: bool
) -> int:
    """Render unresolved or unverifiable feedback for buff status/watch."""

    if feedback_result.status == CheckStatus.FAILED:
        if no_checks:
            print(
                "Buff status blocked: no CI checks found, but unresolved PR review threads remain."
            )
        else:
            print(
                "Buff status blocked: CI checks are clean, but unresolved PR review threads remain."
            )
        if feedback_result.output:
            print(feedback_result.output)
        print("Next step: run 'sm buff inspect' to take the next review batch.")
        return 1

    print("Buff status error: could not verify unresolved PR feedback.")
    if feedback_result.error:
        print(f"ERROR: {feedback_result.error}")
    return 1


def cmd_buff_status(
    pr_number: int | None,
    watch: bool,
    interval: int,
    *,
    fail_fast: bool = False,
) -> int:
    """Check PR CI status through the buff rail."""
    import json

    from slopmop.cli.buff import _warn_if_pr_worktree_mismatch

    project_root = Path(_project_root_from_cwd())
    repo: str | None = None
    try:
        repo = _get_repo_slug(str(project_root))
        resolved_pr, pr_resolution_source = resolve_pr_number_with_source(
            repo, pr_number
        )
    except (TriageError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        if repo is not None and isinstance(exc, TriageError):
            _suggest_stale_pr_fix(repo, pr_number, watch)
        return 1

    print()
    print("🪣 sm buff status - CI Status Check")
    print("=" * 60)
    from slopmop.reporting import print_project_header

    print_project_header(str(project_root))
    print(f"🔀 PR: #{resolved_pr}")
    _warn_if_pr_worktree_mismatch(project_root, resolved_pr, repo)
    if watch:
        flags = f"polling every {interval}s"
        if fail_fast:
            flags += ", fail-fast"
        print(f"👀 Watch mode: {flags}")
    print("=" * 60)
    print()
    print_pr_selection_trace(
        repo=repo,
        current_branch=_get_current_branch(project_root),
        json_output=False,
        requested_pr_number=pr_number,
        resolved_pr_number=resolved_pr,
        source=pr_resolution_source,
        assume_latest=False,
    )

    settled_post_ci_feedback = False
    poll_count = 0
    watch_start = time.monotonic()
    _MAX_EMPTY_POLLS = 6

    while True:
        poll_count += 1

        # Show poll header with timestamp in watch mode (skip first poll)
        if watch and poll_count > 1:
            elapsed = time.monotonic() - watch_start
            ts = time.strftime("%H:%M:%S")
            print(
                f"[{ts}] Poll #{poll_count} (watching for "
                f"{_format_elapsed(elapsed)})"
            )
            print()

        checks, error = _fetch_checks(project_root, resolved_pr)

        if checks is None:
            print(f"ERROR: {error}")
            return 2 if "not found" in error.lower() else 1

        if not checks:
            print("Overall PR state: waiting for CI - no checks registered yet")
            print()
            if watch and poll_count <= _MAX_EMPTY_POLLS:
                print(
                    "⏳ No CI checks registered yet — waiting for GitHub to pick up workflows..."
                )
                print(_POLL_WAIT_MSG.format(interval=interval))
                time.sleep(interval)
                print()
                continue

            feedback_result = _run_pr_feedback_gate(resolved_pr, str(project_root))
            if feedback_result.status != CheckStatus.PASSED:
                _fire_buff_hook(has_issues=True)
                return _render_status_feedback_blocker(
                    feedback_result,
                    no_checks=True,
                )

            print(format_feedback_state(feedback_result))
            print(
                "Final PR state: incomplete - no CI checks registered, "
                "but PR feedback is resolved"
            )
            print()
            print("ℹ️  No CI checks found for this PR")
            print("   (CI workflow may not be set up yet)")
            _fire_buff_hook(has_issues=False)
            return 0

        completed, in_progress, failed = _categorize_checks(checks)
        total = len(checks)
        print_ci_state_summary(checks)

        if failed:
            _print_failed_status(completed, in_progress, failed)
            if watch and in_progress and not fail_fast:
                settled_post_ci_feedback = False
                print(_POLL_WAIT_MSG.format(interval=interval))
                time.sleep(interval)
                print()
                continue
            _fire_buff_hook(has_issues=True)
            return 1

        if in_progress:
            _print_in_progress_status(completed, in_progress)
            if watch:
                settled_post_ci_feedback = False
                print(_POLL_WAIT_MSG.format(interval=interval))
                time.sleep(interval)
                print()
                continue
            print("💡 Use 'sm buff watch' to poll until complete")
            return 1

        # Extra settle wait when a post-CI review bot (e.g. Cursor Bugbot)
        # is present.  completedAt being set means the bot has truly
        # finished, but it may still be syncing its final comments.
        # One extra interval is a reasonable buffer.
        if (
            watch
            and not settled_post_ci_feedback
            and _has_post_ci_feedback_check(checks)
        ):
            settled_post_ci_feedback = True
            print(
                "⏳ CI checks are complete. Waiting one extra interval for review feedback to settle..."
            )
            time.sleep(interval)
            print()
            continue

        # Final (authoritative) feedback gate check.
        feedback_result = _run_pr_feedback_gate(resolved_pr, str(project_root))
        if feedback_result.status != CheckStatus.PASSED:
            _fire_buff_hook(has_issues=True)
            return _render_status_feedback_blocker(
                feedback_result,
                no_checks=False,
            )

        print(format_feedback_state(feedback_result))
        print("Final PR state: clean - CI checks passed and PR feedback is resolved")
        print()
        _print_success_status(completed, total)
        _fire_buff_hook(has_issues=False)
        if watch:
            elapsed = time.monotonic() - watch_start
            print(f"⏱️  Total watch time: {_format_elapsed(elapsed)}")
            print()
        return 0
