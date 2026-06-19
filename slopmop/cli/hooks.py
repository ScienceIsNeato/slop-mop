"""Git commit hooks management for slop-mop CLI."""

import argparse
import re
import stat
from pathlib import Path
from typing import Any, Optional

# Hook markers
SB_HOOK_MARKER = "# MANAGED BY SLOP-MOP"
SB_HOOK_END_MARKER = "# END SLOP-MOP HOOK"


def _get_git_hooks_dir(project_root: Path) -> Optional[Path]:
    """Find the .git/hooks directory for a project."""
    git_dir = project_root / ".git"
    if not git_dir.is_dir():
        # Check if it's a worktree (git file instead of dir)
        git_file = project_root / ".git"
        if git_file.is_file():
            content = git_file.read_text().strip()
            if content.startswith("gitdir:"):
                git_path = Path(content.split(":", 1)[1].strip())
                if not git_path.is_absolute():
                    git_path = project_root / git_path
                return git_path / "hooks"
        return None
    return git_dir / "hooks"


def _generate_merged_branch_guard() -> str:
    """POSIX-sh guard: refuse a commit on an already-merged/deleted branch.

    Embedded at the top of the pre-commit hook so the dead-branch case is
    caught at *commit* time — before a pile of work accumulates on a ref
    that's already closed out and would just have to be redone on a fresh
    branch.  slopmop already ships a pre-push guard for the merged-PR case;
    this catches it earlier and handles more states.

    Detection, strongest first (each fail-open if the network or tooling is
    unavailable, so offline commits are never blocked):

      1. A MERGED PR for this branch via ``gh`` — catches squash/rebase
         merges that leave no ancestor relationship.  Authoritative.
      2. The remote head is gone (``git ls-remote``) — the usual post-merge
         state once the branch has been deleted.
      3. HEAD is already fully contained in a moved-on default branch
         (ref math) — the non-squash merge case.

    Allowed without question: integration branches (main/master/develop),
    never-pushed branches (no upstream), base-tracking branches
    (``git checkout -b X origin/main``), and mid rebase/merge/cherry-pick.
    Override one commit with ``git commit --no-verify``.

    Adapted from the welcome-to-willville ``check-branch-not-merged`` guard.
    Because the guard runs *before* the swab step, "allowed" cases must
    fall through (``return 0``) rather than ``exit`` — only a real block
    exits non-zero.  Returns a plain shell string (no Python interpolation)
    so it embeds verbatim via a single f-string field.
    """
    return r"""# --- merged/deleted-branch guard (slop-mop) ---
export GIT_TERMINAL_PROMPT=0  # never hang on an auth prompt inside a hook

_sm_block() {
    echo "" >&2
    echo "  ⛔ Branch '$_sm_branch' $1." >&2
    echo "     You're committing onto a branch that's already closed out. Start fresh:" >&2
    echo "" >&2
    echo "         git fetch $_sm_remote --prune" >&2
    echo "         git checkout -b <new-branch> $_sm_default_ref" >&2
    echo "" >&2
    echo "     (Intentional? Override this one commit with: git commit --no-verify)" >&2
    echo "" >&2
    exit 1
}

_sm_merged_branch_guard() {
    _sm_git_dir=$(git rev-parse --git-dir 2>/dev/null || echo .git)
    if [ -d "$_sm_git_dir/rebase-merge" ] || [ -d "$_sm_git_dir/rebase-apply" ] || [ -f "$_sm_git_dir/MERGE_HEAD" ] || [ -f "$_sm_git_dir/CHERRY_PICK_HEAD" ]; then
        return 0  # mid rebase/merge/cherry-pick — HEAD is intentionally unusual
    fi
    _sm_branch=$(git symbolic-ref --short -q HEAD 2>/dev/null || true)
    [ -z "$_sm_branch" ] && return 0  # detached HEAD
    case "$_sm_branch" in
        main|master|develop) return 0 ;;  # integration branches are fine
    esac
    _sm_upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)
    [ -z "$_sm_upstream" ] && return 0  # never pushed — no upstream to check
    _sm_remote=${_sm_upstream%%/*}
    _sm_remote_branch=${_sm_upstream#*/}
    _sm_default_branch=$(git symbolic-ref --quiet --short "refs/remotes/$_sm_remote/HEAD" 2>/dev/null | sed "s#^$_sm_remote/##")
    [ -z "$_sm_default_branch" ] && _sm_default_branch=main
    _sm_default_ref="$_sm_remote/$_sm_default_branch"

    # Skip ALL checks for a base-tracking branch — one tracking the DEFAULT
    # branch (git checkout -b X origin/main): it can't be "closed out", and
    # the ref checks would false-positive once the default moves ahead. This
    # must come before the gh check so a fresh base-tracking branch reusing an
    # old merged branch's name isn't false-blocked by that stale PR. Note:
    # tracking a NON-default remote ref (e.g. a renamed branch pushed with
    # `git push -u origin local:remote`) is NOT base-tracking — it has its own
    # remote branch that can be merged/deleted, so it still gets checked below
    # (against $_sm_remote_branch, the actual remote name).
    [ "$_sm_remote_branch" = "$_sm_default_branch" ] && return 0

    # 1) Authoritative: a MERGED PR for this branch (squash/rebase safe).
    #    Match on the remote branch name (the PR's head), and use `// empty`
    #    so "no merged PR" yields an empty string, not the literal "null" jq
    #    emits for an absent field (which would false-block as "PR #null").
    if command -v gh >/dev/null 2>&1; then
        _sm_merged_pr=$(gh pr list --head "$_sm_remote_branch" --state merged --json number --jq '.[0].number // empty' 2>/dev/null || true)
        [ -n "$_sm_merged_pr" ] && _sm_block "was merged via PR #$_sm_merged_pr"
    fi

    # 2) Remote head deleted (the usual post-merge state). Query the actual
    #    remote branch name, which can differ from the local one.
    if _sm_remote_heads=$(git ls-remote --heads "$_sm_remote" "$_sm_remote_branch" 2>/dev/null); then
        [ -z "$_sm_remote_heads" ] && _sm_block "no longer exists on '$_sm_remote' (deleted, typically after a merge)"
    fi

    # 3) HEAD already fully merged into the default branch (non-squash). Require
    #    the default to be strictly AHEAD so a fresh branch at the default tip
    #    isn't flagged.
    git fetch --quiet "$_sm_remote" "$_sm_default_branch" 2>/dev/null || true
    if git rev-parse --verify --quiet "$_sm_default_ref" >/dev/null; then
        _sm_ahead=$(git rev-list --count "HEAD..$_sm_default_ref" 2>/dev/null || echo 0)
        if [ "$_sm_ahead" -gt 0 ] && git merge-base --is-ancestor HEAD "$_sm_default_ref" 2>/dev/null; then
            _sm_block "is already fully merged into $_sm_default_ref"
        fi
    fi
    return 0
}

_sm_merged_branch_guard
# --- end merged/deleted-branch guard ---"""


