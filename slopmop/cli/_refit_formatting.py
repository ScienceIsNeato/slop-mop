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
from typing import List

import slopmop.cli.refit as _refit

_status_path = _refit._status_path  # shared helper — defined in refit.py


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
    from slopmop.checks.javascript.lint_format import (  # noqa: PLC0415
        JavaScriptLintFormatCheck,
    )
    from slopmop.checks.python.lint_format import (  # noqa: PLC0415
        PythonLintFormatCheck,
    )

    json_mode = getattr(args, "json_output", False)
    project_root_str = str(project_root)

    if not json_mode:
        print(
            "🎨 Running formatters to quarantine style changes" " before gate analysis…"
        )

    any_formatter_applicable = False

    py_check = PythonLintFormatCheck(config={})
    if py_check.is_applicable(project_root_str):
        if not json_mode:
            print("  → Python: autoflake + black + isort")
        py_check.auto_fix(project_root_str)
        any_formatter_applicable = True

    js_check = JavaScriptLintFormatCheck(config={})
    if js_check.is_applicable(project_root_str):
        if not json_mode:
            print("  → JavaScript/TypeScript: ESLint/Prettier or deno fmt")
        js_check.auto_fix(project_root_str)
        any_formatter_applicable = True

    if not any_formatter_applicable:
        if not json_mode:
            print(
                "  ℹ No formatter-applicable language detected"
                " — skipping formatting commit."
            )
        return True

    changed = _refit._worktree_status(project_root)
    if not changed:
        if not json_mode:
            print(
                "✅ Codebase already fully formatted" " — no formatting commit needed."
            )
        return True

    if not json_mode:
        print(
            f"  → {len(changed)} file(s) reformatted."
            "  Committing as dedicated formatting commit…"
        )

    code, _, err = _refit._git_output(project_root, "add", "-A")
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
        "This commit was generated automatically by `sm refit --start`.\n"
        "It contains only formatter output (autoflake/black/isort for Python,\n"
        "ESLint/Prettier/deno fmt for JS/TS). Review can safely be skipped\n"
        "or filtered with `git log --invert-grep --grep='slop-mop refit'`."
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
    from slopmop.checks.javascript.lint_format import (  # noqa: PLC0415
        JavaScriptLintFormatCheck,
    )
    from slopmop.checks.python.lint_format import (  # noqa: PLC0415
        PythonLintFormatCheck,
    )

    json_mode = getattr(args, "json_output", False)
    project_root_str = str(project_root)

    py_check = PythonLintFormatCheck(config={})
    js_check = JavaScriptLintFormatCheck(config={})
    py_applicable = py_check.is_applicable(project_root_str)
    js_applicable = js_check.is_applicable(project_root_str)

    if not py_applicable and not js_applicable:
        return True

    if py_applicable:
        py_check.auto_fix(project_root_str)
    if js_applicable:
        js_check.auto_fix(project_root_str)

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
