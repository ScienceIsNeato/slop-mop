"""Post-PR buffing command.

`sm buff` is CI-first post-submit orchestration:
- read latest CI code-scan results
- summarize actionable status
- direct the next local fix/recheck loop
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional, cast

from slopmop.checks.pr.comments import PRCommentsCheck
from slopmop.cli.ci import (
    _categorize_checks,
    _fetch_checks,
    _print_failed_status,
    _print_in_progress_status,
    _print_success_status,
)
from slopmop.cli.scan_triage import (
    TriageError,
    print_triage,
    resolve_pr_number,
    run_triage,
    write_json_out,
)
from slopmop.core.result import CheckResult, CheckStatus

_RESOLUTION_SCENARIOS = {
    "fixed_in_code",
    "invalid_with_explanation",
    "no_longer_applicable",
    "out_of_scope_ticketed",
    "needs_human_feedback",
}


def _parse_optional_int(value: str | None, label: str) -> int | None:
    """Parse an optional integer CLI token."""

    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an integer, got: {value}") from exc


def _normalize_single_pr_action(
    raw_mode: str,
    raw_rest: list[str],
) -> argparse.Namespace:
    """Normalize actions that take at most one PR number."""

    if len(raw_rest) > 1:
        raise ValueError(f"buff {raw_mode} accepts at most one PR number")
    return argparse.Namespace(
        action=raw_mode,
        pr_number=_parse_optional_int(
            raw_rest[0] if raw_rest else None,
            "PR number",
        ),
    )


def _normalize_status_action(
    mode: str,
    raw_rest: list[str],
    interval: int,
) -> argparse.Namespace:
    """Normalize buff CI status/watch actions."""

    if len(raw_rest) > 1:
        raise ValueError(f"buff {mode} accepts at most one PR number")
    return argparse.Namespace(
        action="status",
        pr_number=_parse_optional_int(
            raw_rest[0] if raw_rest else None,
            "PR number",
        ),
        watch=mode == "watch",
        interval=interval,
    )


def _normalize_buff_args(args: argparse.Namespace) -> argparse.Namespace:
    """Normalize parser output into an action-oriented namespace."""

    raw_mode = getattr(args, "pr_or_action", None)
    raw_rest = list(getattr(args, "action_args", []) or [])

    if raw_mode in (None, ""):
        return argparse.Namespace(action="inspect", pr_number=None)

    if raw_mode == "inspect":
        return _normalize_single_pr_action("inspect", raw_rest)

    if raw_mode == "status":
        return _normalize_status_action(
            mode="status",
            raw_rest=raw_rest,
            interval=int(getattr(args, "interval", 30)),
        )

    if raw_mode == "watch":
        return _normalize_status_action(
            mode="watch",
            raw_rest=raw_rest,
            interval=int(getattr(args, "interval", 30)),
        )

    if raw_mode == "iterate":
        return _normalize_single_pr_action("iterate", raw_rest)

    if raw_mode == "finalize":
        normalized = _normalize_single_pr_action("finalize", raw_rest)
        return argparse.Namespace(
            action=normalized.action,
            pr_number=normalized.pr_number,
            push_changes=bool(getattr(args, "push", False)),
        )

    if raw_mode == "verify":
        return _normalize_single_pr_action("verify", raw_rest)

    if raw_mode == "resolve":
        if len(raw_rest) < 2:
            raise ValueError(
                "buff resolve requires PR number and thread id: "
                "sm buff resolve <pr_number> <thread_id>"
            )
        if len(raw_rest) > 2:
            raise ValueError(
                "buff resolve accepts only PR number and thread id positional arguments"
            )
        return argparse.Namespace(
            action="resolve",
            pr_number=_parse_optional_int(raw_rest[0], "PR number"),
            thread_id=raw_rest[1],
            scenario=getattr(args, "scenario", None),
            message=getattr(args, "message", None),
            resolve_thread=not bool(getattr(args, "no_resolve", False)),
        )

    return argparse.Namespace(
        action="inspect",
        pr_number=_parse_optional_int(raw_mode, "PR number"),
    )


def _load_json_file(path: Path) -> dict[str, Any]:
    """Load a JSON file and enforce object shape."""

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return cast(dict[str, Any], data)


def _latest_protocol_dir(project_root: str, pr_number: int) -> Path | None:
    """Return the newest persistent protocol loop directory for a PR."""

    root = (
        Path(project_root) / ".slopmop" / "buff-persistent-memory" / f"pr-{pr_number}"
    )
    if not root.is_dir():
        return None

    loops = sorted(
        child
        for child in root.iterdir()
        if child.is_dir() and child.name.startswith("loop-")
    )
    return loops[-1] if loops else None


def _load_latest_protocol(project_root: str, pr_number: int) -> dict[str, Any] | None:
    """Load protocol metadata for the newest inspect loop."""

    loop_dir = _latest_protocol_dir(project_root, pr_number)
    if loop_dir is None:
        return None

    protocol_path = loop_dir / "protocol.json"
    if not protocol_path.exists():
        return None
    return _load_json_file(protocol_path)


def _select_iteration_batch(
    protocol: dict[str, Any],
) -> tuple[list[dict[str, Any]], int] | None:
    """Select the next deterministic batch for a buff iterate round."""

    ordered_threads_obj = protocol.get("ordered_threads")
    if not isinstance(ordered_threads_obj, list) or not ordered_threads_obj:
        return None
    ordered_threads: list[object] = cast(list[object], ordered_threads_obj)

    first_thread_obj = ordered_threads[0]
    if not isinstance(first_thread_obj, dict):
        return None
    first_thread = cast(dict[str, Any], first_thread_obj)

    first_rank = int(first_thread.get("resolution_priority_rank", 0))
    batch: list[dict[str, Any]] = []
    for thread_obj in ordered_threads:
        if not isinstance(thread_obj, dict):
            continue
        thread = cast(dict[str, Any], thread_obj)
        if int(thread.get("resolution_priority_rank", 0)) != first_rank:
            break
        batch.append(thread)

    if not batch:
        return None
    return batch, first_rank


def _write_iteration_artifact(
    protocol: dict[str, Any],
    batch: list[dict[str, Any]],
    rank: int,
) -> Path:
    """Persist the current iterate round so agents can consume a stable batch."""

    loop_dir = Path(str(protocol["loop_dir"]))
    target = loop_dir / "next_iteration.json"
    target.write_text(
        json.dumps(
            {
                "pr_number": protocol.get("pr_number"),
                "loop_dir": protocol.get("loop_dir"),
                "selected_rank": rank,
                "scenario": batch[0].get("resolution_scenario"),
                "thread_count": len(batch),
                "thread_ids": [thread.get("thread_id") for thread in batch],
                "threads": batch,
                "instructions": [
                    "Limit this round to the listed threads only.",
                    "Make code changes or reviewer replies only for this batch.",
                    "When the batch is addressed, re-run 'sm buff iterate'.",
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return target


def _build_draft_entries(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build draft local-response placeholders for an iterate round."""

    drafts: list[dict[str, Any]] = []
    for thread in batch:
        scenario = str(thread.get("resolution_scenario") or "")
        if scenario == "fixed_in_code":
            template = (
                "Fixed in the current branch. Replace with commit SHA after committing: "
                "[explain the code change]"
            )
        elif scenario == "invalid_with_explanation":
            template = "[state why this comment no longer applies with evidence]"
        elif scenario == "no_longer_applicable":
            template = "Code has changed and this thread is outdated; adding explicit note for reviewer."
        elif scenario == "out_of_scope_ticketed":
            template = (
                "Tracking in issue #[ISSUE_NUMBER]: [URL]. Not part of this PR scope."
            )
        else:
            template = "Please clarify expected behavior or acceptance criteria before implementation."

        drafts.append(
            {
                "thread_id": thread.get("thread_id"),
                "scenario": scenario,
                "category": thread.get("category"),
                "path": thread.get("path"),
                "line": thread.get("line"),
                "draft_status": "pending",
                "comment_template": template,
                "notes": "",
            }
        )
    return drafts


