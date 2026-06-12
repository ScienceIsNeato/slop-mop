"""Entry point for pre-commit framework hooks (.pre-commit-hooks.yaml).

When slop-mop is consumed via https://pre-commit.com, the hook runs in
every contributor's checkout of the host repo — including checkouts
where slop-mop has never been onboarded. The guard here is what makes
that safe: the real gate only runs in maintenance mode (the repo went
through ``sm init`` + ``sm refit``, leaving a ``.slopmop/`` directory).
Anything earlier in the lifecycle gets a one-line nudge and exit 0, so
adding the hook to a team's ``.pre-commit-config.yaml`` never blocks a
contributor who hasn't adopted slop-mop yet.
"""

import argparse
from pathlib import Path

# Hook verb → sm validation verb. Identity today, but the indirection
# documents that the hook surface is intentionally narrower than the CLI.
_HOOK_VERBS = ("swab", "scour")


def cmd_hook(args: argparse.Namespace) -> int:
    """Handle ``sm hook <swab|scour>`` — the pre-commit framework entry.

    Exit codes:
      0 — gates passed, or repo not yet onboarded (warn-and-allow)
      nonzero — gates failed in an onboarded repo (block the commit/push)
    """
    verb = args.hook_verb
    if verb not in _HOOK_VERBS:
        print(f"❌ Unknown hook verb: {verb} (expected one of {_HOOK_VERBS})")
        return 2

    project_root = Path(args.project_root).resolve()

    from slopmop.cli.sail import _onboard_status

    # Contract (see _onboard_status docstring): returns exactly one of
    # "onboarded" | "init_done" | "fresh". All three paths are covered by
    # tests/unit/test_precommit_hook.py, so a contract change breaks loudly.
    status = _onboard_status(project_root)
    if status != "onboarded":
        remedy = (
            "sm refit --start"
            if status == "init_done"
            else "sm init && sm refit --start"
        )
        print(
            f"⚠️  slop-mop hook skipped: this repo is not onboarded "
            f"(status: {status}).\n"
            f"   To activate quality gates, run: {remedy}\n"
            f"   Until then this hook always passes."
        )
        return 0

    from slopmop.sm import main as sm_main

    argv = [verb, "--porcelain", "--project-root", str(project_root)]
    if verb == "swab":
        # Hooks must be deterministic: never skip gates on a time budget.
        argv += ["--swabbing-timeout", "0"]
    return sm_main(argv)
