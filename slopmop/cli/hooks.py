"""Git commit hooks management for slop-mop CLI."""

import argparse
import hashlib
import importlib.resources
import os
import re
import stat
from pathlib import Path
from typing import Any, Optional

# Hook markers
SB_HOOK_MARKER = "# MANAGED BY SLOP-MOP"
SB_HOOK_END_MARKER = "# END SLOP-MOP HOOK"

# Deep hook markers (written into shell rc files)
DEEP_HOOK_MARKER = "# MANAGED BY SLOP-MOP DEEP"
DEEP_HOOK_END_MARKER = "# END SLOP-MOP DEEP"

# Exact phrase the user must supply to opt in to system-wide alias installation.
# Kept here (not in sm.py) so tests can import it without touching the parser.
DEEP_HOOKS_CONFIRM_PHRASE = "I understand this aliases git system-wide on this machine"

_SLOPMOP_HOME = Path.home() / ".slopmop"
_WRAPPER_DEST = _SLOPMOP_HOME / "bin" / "git_wrapper.sh"


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
# Command: sm {verb} --porcelain
# To remove: sm commit-hooks uninstall
#

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


def _parse_hook_info(hook_content: str) -> Optional[dict[str, Any]]:
    """Parse sb-managed hook to extract info."""
    if SB_HOOK_MARKER not in hook_content:
        return None

    # Try to extract the command verb
    match = re.search(r"# Command: sm (\w+)", hook_content)
    if match:
        return {"verb": match.group(1), "managed": True}

    return {"verb": "unknown", "managed": True}


def _rc_has_marker(path: Path) -> bool:
    """Read rc file safely and check for the deep hook marker."""
    try:
        return DEEP_HOOK_MARKER in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


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
    print("   sm commit-hooks install           # Install pre-commit hook (swab)")
    print("   sm commit-hooks install --deep    # Also install system git wrapper")
    print("   sm commit-hooks uninstall          # Remove sm hooks")
    print()

    # Deep hook status
    print("🔒 Deep Hooks (system-level git wrapper):")
    if _WRAPPER_DEST.exists():
        print(f"   ✅ git_wrapper.sh installed at {_WRAPPER_DEST}")
    else:
        print(f"   ✗  Not installed (run: sm commit-hooks install --deep)")
    home = Path.home()
    rc_candidates = [
        home / ".zshrc",
        home / ".zprofile",
        home / ".bashrc",
        home / ".bash_profile",
    ]
    wired = [str(p) for p in rc_candidates if p.exists() and _rc_has_marker(p)]
    if wired:
        print(f"   ✅ Shell alias active in: {', '.join(wired)}")
    else:
        print("   ✗  No shell alias found in rc files")
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


def _deep_rc_candidates() -> list[Path]:
    """All shell rc files that might contain the deep hook alias block."""
    home = Path.home()
    return [
        home / ".zshrc",
        home / ".zprofile",
        home / ".bashrc",
        home / ".bash_profile",
    ]


def _get_deep_rc_files() -> list[Path]:
    """Return shell rc files to update, based on the current shell."""
    shell = os.environ.get("SHELL", "")
    home = Path.home()
    if "zsh" in shell:
        candidates = [home / ".zshrc"]
    elif "bash" in shell:
        candidates = [home / ".bashrc", home / ".bash_profile"]
    else:
        candidates = [home / ".zshrc", home / ".bashrc"]
    # Always return at least the first candidate even if it doesn't exist yet
    return [p for p in candidates if p.exists()] or candidates[:1]