def _generate_hook_script(verb: str) -> str:
    """Generate the pre-commit hook script content.

    The hook assumes ``sm`` is on PATH — ``pipx install slopmop``
    puts the entrypoint there, and so does the legacy setup.sh.
    The old hook did 30 lines of submodule discovery and venv
    hunting that broke the moment a pipx user ran ``sm commit-hooks
    install`` (no ``slop-mop/`` directory to find).  If ``sm`` isn't
    on PATH the hook fails with ``sm: command not found``, which is
    the honest signal: fix your install.

    Note: The generated script uses a ``#!/bin/sh`` shebang and POSIX
    shell syntax.  On Windows this requires Git for Windows (Git Bash)
    or WSL — native ``cmd.exe`` / PowerShell won't run it.

    Args:
        verb: The validation command to run ("swab" or "scour").
    """

    json_file = f".slopmop/last_{verb}.json"
    guard = _generate_merged_branch_guard()
    return f"""#!/bin/sh
{SB_HOOK_MARKER}
#
# Pre-commit hook managed by slop-mop
# Command: sm {verb} --porcelain
# Guard: refuse commits on an already-merged or deleted branch
# To remove: sm commit-hooks uninstall
#

{guard}

if ! command -v sm >/dev/null 2>&1; then
    echo "❌ sm not found on PATH"
    echo "   Install: pipx install slopmop"
    exit 1
fi

mkdir -p .slopmop
sm {verb} --porcelain --swabbing-timeout 0 --json-file {json_file}
result=$?

if [ $result -ne 0 ]; then
    echo ""
    echo "❌ Commit blocked by slop-mop quality gates"
    echo "   Structured results: {json_file}"
    echo ""
    exit 1
fi

exit 0
{SB_HOOK_END_MARKER}
"""


