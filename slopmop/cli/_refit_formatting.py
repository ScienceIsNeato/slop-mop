"""Formatting quarantine and drain steps for the refit onboarding process.

``run_formatting_quarantine_commit`` runs at ``--start`` time: formats
everything once and commits the result before the initial scour.

``drain_formatting_before_commit`` runs inside ``--iterate`` just before each
gate-fix commit: if the formatter wants to touch files that the gate fix
didn't touch, it commits those separately so the gate fix commit stays
logically clean.  Files where gate-fix logic and formatter output are
interleaved end up in the gate fix commit (splitting them would require
brittle git-patch algebra).

Separated from the main refit module to keep file sizes within code-sprawl
limits.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, cast

import slopmop.cli.refit as _refit
from slopmop.checks.base import BaseCheck

_status_path = _refit._status_path  # shared helper — defined in refit.py

# Enough to see what is happening without burying the next line of output.
_FORMATTING_PREVIEW_LIMIT = 25


def _collect_applicable_formatters(project_root_str: str) -> List[BaseCheck]:
    """Applicable formatting gates, configured the way the repo configured them.

    These were built with ``config={}``. A formatting gate auto-fixes, so an
    unconfigured one rewrites every file it can find: the repo's
    ``exclude_paths``, its ``include_dirs``, the gate's own ``exclude_dirs`` —
    none of it was loaded, because the config was never read. That is how a
    run scoped to a single package reformatted and committed 46 files across
    directories the repo had explicitly excluded (#357).

    Going through the registry is what every other caller does, and it applies
    the same repo-wide path filters the gates get during a normal scour.
    """
    from slopmop.core.gate_config import is_gate_enabled  # noqa: PLC0415
    from slopmop.core.registry import get_registry  # noqa: PLC0415
    from slopmop.sm import load_config  # noqa: PLC0415

    registry = get_registry()
    full_config = load_config(Path(project_root_str))

    applicable: List[BaseCheck] = []
    for name, check_cls in registry._check_classes.items():
        if not getattr(check_cls, "is_formatting_gate", False):
            continue
        check = registry.get_check(name, full_config)
        if check is None:
            continue
        # `get_check` builds whatever it is asked for; it does not decide
        # whether the repo wants the gate. Reading the config and then
        # rewriting files with a formatter the repo switched off would be the
        # same defect this function is being fixed for, one field along.
        if not is_gate_enabled(full_config, name):
            continue
        if check.is_applicable(project_root_str):
            applicable.append(check)
    return applicable


def _out_of_scope_warning(project_root: Path, paths: List[str]) -> List[str]:
    """Flag a formatting pass that reached outside the repo's declared scope.

    Belt and braces for a step that rewrites source and commits without being
    asked: if the scope filters are ever bypassed again, this says so at the
    moment it happens instead of leaving it to be found in ``git log``.
    """
    from slopmop.checks.base import _within_include_dirs  # noqa: PLC0415
    from slopmop.sm import load_config  # noqa: PLC0415

    try:
        full_config = load_config(project_root)
    except Exception:  # noqa: BLE001 — a warning must never break the commit
        return []

    includes: List[str] = []
    for category in full_config.values():
        if not isinstance(category, dict):
            continue
        raw = cast(Dict[str, Any], category).get("include_dirs")
        declared: List[Any] = (
            [raw] if isinstance(raw, str) else cast(List[Any], raw or [])
        )
        includes.extend(str(value) for value in declared)
    if not includes:
        return []

    strays = [p for p in paths if not _within_include_dirs(p, sorted(set(includes)))]
    if not strays:
        return []
    return [
        f"  ⚠️  {len(strays)} file(s) fall outside the configured include_dirs "
        f"({', '.join(sorted(set(includes)))}).",
        "     Check the scope before this commit lands: sm refit --start "
        "reformats and commits without prompting.",
    ]


def run_formatting_quarantine_commit(
    args: argparse.Namespace, project_root: Path
) -> bool:
    """Run all auto-fixable formatters and commit any changes as a dedicated
    formatting-only commit.

    This runs after the worktree-clean prerequisite check passes and before
    the initial scour so that gate analysis sees a fully-formatted codebase
    and no structural commits are contaminated with formatter noise.

    Returns True on success (commit made, or nothing to commit), False if a
    git operation fails.
    """
    json_mode = getattr(args, "json_output", False)
    project_root_str = str(project_root)

    if not json_mode:
        print(
            "🎨 Running formatters to quarantine style changes" " before gate analysis…"
        )

    applicable_checks = _collect_applicable_formatters(project_root_str)
    if not applicable_checks:
        if not json_mode:
            print(
                "  ℹ No formatter-applicable language detected"
                " — skipping formatting commit."
            )
        return True

    # Snapshot dirty files before running formatters so that upstream
    # changes (e.g. .gitignore from ensure_slopmop_gitignored) are not
    # bundled into the formatter-only commit.
    pre_fmt_dirty = {_status_path(l) for l in _refit._worktree_status(project_root)}

    for check in applicable_checks:
        if not json_mode:
            print(f"  → {check.display_name}")
        check.auto_fix(project_root_str)

    changed = _refit._worktree_status(project_root)
    formatter_paths = sorted(
        _status_path(l) for l in changed if _status_path(l) not in pre_fmt_dirty
    )
    if not formatter_paths:
        if not json_mode:
            print(
                "✅ Codebase already fully formatted" " — no formatting commit needed."
            )
        return True

    if not json_mode:
        # This commit lands without being asked, so what it contains has to be
        # readable at the moment it happens. It previously printed a count
        # alone: a run that reformatted 46 files across directories the repo
        # had scoped out said "46 file(s) reformatted" and committed, and the
        # damage was only discoverable afterwards in git log (#357). A list is
        # the difference between noticing now and reverting by hand later.
        print(f"  → {len(formatter_paths)} file(s) reformatted:")
        for path in formatter_paths[:_FORMATTING_PREVIEW_LIMIT]:
            print(f"      {path}")
        if len(formatter_paths) > _FORMATTING_PREVIEW_LIMIT:
            remaining = len(formatter_paths) - _FORMATTING_PREVIEW_LIMIT
            print(f"      ... and {remaining} more")
        for line in _out_of_scope_warning(project_root, formatter_paths):
            print(line)
        print("  Committing as dedicated formatting commit…")

    code, _, err = _refit._git_output(project_root, "add", "--", *formatter_paths)
    if code != 0:
        _refit._emit_standalone_protocol(
            args,
            project_root,
            event="formatting_quarantine_commit_failed",
            status="formatting_quarantine_commit_failed",
            next_action=("Resolve the git staging error and rerun `sm refit --start`."),
            human_lines=[
                f"Failed to stage formatting changes: {err or 'unknown error'}"
            ],
        )
        return False

    commit_msg = (
        "style: automated formatting pass (zero logic changes) [slop-mop refit]\n\n"
        "Generated by `sm refit --start`: formatter output only (autoflake/black/isort\n"
        "for Python, ESLint/Prettier/deno fmt for JS/TS). No logic was changed.\n"
        "Filtered with `git log --invert-grep --grep='slop-mop refit'`."
    )
    code, _, err = _refit._git_output(project_root, "commit", "-m", commit_msg)
    if code != 0:
        _refit._emit_standalone_protocol(
            args,
            project_root,
            event="formatting_quarantine_commit_failed",
            status="formatting_quarantine_commit_failed",
            next_action=("Resolve the git commit error and rerun `sm refit --start`."),
            human_lines=[
                f"Failed to commit formatting changes: {err or 'unknown error'}"
            ],
        )
        return False

    head_sha = _refit._current_head(project_root) or "unknown"
    if not json_mode:
        print(f"✅ Formatting commit created: {head_sha[:8]}")
    return True


def drain_formatting_before_commit(
    args: argparse.Namespace,
    project_root: Path,
    gate: str,
    gate_fix_status: List[str],
) -> bool:
    """Drain formatter drift on files outside the gate fix before committing.

    Runs all applicable formatters after the gate's scour pass.  Any files
    that are newly dirty — i.e. touched by the formatter but NOT part of the
    agent's gate fix — get committed as a dedicated formatting-only commit
    first, so the subsequent gate fix commit stays logically clean.

    Files that are in *both* the gate fix set and the formatter's output
    end up in the gate fix commit (mixed).  Splitting those would require
    git-patch algebra that is too fragile to implement reliably.

    Always returns True.  Git failures are non-fatal: the gate-fix commit
    proceeds regardless so the remediation loop is never blocked by
    formatting housekeeping.
    """
    json_mode = getattr(args, "json_output", False)
    project_root_str = str(project_root)

    applicable_checks = _collect_applicable_formatters(project_root_str)
    if not applicable_checks:
        return True

    for check in applicable_checks:
        check.auto_fix(project_root_str)

    try:
        status_after_fmt = _refit._worktree_status(project_root)
    except RuntimeError:
        return True  # Don't block on a status check failure

    gate_fix_paths = {_status_path(line) for line in gate_fix_status}
    fmt_paths = {_status_path(line) for line in status_after_fmt}
    formatting_only_paths = fmt_paths - gate_fix_paths

    if not formatting_only_paths:
        # Either no drift at all, or all drift is in files the gate fix
        # already touched (mixed commits — accepted limitation).
        return True

    if not json_mode:
        print(
            f"  🎨 {len(formatting_only_paths)} file(s) outside gate fix reformatted"
            " — committing as formatting-only commit first…"
        )

    code, _, err = _refit._git_output(
        project_root, "add", "--", *sorted(formatting_only_paths)
    )
    if code != 0:
        if not json_mode:
            print(f"  ⚠ Could not stage formatting files: {err or 'unknown error'}")
        return True  # Non-fatal

    commit_msg = (
        "style: automated formatting pass (zero logic changes) [slop-mop refit]\n\n"
        f"Committed during remediation of gate: {gate}\n"
        "Contains only formatter output for files not touched by the gate fix.\n"
        "Filtered with `git log --invert-grep --grep='slop-mop refit'`."
    )
    # Restrict the commit to formatting_only_paths so that any gate-fix
    # files already staged by the agent do not get bundled in.
    code, _, err = _refit._git_output(
        project_root, "commit", "-m", commit_msg, "--", *sorted(formatting_only_paths)
    )
    if code != 0:
        # Nothing staged (e.g. files were already clean after git add)
        if "nothing to commit" in (err or "").lower():
            return True
        if not json_mode:
            print(f"  ⚠ Could not commit formatting drift: {err or 'unknown error'}")
        # Reset staging area so the gate fix commit picks up everything
        _refit._git_output(project_root, "reset", "HEAD")
        return True  # Non-fatal

    head_sha = _refit._current_head(project_root) or "unknown"
    if not json_mode:
        print(f"  ✅ Formatting drain commit: {head_sha[:8]}")
    return True
