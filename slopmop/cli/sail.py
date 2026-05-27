"""Sail command — drive the workflow toward a green, buffed PR.

``sm sail`` reads the current workflow state and mode, executes the next
obvious step (or emits the exact command to run), then exits.  The caller
invokes ``sm sail`` again after completing any emitted instruction.

Design principles:

*   **Single-step, agent loops**: one action or instruction per call.
    Agents follow the emitted gradient and call ``sm sail`` again.
*   **Instruct, don't act**: sail tells the agent exactly what to run —
    including git/gh command lines — rather than running them itself.
    Committing and pushing are agent responsibilities.
*   **Two modes**: ITERATING (default, surface results to human) vs
    SAILING (human approved, drive all the way to PR_READY).  Invoking
    ``sm sail`` activates SAILING mode.
*   **HOLD pattern**: when a human decision is needed, sail emits a
    structured ``⚓ HOLD`` block so agents never have to guess.
*   **Delegates**: dispatches directly to ``cmd_swab``, ``cmd_scour``,
    or ``cmd_buff``.  State transitions are handled by the existing
    workflow hooks — sail does not duplicate state management.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Optional

from slopmop.workflow.state_machine import SailMode, WorkflowState
from slopmop.workflow.state_store import (
    read_sail_mode,
    read_state,
    write_sail_mode,
    write_state,
)

# ── Helpers ──────────────────────────────────────────────────────

_THEN_SAIL = "   Then: sm sail"


def _has_uncommitted_changes(project_root: Path) -> bool:
    """Return True when the working tree or index has uncommitted changes."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return bool(result.stdout.strip())


def _get_pr_number(project_root: Path) -> Optional[int]:
    """Auto-detect PR number from current branch."""
    from slopmop.cli.ci import _detect_pr_number

    return _detect_pr_number(project_root)


