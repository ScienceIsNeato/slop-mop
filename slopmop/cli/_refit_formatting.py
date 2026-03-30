"""Formatting quarantine step for the refit onboarding process.

Runs all auto-fixable formatters and commits any changes as a dedicated
formatting-only commit before the initial scour generates the gate plan.
Separated from the main refit module to keep file size within code-sprawl
limits.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import slopmop.cli.refit as _refit


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