def _generate_pre_push_hook_script() -> str:
    """Generate a pre-push hook: merged-branch guard, then a full scour.

    Two things run before a push is allowed:

    1. Merged-branch guard. Git feeds the refs actually being pushed on stdin
       (one line per ref: ``<local ref> <local sha> <remote ref> <remote
       sha>``). The guard reads those rather than ``HEAD`` so a push like
       ``git push origin merged-feature:merged-feature`` from another checkout
       is still inspected. For each pushed branch it asks GitHub whether that
       branch name has an already-merged PR; if yes, pushing it is almost
       always accidental follow-up on a branch that should have been retired.

    2. ``sm scour``. The thorough validation CI runs, executed locally so
       scour-only failures surface here instead of on a red build. swab-level
       results from the pre-commit hook are reused from the cache (keyed
       per-gate by a fingerprint), so only scour-only and changed gates run
       fresh — a cached scour is dramatically faster than a cold one.
    """

    return f"""#!/bin/sh
{SB_HOOK_MARKER}
#
# Pre-push hook managed by slop-mop
# Command: merged-branch-guard + sm scour
# To remove: sm commit-hooks uninstall
#

if ! command -v gh >/dev/null 2>&1; then
    echo "❌ gh not found on PATH"
    echo "   This guard checks whether the branch already has a merged PR."
    echo "   Install GitHub CLI: https://cli.github.com/"
    exit 1
fi

zero_sha="0000000000000000000000000000000000000000"

# Git passes the refs being pushed on stdin, one per line:
#   <local ref> <local sha> <remote ref> <remote sha>
# Inspect each pushed branch rather than HEAD so a push that names a
# branch other than the current checkout is still guarded.
while read -r local_ref local_sha remote_ref remote_sha; do
    # Only branch refs can correspond to a PR head.
    case "$local_ref" in
        refs/heads/*) branch=${{local_ref#refs/heads/}} ;;
        *) continue ;;
    esac

    # Skip deletions (local sha all zeros) — nothing is being written.
    if [ "$local_sha" = "$zero_sha" ]; then
        continue
    fi

    merged_line=$(gh pr list \
        --head "$branch" \
        --state merged \
        --json number,url \
        --limit 1 \
        --jq 'if length>0 then "\\(.[0].number)\\t\\(.[0].url)" else "" end' \
        2>/dev/null)
    status=$?

    if [ $status -ne 0 ]; then
        echo "❌ Could not verify merged-PR status for branch '$branch'"
        echo "   gh query failed; refusing push to avoid writing onto a merged branch."
        exit 1
    fi

    if [ -n "$merged_line" ]; then
        pr_number=$(printf '%s' "$merged_line" | cut -f1)
        pr_url=$(printf '%s' "$merged_line" | cut -f2-)
        echo ""
        echo "❌ Push blocked: branch '$branch' already has merged PR #$pr_number"
        echo "   $pr_url"
        echo ""
        echo "You're missing some context. It appears as if a branch was merged"
        echo "out from under you while you were working on it."
        echo "sync against main, checkout a new branch, and open a new PR."
        echo ""
        exit 1
    fi
done

# Merged-branch guard passed for every pushed ref. Now run the full scour so
# scour-only failures are caught here instead of in CI. swab-level gate results
# from the pre-commit hook are reused from cache; only scour-only and changed
# gates run fresh, so this is fast on an unchanged tree.
if ! command -v sm >/dev/null 2>&1; then
    echo "❌ sm not found on PATH"
    echo "   Install: pipx install slopmop"
    exit 1
fi

mkdir -p .slopmop
echo "🧽 slop-mop: running scour before push (cached swab results are reused)…"
sm scour --porcelain --json-file .slopmop/last_scour.json
scour_result=$?

if [ $scour_result -ne 0 ]; then
    echo ""
    echo "❌ Push blocked by slop-mop scour"
    echo "   Structured results: .slopmop/last_scour.json"
    echo "   This is the same scour CI runs — fix it here to avoid a red build."
    echo "   Bypass once (not recommended): git push --no-verify"
    echo ""
    exit 1
fi

exit 0
{SB_HOOK_END_MARKER}
"""


def _parse_hook_info(hook_content: str) -> Optional[dict[str, Any]]:
    """Parse sb-managed hook to extract info."""
    if SB_HOOK_MARKER not in hook_content:
        return None

    # Try to extract command label from the script header.
    match = re.search(r"# Command: (.+)", hook_content)
    if match:
        command = match.group(1).strip()
        display = command.removeprefix("sm ")
        return {"verb": display, "managed": True}

    return {"verb": "unknown", "managed": True}


