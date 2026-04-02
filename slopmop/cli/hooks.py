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
    return f"""#!/bin/sh
{SB_HOOK_MARKER}
#
# Pre-commit hook managed by slop-mop
# Command: sm {verb}
# To remove: sm commit-hooks uninstall
#

if ! command -v sm >/dev/null 2>&1; then
    echo "❌ sm not found on PATH"
    echo "   Install: pipx install slopmop"
    exit 1
fi

mkdir -p .slopmop
sm {verb} --swabbing-time 0 --json-file {json_file}
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


def _parse_hook_info(hook_content: str) -> Optional[dict[str, Any]]:
    """Parse sb-managed hook to extract info."""
    if SB_HOOK_MARKER not in hook_content:
        return None

    # Try to extract the command verb
    match = re.search(r"# Command: sm (\w+)", hook_content)
    if match:
        return {"verb": match.group(1), "managed": True}

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
        return 0

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
    print("   sm commit-hooks install           # Install pre-commit hook (swab)")
    print("   sm commit-hooks uninstall          # Remove sm hooks")
    print()
    return 0


def _hooks_install(project_root: Path, hooks_dir: Path, verb: str) -> int:
    """Install a pre-commit hook."""
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_file = hooks_dir / "pre-commit"

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

    hook_content = _generate_hook_script(verb)
    hook_file.write_text(hook_content)
    hook_file.chmod(
        hook_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    )

    print()
    print("✅ Pre-commit hook installed!")
    print("=" * 60)
    from slopmop.reporting import print_project_header

    print_project_header(str(project_root))
    print(f"📄 Hook: {hook_file}")
    print(f"🎯 Command: sm {verb}")
    print()
    print(f"The hook will run 'sm {verb}' before each commit.")
    print("Commits will be blocked if quality gates fail.")
    print()
    print("To remove: sm commit-hooks uninstall")
    print()
    return 0


def _hooks_uninstall(project_root: Path, hooks_dir: Path) -> int:
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


def _pre_commit_hook_path(project_root: Path) -> Path:
    """Return the canonical pre-commit hook path for *project_root*."""
    return project_root / ".git" / "hooks" / "pre-commit"


def _parked_hook_path(project_root: Path) -> Path:
    """Return the park-aside path for the pre-commit hook."""
    return _pre_commit_hook_path(project_root).with_suffix(HOOK_PARK_SUFFIX)


def park_slopmop_hook(project_root: Path) -> None:
    """Move the slop-mop pre-commit hook aside for the duration of a refit.

    Only acts on hooks installed by slop-mop (identified by ``SB_HOOK_MARKER``).
    Third-party hooks are left in place — they're not ours to manage and the
    user has presumably arranged for them to work safely during refit.

    After ``sm refit --finish``, call ``restore_slopmop_hook`` to put it back.
    """
    hook = _pre_commit_hook_path(project_root)
    if not hook.exists():
        return
    try:
        content = hook.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    if SB_HOOK_MARKER not in content:
        return  # not ours — leave it alone

    parked = _parked_hook_path(project_root)
    try:
        hook.rename(parked)
        print(
            f"ℹ️  Pre-commit hook parked for refit: {parked.name}\n"
            "   It will be restored automatically by `sm refit --finish`."
        )
    except OSError as exc:
        # Non-fatal: worst case the user gets their own hook running during
        # refit, which is the pre-lifecycle-management status quo.
        print(f"⚠️  Could not park pre-commit hook (continuing anyway): {exc}")


def restore_slopmop_hook(project_root: Path) -> None:
    """Restore a previously-parked slop-mop pre-commit hook after ``--finish``."""
    parked = _parked_hook_path(project_root)
    if not parked.exists():
        return

    hook = _pre_commit_hook_path(project_root)
    if hook.exists():
        # Something else installed a hook while refit was running.  Don't
        # clobber it; leave the parked backup and warn the user.
        print(
            f"⚠️  Could not restore parked hook: {hook} already exists.\n"
            f"   Parked backup kept at: {parked}"
        )
        return

    try:
        parked.rename(hook)
        print(f"✅ Pre-commit hook restored from refit backup: {hook.name}")
    except OSError as exc:
        print(
            f"⚠️  Could not restore parked hook (manual action needed): {exc}\n"
            f"   Parked backup: {parked}\n"
            f"   To restore manually: mv {parked} {hook}"
        )