def _write_iteration_supporting_artifacts(
    protocol: dict[str, Any],
    batch: list[dict[str, Any]],
    rank: int,
) -> dict[str, Path]:
    """Write the local state bundle for the current iterate round."""

    loop_dir = Path(str(protocol["loop_dir"]))
    iteration_path = _write_iteration_artifact(protocol, batch, rank)
    drafts_path = loop_dir / "drafts.json"
    drafts_path.write_text(
        json.dumps(
            {
                "pr_number": protocol.get("pr_number"),
                "loop_dir": protocol.get("loop_dir"),
                "selected_rank": rank,
                "drafts": _build_draft_entries(batch),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    iteration_log = loop_dir / "iteration_log.md"
    iteration_log.write_text(
        "# Buff Iterate Round\n\n"
        f"- pr_number: {protocol.get('pr_number')}\n"
        f"- loop_dir: {protocol.get('loop_dir')}\n"
        f"- selected_rank: {rank}\n"
        f"- thread_count: {len(batch)}\n",
        encoding="utf-8",
    )
    return {
        "iteration": iteration_path,
        "drafts": drafts_path,
        "iteration_log": iteration_log,
    }


def _write_finalize_plan(
    project_root: str,
    pr_number: int,
    *,
    ready_to_push: bool,
    push_requested: bool,
    next_step: str,
) -> Path | None:
    """Write a local finalize plan artifact for the current PR loop."""

    loop_dir = _latest_protocol_dir(project_root, pr_number)
    base_dir = loop_dir or (
        Path(project_root) / ".slopmop" / "buff-persistent-memory" / f"pr-{pr_number}"
    )
    plan_path = base_dir / "finalize_plan.json"
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(
            json.dumps(
                {
                    "pr_number": pr_number,
                    "loop_dir": str(loop_dir) if loop_dir else None,
                    "ready_to_push": ready_to_push,
                    "push_requested": push_requested,
                    "next_step": next_step,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        return None
    return plan_path


def _format_finalize_plan_path(plan_path: Path | None) -> str:
    """Render finalize-plan status without crashing when persistence is unavailable."""

    if plan_path is None:
        return "unavailable (local state directory not writable)"
    return str(plan_path)


def _print_finalize_plan(plan_path: Path | None) -> None:
    """Print finalize plan status in one place to keep wording consistent."""

    print(f"Finalize plan: {_format_finalize_plan_path(plan_path)}")


def _run_scour_quietly(project_root: str) -> int:
    """Run scour through the slop-mop rail without dumping its raw payload."""

    output_path = Path(project_root) / ".slopmop" / "last_buff_iterate_scour.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "slopmop.sm",
            "scour",
            "--json",
            "--output-file",
            str(output_path),
            "--project-root",
            project_root,
        ],
        capture_output=True,
        text=True,
        cwd=project_root,
        check=False,
    )
    return result.returncode


def _push_current_branch(project_root: str) -> int:
    """Push the current branch to its configured upstream."""

    result = subprocess.run(
        ["git", "push"],
        capture_output=True,
        text=True,
        cwd=project_root,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        print(f"ERROR: git push failed: {detail or 'unknown git error'}")
    return result.returncode


def _get_repo_owner_name(project_root: str) -> tuple[str, str]:
    """Return owner/name for the current repository."""

    check = PRCommentsCheck({})
    return check._get_repo_info(project_root)


def _get_repo_slug(project_root: str) -> str:
    """Return owner/repo slug for the current repository."""

    owner, repo = _get_repo_owner_name(project_root)
    if not owner or not repo:
        raise TriageError("Could not determine repository owner/name")
    return f"{owner}/{repo}"


def _post_pr_comment(
    project_root: str, owner: str, repo: str, pr_number: int, message: str
) -> None:
    """Post a PR comment through gh CLI."""

    result = subprocess.run(
        [
            "gh",
            "pr",
            "comment",
            str(pr_number),
            "--repo",
            f"{owner}/{repo}",
            "--body",
            message,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=project_root,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"failed to post PR comment: {detail or 'unknown gh error'}")


def _resolve_review_thread(project_root: str, thread_id: str) -> None:
    """Resolve a PR review thread through the internal GitHub adapter."""

    mutation = (
        "mutation($threadId: ID!) { "
        "resolveReviewThread(input: {threadId: $threadId}) { "
        "thread { id isResolved } } }"
    )
    result = subprocess.run(
        [
            "gh",
            "api",
            "graphql",
            "-F",
            f"threadId={thread_id}",
            "-f",
            f"query={mutation}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=project_root,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            f"failed to resolve review thread {thread_id}: {detail or 'unknown gh error'}"
        )


def _cmd_buff_verify(pr_number: int | None) -> int:
    """Verify unresolved PR feedback using the buff rail."""

    project_root = _project_root_from_cwd()
    try:
        resolved_pr_number = resolve_pr_number(_get_repo_slug(project_root), pr_number)
    except TriageError as exc:
        print(f"ERROR: {exc}")
        return 1

    feedback_result = _run_pr_feedback_gate(resolved_pr_number, project_root)

    if feedback_result.status == CheckStatus.PASSED:
        target = f"PR #{resolved_pr_number}"
        print(f"Buff verify clean: {target} has no unresolved review threads.")
        return 0

    if feedback_result.status == CheckStatus.FAILED:
        print("Buff verify failed: unresolved PR review threads remain.")
        if feedback_result.output:
            print(feedback_result.output)
        return 1

    print("Buff verify error: could not verify unresolved PR feedback.")
    if feedback_result.error:
        print(f"ERROR: {feedback_result.error}")
    return 1


def _cmd_buff_status(pr_number: int | None, watch: bool, interval: int) -> int:
    """Check PR CI status through the buff rail."""

    project_root = Path(_project_root_from_cwd())
    try:
        resolved_pr = resolve_pr_number(_get_repo_slug(str(project_root)), pr_number)
    except TriageError as exc:
        print(f"ERROR: {exc}")
        return 1

    print()
    print("🪣 sm buff status - CI Status Check")
    print("=" * 60)
    from slopmop.reporting import print_project_header

    print_project_header(str(project_root))
    print(f"🔀 PR: #{resolved_pr}")
    if watch:
        print(f"👀 Watch mode: polling every {interval}s")
    print("=" * 60)
    print()

    while True:
        checks, error = _fetch_checks(project_root, resolved_pr)

        if checks is None:
            print(f"ERROR: {error}")
            return 2 if "not found" in error.lower() else 1

        if not checks:
            print("ℹ️  No CI checks found for this PR")
            print("   (CI workflow may not be set up yet)")
            return 0

        completed, in_progress, failed = _categorize_checks(checks)
        total = len(checks)

        if failed:
            _print_failed_status(completed, in_progress, failed)
            if watch and in_progress:
                print(f"⏳ Waiting {interval}s before next check...")
                time.sleep(interval)
                print()
                continue
            return 1

        if in_progress:
            _print_in_progress_status(completed, in_progress)
            if watch:
                print(f"⏳ Waiting {interval}s before next check...")
                time.sleep(interval)
                print()
                continue
            print("💡 Use 'sm buff watch' to poll until complete")
            return 1

        _print_success_status(completed, total)
        return 0


def _cmd_buff_resolve(
    pr_number: int | None,
    thread_id: str,
    scenario: Optional[str],
    message: Optional[str],
    resolve_thread: bool,
) -> int:
    """Post a scenario-tagged comment and optionally resolve the thread."""

    if not message:
        print("ERROR: buff resolve requires --message")
        return 2

    if scenario and scenario not in _RESOLUTION_SCENARIOS:
        print(
            "ERROR: invalid --scenario. Expected one of: "
            + ", ".join(sorted(_RESOLUTION_SCENARIOS))
        )
        return 2

    project_root = _project_root_from_cwd()
    owner, repo = _get_repo_owner_name(project_root)
    if not owner or not repo:
        print("ERROR: could not determine repository owner/name")
        return 1
    try:
        resolved_pr_number = resolve_pr_number(f"{owner}/{repo}", pr_number)
    except TriageError as exc:
        print(f"ERROR: {exc}")
        return 1

    if scenario and not message.startswith("["):
        rendered_message = f"[{scenario}] {message}"
    else:
        rendered_message = message

    try:
        _post_pr_comment(
            project_root,
            owner,
            repo,
            resolved_pr_number,
            rendered_message,
        )
        if resolve_thread:
            _resolve_review_thread(project_root, thread_id)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 1

    action = "commented and resolved" if resolve_thread else "commented"
    print(f"Buff resolve complete: {action} {thread_id} on PR #{resolved_pr_number}.")
    return 0


def _project_root_from_cwd() -> str:
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


def _run_pr_feedback_gate(pr_number: int | None, project_root: str) -> CheckResult:
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


def _cmd_buff_iterate(pr_number: int | None) -> int:
    """Advance the post-PR loop by one deterministic thread batch."""

    project_root = _project_root_from_cwd()
    try:
        resolved_pr_number = resolve_pr_number(_get_repo_slug(project_root), pr_number)
    except TriageError as exc:
        print(f"ERROR: {exc}")
        return 1

    feedback_result = _run_pr_feedback_gate(resolved_pr_number, project_root)

    if feedback_result.status == CheckStatus.ERROR:
        print("Buff iterate error: could not inspect unresolved PR feedback.")
        if feedback_result.error:
            print(f"ERROR: {feedback_result.error}")
        return 1

    if feedback_result.status == CheckStatus.PASSED:
        print(
            f"Buff iterate found no unresolved review threads for PR #{resolved_pr_number}."
        )
        print("Falling through to scour before finalization.")
        scour_exit = _run_scour_quietly(project_root)
        if scour_exit != 0:
            print(
                "Scour found issues. Next loop: return to swab until local fixes are green, then re-run scour."
            )
            print(
                "After scour is green again, run 'sm buff inspect' to refresh the PR loop."
            )
            return 1

        print(
            "Scour is clean. Next step: run 'sm buff inspect' to confirm the PR loop is still clean, then 'sm buff finalize --push'."
        )
        return 0

    protocol = _load_latest_protocol(project_root, resolved_pr_number)
    if protocol is None:
        print(
            "ERROR: buff iterate could not find the latest inspect protocol. Run 'sm buff inspect' first."
        )
        return 1

    selected = _select_iteration_batch(protocol)
    if selected is None:
        print(
            "ERROR: latest inspect protocol has no ordered thread frontier. Re-run 'sm buff inspect'."
        )
        return 1

    batch, rank = selected
    artifact_paths = _write_iteration_supporting_artifacts(protocol, batch, rank)

    print(f"Buff iterate round prepared for PR #{resolved_pr_number}.")
    print(
        "This round is locked to the highest-priority unresolved frontier from the latest inspect loop."
    )
    print(f"Loop dir: {protocol.get('loop_dir')}")
    print(f"Iteration artifact: {artifact_paths['iteration']}")
    print(f"Drafts artifact: {artifact_paths['drafts']}")
    print(f"Iteration log: {artifact_paths['iteration_log']}")
    print(f"Selected scenario: {batch[0].get('resolution_scenario')} (rank {rank})")
    print("Threads in scope:")
    for idx, thread in enumerate(batch, 1):
        location = str(thread.get("path") or "(no path)")
        if thread.get("line"):
            location += f":{thread['line']}"
        print(
            f"  [{idx}] {thread.get('thread_id')} :: {thread.get('category')} :: {location}"
        )
    print("Next step: address only this batch, then run 'sm buff iterate' again.")
    return 1


def _cmd_buff_finalize(pr_number: int | None, push_changes: bool) -> int:
    """Run final post-PR validation and optionally push the branch."""

    project_root = _project_root_from_cwd()
    try:
        resolved_pr_number = resolve_pr_number(_get_repo_slug(project_root), pr_number)
    except TriageError as exc:
        print(f"ERROR: {exc}")
        return 1

    feedback_result = _run_pr_feedback_gate(resolved_pr_number, project_root)
    if feedback_result.status != CheckStatus.PASSED:
        plan_path = _write_finalize_plan(
            project_root,
            resolved_pr_number,
            ready_to_push=False,
            push_requested=push_changes,
            next_step="sm buff inspect",
        )
        print("Buff finalize blocked: unresolved PR review threads remain.")
        print("Run 'sm buff inspect' and continue the inspect/iterate loop first.")
        _print_finalize_plan(plan_path)
        if feedback_result.output:
            print(feedback_result.output)
        if feedback_result.error:
            print(f"ERROR: {feedback_result.error}")
        return 1

    scour_exit = _run_scour_quietly(project_root)
    if scour_exit != 0:
        plan_path = _write_finalize_plan(
            project_root,
            resolved_pr_number,
            ready_to_push=False,
            push_requested=push_changes,
            next_step="sm swab",
        )
        print("Buff finalize blocked: scour found issues.")
        print(
            "Next loop: return to swab until fixes are green, then scour, then inspect again."
        )
        _print_finalize_plan(plan_path)
        return 1

    if not push_changes:
        plan_path = _write_finalize_plan(
            project_root,
            resolved_pr_number,
            ready_to_push=True,
            push_requested=False,
            next_step="sm buff finalize --push",
        )
        print(
            f"Buff finalize ready: PR #{resolved_pr_number} is clean. Re-run with --push to publish."
        )
        _print_finalize_plan(plan_path)
        return 0

    push_exit = _push_current_branch(project_root)
    if push_exit != 0:
        _write_finalize_plan(
            project_root,
            resolved_pr_number,
            ready_to_push=True,
            push_requested=True,
            next_step="retry git push",
        )
        return 1

    plan_path = _write_finalize_plan(
        project_root,
        resolved_pr_number,
        ready_to_push=True,
        push_requested=True,
        next_step="wait for CI then sm buff inspect",
    )

    print(
        f"Buff finalize complete: pushed the current branch for PR #{resolved_pr_number}."
    )
    _print_finalize_plan(plan_path)
    return 0


def _cmd_buff_inspect(args: argparse.Namespace, pr_number: int | None) -> int:
    """Run the post-PR inspection rail."""

    if not getattr(args, "json_output", False):
        print("== Buff inspect: checking CI code-scanning results ==")

    try:
        scan_exit, payload = run_triage(
            repo=args.repo,
            run_id=args.run_id,
            pr_number=pr_number,
            workflow=args.workflow,
            artifact=args.artifact,
            show_low_coverage=False,
            json_out=None,
            print_output=False,
        )
    except TriageError as exc:
        print(f"ERROR: {exc}")
        return 1

    if payload is None:
        print("ERROR: CI triage produced no payload.")
        return 1

    resolved_pr_number = payload.get("pr_number", pr_number)
    feedback_result = _run_pr_feedback_gate(
        resolved_pr_number,
        _project_root_from_cwd(),
    )
    payload["pr_feedback"] = {
        "gate": "myopia:ignored-feedback",
        "status": feedback_result.status.value,
        "status_detail": feedback_result.status_detail,
        "error": feedback_result.error,
        "fix_suggestion": feedback_result.fix_suggestion,
    }

    write_json_out(getattr(args, "output_file", None), payload)

    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2))
    else:
        print_triage(payload, show_low_coverage=False)

    feedback_blocking = feedback_result.status in {
        CheckStatus.FAILED,
        CheckStatus.ERROR,
    }

    if scan_exit != 0 or feedback_blocking:
        if not getattr(args, "json_output", False):
            if scan_exit != 0:
                print("\nBuff inspect found unresolved CI scan signals.")
            if feedback_result.status == CheckStatus.FAILED:
                print("Buff inspect found unresolved PR review threads.")
                print(
                    "Next step: run 'sm buff iterate' to take the highest-priority batch."
                )
                if feedback_result.output:
                    print(feedback_result.output)
            elif feedback_result.status == CheckStatus.ERROR:
                print("Buff inspect failed: could not verify unresolved PR feedback.")
                if feedback_result.error:
                    print(f"ERROR: {feedback_result.error}")
        return 1

    if not getattr(args, "json_output", False):
        print("\nBuff inspect clean: CI scan signals and PR feedback are resolved.")
        print("Next step: run 'sm buff finalize --push' when you want to publish.")
    return 0


def cmd_buff(args: argparse.Namespace) -> int:
    """Run post-PR CI triage and return non-zero on unresolved signals."""

    if hasattr(args, "pr_or_action"):
        try:
            normalized = _normalize_buff_args(args)
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 2
    else:
        normalized = argparse.Namespace(
            action="inspect",
            pr_number=getattr(args, "pr_number", None),
            scenario=getattr(args, "scenario", None),
            message=getattr(args, "message", None),
            resolve_thread=not bool(getattr(args, "no_resolve", False)),
            thread_id=getattr(args, "thread_id", None),
            push_changes=bool(getattr(args, "push", False)),
        )

    if normalized.action == "inspect":
        exit_code = _cmd_buff_inspect(args, normalized.pr_number)
        _fire_buff_hook(has_issues=exit_code != 0)
        return exit_code
    if normalized.action == "iterate":
        exit_code = _cmd_buff_iterate(normalized.pr_number)
        if exit_code == 0:
            try:
                from slopmop.workflow.hooks import on_iteration_started

                on_iteration_started(_project_root_from_cwd())
            except Exception:
                pass
        return exit_code
    if normalized.action == "status":
        return _cmd_buff_status(
            normalized.pr_number, normalized.watch, normalized.interval
        )
    if normalized.action == "finalize":
        return _cmd_buff_finalize(normalized.pr_number, normalized.push_changes)
    if normalized.action == "verify":
        return _cmd_buff_verify(normalized.pr_number)
    if normalized.action == "resolve":
        return _cmd_buff_resolve(
            normalized.pr_number,
            normalized.thread_id,
            normalized.scenario,
            normalized.message,
            normalized.resolve_thread,
        )

    exit_code = _cmd_buff_inspect(args, normalized.pr_number)
    _fire_buff_hook(has_issues=exit_code != 0)
    return exit_code


def _fire_buff_hook(has_issues: bool) -> None:
    try:
        from slopmop.workflow.hooks import on_buff_complete

        on_buff_complete(_project_root_from_cwd(), has_issues=has_issues)
    except Exception:
        pass