def _hooks_status(project_root: Path, hooks_dir: Path) -> int:
    """Show status of installed hooks."""
    print()
    print("🪝 Git Hooks Status")
    print("=" * 60)
    from slopmop.reporting import print_project_header

    print_project_header(str(project_root))
    print(f"📁 Hooks dir: {hooks_dir}")
    print()

    if not hooks_dir.exists():
        print("ℹ️  No hooks directory found")
        print("   Install a hook: sm commit-hooks install <verb>")
        print()
    else:
        hook_types = ["pre-commit", "pre-push", "commit-msg"]
        found_sb_hooks: list[tuple[str, dict[str, Any]]] = []
        found_other_hooks: list[str] = []

        for hook_type in hook_types:
            hook_file = hooks_dir / hook_type
            if hook_file.exists():
                content = hook_file.read_text()
                info = _parse_hook_info(content)
                if info:
                    found_sb_hooks.append((hook_type, info))
                else:
                    found_other_hooks.append(hook_type)

        if found_sb_hooks:
            print("🪣 Slop-Mop-managed hooks:")
            for hook_type, info in found_sb_hooks:
                print(f"   ✅ {hook_type}: {info['verb']}")
            print()

        if found_other_hooks:
            print("📋 Other hooks (not managed by sm):")
            for hook_type in found_other_hooks:
                print(f"   • {hook_type}")
            print()

        if not found_sb_hooks and not found_other_hooks:
            print("ℹ️  No commit hooks installed")
            print()

    print("Commands:")
    print("   sm commit-hooks install           # Install pre-commit + pre-push guard")
    print("   sm commit-hooks uninstall          # Remove sm hooks")
    print(
        "   sm gang press                 # System-wide command intercepts + git wrapper"
    )
    print()
    return 0


def _hooks_install(project_root: Path, hooks_dir: Path, verb: str) -> int:
    """Install managed pre-commit + pre-push hooks."""
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_file = hooks_dir / "pre-commit"
    pre_push_file = hooks_dir / "pre-push"

    if hook_file.exists():
        content = hook_file.read_text()
        if SB_HOOK_MARKER in content:
            print("ℹ️  Updating existing slopmop hook...")
        else:
            print(f"⚠️  Existing pre-commit hook found at: {hook_file}")
            print("   This hook is not managed by slopmop.")
            print()
            print("Options:")
            print("   1. Back up your existing hook and run install again")
            print("   2. Manually add 'sm swab' to your existing hook")
            print()
            return 1

    if pre_push_file.exists():
        content = pre_push_file.read_text()
        if SB_HOOK_MARKER in content:
            print("ℹ️  Updating existing slopmop pre-push guard...")
        else:
            print(f"⚠️  Existing pre-push hook found at: {pre_push_file}")
            print("   This hook is not managed by slopmop.")
            print()
            print("Options:")
            print("   1. Back up your existing hook and run install again")
            print(
                "   2. Manually add the merged-branch guard from sm commit-hooks output"
            )
            print()
            return 1

    hook_content = _generate_hook_script(verb)
    hook_file.write_text(hook_content)
    pre_push_content = _generate_pre_push_hook_script()
    pre_push_file.write_text(pre_push_content)
    hook_file.chmod(
        hook_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    )
    pre_push_file.chmod(
        pre_push_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    )

    print()
    print("✅ Pre-commit hook installed!")
    print("=" * 60)
    from slopmop.reporting import print_project_header

    print_project_header(str(project_root))
    print(f"📄 Hook: {hook_file}")
    print(f"📄 Hook: {pre_push_file}")
    print(f"🎯 Pre-commit: sm {verb} + merged/deleted-branch guard")
    print("🎯 Pre-push:   merged-branch guard + sm scour")
    print()
    print(f"The pre-commit hook runs 'sm {verb}' before each commit and first")
    print("refuses the commit if the branch is already merged or deleted (so")
    print("you don't pile work onto a dead branch).")
    print()
    print("The pre-push hook runs the full 'sm scour' — the same validation CI")
    print("runs — so scour-only failures are caught before you push, not on a red")
    print("build. swab results from the commit hook are reused from cache, so")
    print("only scour-only and changed gates run fresh. Bypass once with")
    print("'git push --no-verify'.")
    print()
    print("To remove: sm commit-hooks uninstall")
    print()
    return 0