def _has_unpushed_commits(project_root: Path) -> bool:
    """Return True when HEAD is ahead of its upstream, or upstream is unknown."""
    upstream_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if upstream_result.returncode != 0:
        return True

    divergence_result = subprocess.run(
        ["git", "rev-list", "--left-right", "--count", "@{u}...HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if divergence_result.returncode != 0:
        return True

    counts = divergence_result.stdout.strip().split()
    if len(counts) != 2:
        return True

    try:
        ahead = int(counts[1])
    except ValueError:
        return True
    return ahead > 0


def _onboard_status(project_root: Path) -> str:
    """Return the onboarding status of the repo.

    Returns:
        "onboarded"  — .slopmop/ dir exists; repo is in the workflow loop.
        "init_done"  — .sb_config.json exists but .slopmop/ does not;
                       sm init ran but sm refit --start has not.
        "fresh"      — neither exists; repo has never been touched by slopmop.
    """
    if (project_root / ".slopmop").exists():
        return "onboarded"
    if (project_root / ".sb_config.json").exists():
        return "init_done"
    return "fresh"


def _reconcile_runtime_state(
    state: WorkflowState,
    project_root: Path,
) -> WorkflowState:
    """Heal stale persisted state using obvious repo/PR facts.

    ``sail`` should not suggest a push when the branch is already pushed and
    has an open PR. That condition means the loop has advanced past
    ``SCOUR_CLEAN`` even if the persisted state has not caught up yet.
    """
    if state != WorkflowState.SCOUR_CLEAN:
        return state

    pr_number = _get_pr_number(project_root)
    if pr_number is None:
        return state

    if _has_unpushed_commits(project_root):
        return state

    return WorkflowState.PR_OPEN


def _print_step(icon: str, heading: str, detail: str = "") -> None:
    print(f"\n⛵ sail → {icon} {heading}")
    if detail:
        print(f"   {detail}")
    print()


def _swab_args(args: argparse.Namespace) -> argparse.Namespace:
    """Build a namespace with every attribute ``cmd_swab`` expects.

    Sail's own parser only defines a handful of flags.  When delegating
    to ``cmd_swab`` we must provide the full set that
    ``_run_validation`` reads, otherwise it crashes with
    ``AttributeError: Namespace object has no attribute …``.
    """
    swab = argparse.Namespace(**vars(args))
    swab.quality_gates = getattr(args, "quality_gates", None)
    swab.no_auto_fix = getattr(args, "no_auto_fix", False)
    swab.no_fail_fast = getattr(args, "no_fail_fast", False)
    swab.no_cache = getattr(args, "no_cache", False)
    swab.sarif = getattr(args, "sarif", False)
    swab.json_output = getattr(args, "json_output", False)
    swab.json_file = getattr(args, "json_file", None)
    swab.output_file = getattr(args, "output_file", None)
    swab.verbose = getattr(args, "verbose", False)
    swab.quiet = getattr(args, "quiet", False)
    swab.static = getattr(args, "static", False)
    swab.porcelain = getattr(args, "porcelain", False)
    swab.swabbing_timeout = getattr(args, "swabbing_timeout", None)
    swab.clear_history = getattr(args, "clear_history", False)
    swab.ignore_baseline_failures = getattr(args, "ignore_baseline_failures", False)
    return swab


# ── State → action dispatch ─────────────────────────────────────


def _sail_idle(args: argparse.Namespace, project_root: Path) -> int:
    """S1 — IDLE: run swab to see where things stand."""
    _print_step("🧹", "Running swab", "No pending state — checking quality gates.")
    from slopmop.cli import cmd_swab

    return cmd_swab(_swab_args(args))


def _sail_swab_failing(args: argparse.Namespace, project_root: Path) -> int:
    """S2 — SWAB_FAILING: re-run swab (presumably after fixes)."""
    _print_step("🧹", "Re-running swab", "Checking whether fixes cleared the failures.")
    from slopmop.cli import cmd_swab

    return cmd_swab(_swab_args(args))


def _sail_swab_clean(args: argparse.Namespace, project_root: Path) -> int:
    """S3 — SWAB_CLEAN: instruct to commit (mode-aware), then run scour."""
    if _has_uncommitted_changes(project_root):
        sail_mode = read_sail_mode(project_root)
        if sail_mode == SailMode.SAILING:
            _print_step(
                "📝",
                "Commit your changes",
                "Swab is clean — stage and commit, then continue sailing.\n"
                "   Run: git add -A && git commit -m 'wip: ...'\n" + _THEN_SAIL,
            )
        else:
            _print_step(
                "📝",
                "Commit and share results",
                "Swab is clean — commit your changes, share the results\n"
                "   with the human, and await the next instruction.\n"
                "   Run: git add -A && git commit -m '...'\n"
                "   When ready to ship: sm sail",
            )
        return 0

    # Working tree is clean — advance to scour
    _print_step(
        "🔬", "Running scour", "Swab clean, changes committed — full pre-PR sweep."
    )
    from slopmop.cli import cmd_scour

    # Build a scour-appropriate args namespace
    scour_args = argparse.Namespace(**vars(args))
    scour_args.quality_gates = None
    scour_args.no_auto_fix = getattr(args, "no_auto_fix", False)
    scour_args.no_fail_fast = True
    scour_args.no_cache = False
    scour_args.sarif = getattr(args, "sarif", False)
    scour_args.json_output = getattr(args, "json_output", False)
    scour_args.json_file = None
    scour_args.output_file = getattr(args, "output_file", None)
    scour_args.verbose = getattr(args, "verbose", False)
    scour_args.quiet = getattr(args, "quiet", False)
    scour_args.static = getattr(args, "static", False)
    scour_args.porcelain = getattr(args, "porcelain", False)
    scour_args.swabbing_timeout = getattr(args, "swabbing_timeout", 0)
    return cmd_scour(scour_args)


def _sail_scour_failing(args: argparse.Namespace, project_root: Path) -> int:
    """S4 — SCOUR_FAILING: re-run swab to iterate on fixes."""
    _print_step(
        "🧹",
        "Re-running swab",
        "Scour found issues — fix the failures and iterate.",
    )
    from slopmop.cli import cmd_swab

    return cmd_swab(_swab_args(args))


def _sail_scour_clean(args: argparse.Namespace, project_root: Path) -> int:
    """S5 — SCOUR_CLEAN: instruct to push and open/update PR."""
    pr = _get_pr_number(project_root)
    if pr is not None:
        _print_step(
            "📤",
            "Push to existing PR",
            f"Scour is clean. PR #{pr} is open — push your commits.\n"
            f"   Run: git push\n" + _THEN_SAIL,
        )
    else:
        _print_step(
            "📤",
            "Push and open PR",
            "Scour is clean — time to publish.\n"
            "   Run: git push -u origin HEAD\n"
            "        gh pr create --fill\n" + _THEN_SAIL,
        )
    return 0


def _sail_pr_open(args: argparse.Namespace, project_root: Path) -> int:
    """S6 — PR_OPEN: buff inspect to triage CI + review threads."""
    _print_step(
        "✨", "Running buff inspect", "PR is open — triaging CI and review threads."
    )
    from slopmop.cli import cmd_buff
    from slopmop.cli.scan_triage import ARTIFACT_NAME, WORKFLOW_NAME

    pr = _get_pr_number(project_root)
    buff_args = argparse.Namespace(
        pr_or_action=str(pr) if pr else None,
        json_output=getattr(args, "json_output", False),
        repo=None,
        run_id=None,
        workflow=WORKFLOW_NAME,
        artifact=ARTIFACT_NAME,
    )
    return cmd_buff(buff_args)


def _sail_buff_failing(args: argparse.Namespace, project_root: Path) -> int:
    """S7 — BUFF_FAILING: buff inspect to show what to fix."""
    _print_step(
        "✨",
        "Running buff inspect",
        "Buff found issues — showing what needs attention.",
    )
    from slopmop.cli import cmd_buff
    from slopmop.cli.scan_triage import ARTIFACT_NAME, WORKFLOW_NAME

    pr = _get_pr_number(project_root)
    buff_args = argparse.Namespace(
        pr_or_action=str(pr) if pr else None,
        json_output=getattr(args, "json_output", False),
        repo=None,
        run_id=None,
        workflow=WORKFLOW_NAME,
        artifact=ARTIFACT_NAME,
    )
    return cmd_buff(buff_args)


def _sail_pr_ready(args: argparse.Namespace, project_root: Path) -> int:
    """S8 — PR_READY: surface to human for review, reset to iterating."""
    write_sail_mode(project_root, SailMode.ITERATING)
    print(
        "\n⛵ sail → 🏁 PR ready for human review\n"
        "   All CI green, no unresolved threads.\n"
        "   Share the PR with the human and await their decision.\n"
        "   (Sail mode reset to iterating for the next feature.)\n"
    )
    return 0


# ── Dispatch table ───────────────────────────────────────────────

_STATE_HANDLERS = {
    WorkflowState.IDLE: _sail_idle,
    WorkflowState.SWAB_FAILING: _sail_swab_failing,
    WorkflowState.SWAB_CLEAN: _sail_swab_clean,
    WorkflowState.SCOUR_FAILING: _sail_scour_failing,
    WorkflowState.SCOUR_CLEAN: _sail_scour_clean,
    WorkflowState.PR_OPEN: _sail_pr_open,
    WorkflowState.BUFF_FAILING: _sail_buff_failing,
    WorkflowState.PR_READY: _sail_pr_ready,
}


# ── Public entry point ───────────────────────────────────────────


def cmd_sail(args: argparse.Namespace) -> int:
    """Drive the workflow toward a green PR — one step at a time."""
    project_root = Path(getattr(args, "project_root", "."))

    status = _onboard_status(project_root)
    if status == "fresh":
        _print_step(
            "🆕",
            "Repo not onboarded",
            "This repo hasn't been set up with slop-mop yet.\n"
            "   Run: sm refit --start",
        )
        return 1
    if status == "init_done":
        _print_step(
            "🔧",
            "Onboarding incomplete",
            "sm init ran but refit hasn't started.\n" "   Run: sm refit --start",
        )
        return 1

    # Activating sail sets SAILING mode — persists across calls until PR_READY.
    write_sail_mode(project_root, SailMode.SAILING)

    persisted_state = read_state(project_root) or WorkflowState.IDLE
    state = _reconcile_runtime_state(persisted_state, project_root)
    if state != persisted_state:
        write_state(project_root, state)

    handler = _STATE_HANDLERS.get(state)
    if handler is None:
        print(f"⛵ sail: unknown state {state.value!r} — falling back to swab.")
        from slopmop.cli import cmd_swab

        return cmd_swab(_swab_args(args))

    return handler(args, project_root)