def _deep_hooks_install(confirm: str = "") -> int:
    """Install git_wrapper.sh to ~/.slopmop/bin/ and wire a shell alias.

    Requires the caller to pass the exact confirmation phrase — this operation
    modifies the user's shell rc file and affects every git invocation in their
    terminal, not just this repo.
    """
    if confirm != DEEP_HOOKS_CONFIRM_PHRASE:
        print()
        print("⚠️  Deep hooks require explicit confirmation")
        print("=" * 60)
        print()
        print("This will write a shell alias to your rc file:")
        print()
        print('   alias git="$HOME/.slopmop/bin/git_wrapper.sh"')
        print()
        print("What that means for you:")
        print("  • Every git command in your terminal routes through the wrapper")
        print("  • git commit --no-verify (and variants) will be blocked in ALL repos")
        print("  • AI agents and terminal tools are affected — that is the point")
        print("  • GUI clients (Tower, Fork, Sourcetree) use their own git binary")
        print("    and are NOT affected by a shell alias")
        print("  • Other users on this machine are NOT affected")
        print("  • The alias persists after slopmop is uninstalled until you run:")
        print("    sm commit-hooks uninstall --deep")
        print()
        print("To proceed, add this flag exactly:")
        print(f'   --confirm "{DEEP_HOOKS_CONFIRM_PHRASE}"')
        print()
        return 1
    bin_dir = _SLOPMOP_HOME / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    wrapper_bytes = (
        importlib.resources.files("slopmop.data")
        .joinpath("git_wrapper.sh")
        .read_bytes()
    )

    if _WRAPPER_DEST.exists():
        try:
            existing_digest = hashlib.sha256(_WRAPPER_DEST.read_bytes()).hexdigest()
        except OSError as exc:
            print(f"⚠️  Could not read {_WRAPPER_DEST}: {exc}")
            return 1
        new_digest = hashlib.sha256(wrapper_bytes).hexdigest()
        if existing_digest == new_digest:
            print(f"ℹ️  git_wrapper.sh already up to date at {_WRAPPER_DEST}")
        else:
            try:
                _WRAPPER_DEST.write_bytes(wrapper_bytes)
            except OSError as exc:
                print(f"⚠️  Could not write {_WRAPPER_DEST}: {exc}")
                return 1
            print(f"✅ Updated git_wrapper.sh at {_WRAPPER_DEST}")
    else:
        try:
            _WRAPPER_DEST.write_bytes(wrapper_bytes)
        except OSError as exc:
            print(f"⚠️  Could not write {_WRAPPER_DEST}: {exc}")
            return 1
        print(f"✅ Installed git_wrapper.sh to {_WRAPPER_DEST}")

    # Always ensure executable bit is set, even if content was already current.
    try:
        _WRAPPER_DEST.chmod(
            _WRAPPER_DEST.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
    except OSError as exc:
        print(f"⚠️  Could not set executable bit on {_WRAPPER_DEST}: {exc}")
        return 1

    alias_block = (
        f"\n{DEEP_HOOK_MARKER}\n"
        'alias git="$HOME/.slopmop/bin/git_wrapper.sh"\n'
        f"{DEEP_HOOK_END_MARKER}\n"
    )

    for rc_file in _get_deep_rc_files():
        if rc_file.exists() and DEEP_HOOK_MARKER in rc_file.read_text():
            print(f"ℹ️  Shell alias already present in {rc_file}")
            continue
        with rc_file.open("a") as f:
            f.write(alias_block)
        print(f"✅ Added git alias to {rc_file}")
        print(f"   Run: source {rc_file}")

    return 0


def _deep_hooks_uninstall() -> int:
    """Remove git_wrapper.sh from ~/.slopmop/bin/ and strip alias from rc files."""
    # Clean RC files first, so any failures don't leave a dangling alias pointing to deleted wrapper
    for rc_file in _deep_rc_candidates():
        if not rc_file.exists():
            continue
        content = rc_file.read_text()
        if DEEP_HOOK_MARKER not in content:
            continue
        start_idx = content.find(DEEP_HOOK_MARKER)
        end_idx = content.find(DEEP_HOOK_END_MARKER, start_idx)
        if end_idx == -1:
            print(
                f"⚠️  {rc_file}: start marker found but end marker missing — "
                "skipping to avoid data loss"
            )
            continue
        lines = content.splitlines(keepends=True)
        new_lines: list[str] = []
        in_block = False
        for line in lines:
            if DEEP_HOOK_MARKER in line:
                in_block = True
                continue
            if DEEP_HOOK_END_MARKER in line:
                in_block = False
                continue
            if not in_block:
                new_lines.append(line)
        rc_file.write_text("".join(new_lines))
        print(f"✅ Removed git alias from {rc_file}")

    # Remove wrapper last, after RC files are clean
    if _WRAPPER_DEST.exists():
        _WRAPPER_DEST.unlink()
        print(f"✅ Removed {_WRAPPER_DEST}")
    else:
        print(f"ℹ️  git_wrapper.sh not found at {_WRAPPER_DEST}")

    return 0


def cmd_commit_hooks(args: argparse.Namespace) -> int:
    """Handle the commit-hooks command."""
    project_root = Path(args.project_root).resolve()

    if not args.hooks_action:
        args.hooks_action = "status"

    is_deep = getattr(args, "deep", False)
    hooks_dir = _get_git_hooks_dir(project_root)

    # Deep uninstall is machine-level; allow it even outside a git repo.
    if not hooks_dir and is_deep and args.hooks_action == "uninstall":
        return _deep_hooks_uninstall()

    if not hooks_dir:
        print(f"❌ Not a git repository: {project_root}")
        print("   Initialize git first: git init")
        return 1

    if args.hooks_action == "status":
        return _hooks_status(project_root, hooks_dir)
    elif args.hooks_action == "install":
        result = _hooks_install(project_root, hooks_dir, args.hook_verb)
        if is_deep:
            deep_result = _deep_hooks_install(confirm=getattr(args, "confirm", ""))
            result = max(result, deep_result)
        return result
    elif args.hooks_action == "uninstall":
        if is_deep:
            _deep_hooks_uninstall()
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