def _hooks_uninstall(_project_root: Path, hooks_dir: Path) -> int:
    """Remove all sm-managed hooks."""
    if not hooks_dir.exists():
        print("ℹ️  No hooks directory found")
        return 0

    removed: list[str] = []
    hook_types = ["pre-commit", "pre-push", "commit-msg"]

    for hook_type in hook_types:
        hook_file = hooks_dir / hook_type
        if hook_file.exists():
            content = hook_file.read_text()
            if SB_HOOK_MARKER in content:
                hook_file.unlink()
                removed.append(hook_type)

    print()
    if removed:
        print("✅ Removed slopmop-managed hooks:")
        for hook_type in removed:
            print(f"   • {hook_type}")
    else:
        print("ℹ️  No slopmop-managed hooks found")
    print()
    return 0


def cmd_commit_hooks(args: argparse.Namespace) -> int:
    """Handle the commit-hooks command."""
    project_root = Path(args.project_root).resolve()

    if not args.hooks_action:
        args.hooks_action = "status"

    hooks_dir = _get_git_hooks_dir(project_root)

    if not hooks_dir:
        print(f"❌ Not a git repository: {project_root}")
        print("   Initialize git first: git init")
        return 1

    if args.hooks_action == "status":
        return _hooks_status(project_root, hooks_dir)
    elif args.hooks_action == "install":
        return _hooks_install(project_root, hooks_dir, args.hook_verb)
    elif args.hooks_action == "uninstall":
        return _hooks_uninstall(project_root, hooks_dir)
    else:
        print(f"❌ Unknown action: {args.hooks_action}")
        return 1


# ---------------------------------------------------------------------------
# Refit lifecycle helpers — park and restore the pre-commit hook so that
# sm refit --start / --finish can manage it without any --no-verify bypass.
# ---------------------------------------------------------------------------

#: Suffix appended to the hook filename while a refit is in progress.
HOOK_PARK_SUFFIX = ".refit-parked"


def _pre_commit_hook_path(project_root: Path) -> Optional[Path]:
    """Return the canonical pre-commit hook path for *project_root*."""
    hooks_dir = _get_git_hooks_dir(project_root)
    if hooks_dir is None:
        return None
    return hooks_dir / "pre-commit"


def _parked_hook_path(project_root: Path) -> Optional[Path]:
    """Return the park-aside path for the pre-commit hook."""
    hook = _pre_commit_hook_path(project_root)
    return hook.with_suffix(HOOK_PARK_SUFFIX) if hook else None


def park_slopmop_hook(project_root: Path, json_mode: bool = False) -> None:
    """Move the slop-mop pre-commit hook aside for the duration of a refit.

    Only acts on hooks installed by slop-mop (identified by ``SB_HOOK_MARKER``).
    Third-party hooks are left in place — they're not ours to manage and the
    user has presumably arranged for them to work safely during refit.

    After ``sm refit --finish``, call ``restore_slopmop_hook`` to put it back.
    """
    hook = _pre_commit_hook_path(project_root)
    if not hook or not hook.exists():
        return
    try:
        content = hook.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    if SB_HOOK_MARKER not in content:
        return  # not ours — leave it alone

    parked = _parked_hook_path(project_root)
    if parked is None:
        return
    try:
        hook.rename(parked)
        if not json_mode:
            print(
                f"ℹ️  Pre-commit hook parked for refit: {parked.name}\n"
                "   It will be restored automatically by `sm refit --finish`."
            )
    except OSError as exc:
        # Non-fatal: worst case the user gets their own hook running during
        # refit, which is the pre-lifecycle-management status quo.
        if not json_mode:
            print(f"⚠️  Could not park pre-commit hook (continuing anyway): {exc}")


def restore_slopmop_hook(project_root: Path, json_mode: bool = False) -> None:
    """Restore a previously-parked slop-mop pre-commit hook after ``--finish``."""
    parked = _parked_hook_path(project_root)
    if parked is None or not parked.exists():
        return

    hook = _pre_commit_hook_path(project_root)
    if hook is None:
        return
    if hook.exists():
        # Something else installed a hook while refit was running.  Don't
        # clobber it; leave the parked backup and warn the user.
        if not json_mode:
            print(
                f"⚠️  Could not restore parked hook: {hook} already exists.\n"
                f"   Parked backup kept at: {parked}"
            )
        return

    try:
        parked.rename(hook)
        if not json_mode:
            print(f"✅ Pre-commit hook restored from refit backup: {hook.name}")
    except OSError as exc:
        if not json_mode:
            print(
                f"⚠️  Could not restore parked hook (manual action needed): {exc}\n"
                f"   Parked backup: {parked}\n"
                f"   To restore manually: mv {parked} {hook}"
            )
