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
from slopmop.constants import ACTION_BUFF_INSPECT
from slopmop.core.result import CheckResult, CheckStatus
from slopmop.reporting.envelope import NextStep, Status, build_envelope

_POLL_WAIT_MSG = "⏳ Waiting {interval}s before next check..."
_POST_CI_FEEDBACK_CHECK_NAMES = {"cursor bugbot"}


def _feedback_data(feedback_result: CheckResult) -> dict[str, Any]:
    """Summarize the PR feedback gate result for the envelope data slot."""

    detail = (feedback_result.output or feedback_result.error or "").strip()
    return {
        "status": feedback_result.status.value,
        "detail": detail or None,
    }


def _checks_summary(
    checks: list[dict[str, Any]],
    completed: list[Any],
    in_progress: list[Any],
    failed: list[Any],
) -> dict[str, Any]:
    """Build a machine-readable summary of the CI check set."""

    return {
        "total": len(checks),
        "passed": len(completed),
        "in_progress": len(in_progress),
        "failed": len(failed),
        "in_progress_names": [str(entry[0]) for entry in in_progress],
        "failed_names": [str(entry[0]) for entry in failed],
    }


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
    json_output: bool = False,
) -> int:
    """Check PR CI status through the buff rail.

    When ``json_output`` is set, ``status`` emits only the v3 envelope while
    ``watch`` keeps streaming human progress and prints the final envelope once
    polling settles.
    """
    import json

    from slopmop.cli.buff import _warn_if_pr_worktree_mismatch

    # Watch always streams human progress (the poll loop); a one-shot status
    # with --json stays silent until the terminal envelope.
    show_human = watch or not json_output

    def _finish(
        exit_code: int,
        status: Status,
        data: dict[str, Any],
        *,
        next_steps: tuple[NextStep, ...] = (),
    ) -> int:
        if json_output:
            envelope = build_envelope(
                command="buff",
                status=status,
                exit_code=exit_code,
                data=data,
                next_steps=next_steps,
            )
            print(json.dumps(envelope, indent=2))
        return exit_code

    project_root = Path(_project_root_from_cwd())
    repo: str | None = None
    try:
        repo = _get_repo_slug(str(project_root))
        resolved_pr, pr_resolution_source = resolve_pr_number_with_source(
            repo, pr_number
        )
    except (TriageError, json.JSONDecodeError) as exc:
        if show_human:
            print(f"ERROR: {exc}")
            if repo is not None and isinstance(exc, TriageError):
                _suggest_stale_pr_fix(repo, pr_number, watch)
        return _finish(
            1,
            Status.ERROR,
            {"overall_state": "error", "error": str(exc)},
        )

    if show_human:
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
        if show_human and watch and poll_count > 1:
            elapsed = time.monotonic() - watch_start
            ts = time.strftime("%H:%M:%S")
            print(
                f"[{ts}] Poll #{poll_count} (watching for "
                f"{_format_elapsed(elapsed)})"
            )
            print()

        checks, error = _fetch_checks(project_root, resolved_pr)

        if checks is None:
            if show_human:
                print(f"ERROR: {error}")
            exit_code = 2 if "not found" in error.lower() else 1
            return _finish(
                exit_code,
                Status.ERROR,
                {"overall_state": "error", "pr_number": resolved_pr, "error": error},
            )

        if not checks:
            if show_human:
                print("Overall PR state: waiting for CI - no checks registered yet")
                print()
            if watch and poll_count <= _MAX_EMPTY_POLLS:
                if show_human:
                    print(
                        "⏳ No CI checks registered yet — waiting for GitHub to pick up workflows..."
                    )
                    print(_POLL_WAIT_MSG.format(interval=interval))
                time.sleep(interval)
                if show_human:
                    print()
                continue

            feedback_result = _run_pr_feedback_gate(resolved_pr, str(project_root))
            if feedback_result.status != CheckStatus.PASSED:
                _fire_buff_hook(has_issues=True)
                if show_human:
                    _render_status_feedback_blocker(
                        feedback_result,
                        no_checks=True,
                    )
                return _finish(
                    1,
                    Status.FAIL,
                    {
                        "overall_state": "no_checks_feedback_blocked",
                        "pr_number": resolved_pr,
                        "checks": {"total": 0},
                        "feedback": _feedback_data(feedback_result),
                    },
                    next_steps=(
                        NextStep(
                            action="inspect",
                            command=ACTION_BUFF_INSPECT,
                            reason="Take the next review batch.",
                        ),
                    ),
                )

            if show_human:
                print(format_feedback_state(feedback_result))
                print(
                    "Final PR state: incomplete - no CI checks registered, "
                    "but PR feedback is resolved"
                )
                print()
                print("ℹ️  No CI checks found for this PR")
                print("   (CI workflow may not be set up yet)")
            _fire_buff_hook(has_issues=False)
            return _finish(
                0,
                Status.OK,
                {
                    "overall_state": "no_checks_feedback_resolved",
                    "pr_number": resolved_pr,
                    "checks": {"total": 0},
                    "feedback": _feedback_data(feedback_result),
                },
            )

        completed, in_progress, failed = _categorize_checks(checks)
        total = len(checks)
        if show_human:
            print_ci_state_summary(checks)
        checks_summary = _checks_summary(checks, completed, in_progress, failed)

        if failed:
            if show_human:
                _print_failed_status(completed, in_progress, failed)
            if watch and in_progress and not fail_fast:
                settled_post_ci_feedback = False
                if show_human:
                    print(_POLL_WAIT_MSG.format(interval=interval))
                time.sleep(interval)
                if show_human:
                    print()
                continue
            _fire_buff_hook(has_issues=True)
            return _finish(
                1,
                Status.FAIL,
                {
                    "overall_state": "ci_failed",
                    "pr_number": resolved_pr,
                    "checks": checks_summary,
                },
            )

        if in_progress:
            if show_human:
                _print_in_progress_status(completed, in_progress)
            if watch:
                settled_post_ci_feedback = False
                if show_human:
                    print(_POLL_WAIT_MSG.format(interval=interval))
                time.sleep(interval)
                if show_human:
                    print()
                continue
            if show_human:
                print("💡 Use 'sm buff watch' to poll until complete")
            # CI not finished is not a blocking failure: status stays INFO so
            # agents keying off the envelope status don't treat an in-flight
            # PR like a failed one. exit_code stays 1 ("not ready, don't
            # proceed") to keep one-shot scripts from advancing mid-run.
            return _finish(
                1,
                Status.INFO,
                {
                    "overall_state": "ci_in_progress",
                    "pr_number": resolved_pr,
                    "checks": checks_summary,
                },
                next_steps=(
                    NextStep(
                        action="wait",
                        command="sm buff watch",
                        reason="Poll until CI completes.",
                    ),
                ),
            )

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
            if show_human:
                print(
                    "⏳ CI checks are complete. Waiting one extra interval for review feedback to settle..."
                )
            time.sleep(interval)
            if show_human:
                print()
            continue

        # Final (authoritative) feedback gate check.
        feedback_result = _run_pr_feedback_gate(resolved_pr, str(project_root))
        if feedback_result.status != CheckStatus.PASSED:
            _fire_buff_hook(has_issues=True)
            if show_human:
                _render_status_feedback_blocker(
                    feedback_result,
                    no_checks=False,
                )
            return _finish(
                1,
                Status.FAIL,
                {
                    "overall_state": "feedback_blocked",
                    "pr_number": resolved_pr,
                    "checks": checks_summary,
                    "feedback": _feedback_data(feedback_result),
                },
                next_steps=(
                    NextStep(
                        action="inspect",
                        command=ACTION_BUFF_INSPECT,
                        reason="Take the next review batch.",
                    ),
                ),
            )

        if show_human:
            print(format_feedback_state(feedback_result))
            print(
                "Final PR state: clean - CI checks passed and PR feedback is resolved"
            )
            print()
            _print_success_status(completed, total)
        _fire_buff_hook(has_issues=False)
        if show_human and watch:
            elapsed = time.monotonic() - watch_start
            print(f"⏱️  Total watch time: {_format_elapsed(elapsed)}")
            print()
        return _finish(
            0,
            Status.OK,
            {
                "overall_state": "clean",
                "pr_number": resolved_pr,
                "checks": checks_summary,
                "feedback": _feedback_data(feedback_result),
            },
        )
