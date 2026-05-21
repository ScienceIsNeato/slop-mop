"""sm mutinize — free agents from instinct commands, redirect to seamanship.

Installs shell function intercepts (``~/.slopmop/aliases.sh``) that redirect
forbidden instinct commands (``pytest``, ``gh run``, ``mypy``, etc.) to their
correct ``sm`` equivalents, logging a message on each intercept.

Also absorbs the former ``sm commit-hooks install --deep`` functionality:
installs ``git_wrapper.sh`` to ``~/.slopmop/bin/`` and wires the shell alias.

All writes are SHA256-guarded: files are only touched when content changes.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.resources
import os
import stat
from pathlib import Path

from slopmop.data.command_mapping import COMMAND_MAPPING, CommandMap

# ── Constants ─────────────────────────────────────────────────────────────────

MUTINIZE_MARKER = "# BEGIN sm-mutinize"
MUTINIZE_END_MARKER = "# END sm-mutinize"

# Backward-compat: old "deep hooks" marker written by commit-hooks --deep
_LEGACY_MARKER = "# MANAGED BY SLOP-MOP DEEP"
_LEGACY_END_MARKER = "# END SLOP-MOP DEEP"

MUTINIZE_CONFIRM_PHRASE = (
    "I understand this aliases commands system-wide on this machine"
)

_SLOPMOP_HOME = Path.home() / ".slopmop"
_ALIASES_DEST = _SLOPMOP_HOME / "aliases.sh"
_WRAPPER_DEST = _SLOPMOP_HOME / "bin" / "git_wrapper.sh"


# ── Shell alias generation ────────────────────────────────────────────────────


def _escape(s: str) -> str:
    """Escape single quotes and backslashes for embedding in a printf string."""
    return s.replace("\\", "\\\\").replace("'", "'\\''")


def _msg_printf(entry: CommandMap, indent: int) -> str:
    """Return a printf line that shows the intercept message."""
    spaces = " " * indent
    sm = entry.sm_command or "see suggestion below"
    return (
        f"{spaces}printf "
        f"'\\033[1m[slop-mop]\\033[0m "
        f"\\033[33m{_escape(entry.forbidden)}\\033[0m"
        f" \\xe2\\x86\\x92 "
        f"\\033[32m{_escape(sm)}\\033[0m"
        f"  ({_escape(entry.category)}: {_escape(entry.reason)})\\n' >&2"
    )


def _gen_function_blocks(lines: list[str]) -> None:
    """Append bash function wrappers for 'function' intercept type entries."""
    fn_groups: dict[str, list[CommandMap]] = {}
    for entry in COMMAND_MAPPING:
        if entry.intercept_type != "function":
            continue
        cmd = entry.forbidden.split()[0]
        fn_groups.setdefault(cmd, []).append(entry)

    for cmd, entries in fn_groups.items():
        flagged = [e for e in entries if e.flag_trigger]
        plain = [e for e in entries if not e.flag_trigger]

        lines.append(f"{cmd}() {{")
        if flagged:
            for i, entry in enumerate(flagged):
                kw = "if" if i == 0 else "elif"
                lines.append(f'    {kw} [[ " $* " == *"{entry.flag_trigger}"* ]]; then')
                lines.append(_msg_printf(entry, indent=8))
                lines.append(f"        {entry.sm_command}")
            lines.append("    else")
            for entry in plain:
                lines.append(_msg_printf(entry, indent=8))
                lines.append(f"        {entry.sm_command}")
            lines.append("    fi")
        else:
            for entry in plain:
                lines.append(_msg_printf(entry, indent=4))
                lines.append(f"    {entry.sm_command}")
        lines += ["}", '[[ -n "${BASH_VERSION:-}" ]] && export -f ' + cmd, ""]


def _gen_subcommand_blocks(lines: list[str]) -> None:
    """Append bash case-statement wrappers for 'subcommand' intercept type entries."""
    sub_groups: dict[str, list[CommandMap]] = {}
    for entry in COMMAND_MAPPING:
        if entry.intercept_type != "subcommand":
            continue
        sub_groups.setdefault(entry.wrapper_command, []).append(entry)

    for wrapper, entries in sub_groups.items():
        lines += [
            f"{wrapper}() {{",
            '    local _sub="${1:-}" _sub2="${2:-}"',
            '    case "$_sub $_sub2" in',
        ]
        seen_patterns: set[tuple[str, ...]] = set()
        for entry in entries:
            if entry.subcommands in seen_patterns:
                continue
            seen_patterns.add(entry.subcommands)
            pattern = f'"{" ".join(entry.subcommands)}"'
            lines.append(f"        {pattern})")
            lines.append(_msg_printf(entry, indent=12))
            if entry.redirect and entry.sm_command:
                lines.append(f"            {entry.sm_command}")
            else:
                if entry.suggestion:
                    lines.append(
                        f"            printf '  Use: {_escape(entry.suggestion)}\\n' >&2"
                    )
                lines.append("            return 1")
            lines.append("            ;;")

        lines += [
            "        *)",
            f'            command {wrapper} "$@"',
            "            ;;",
            "    esac",
            "}",
            f'[[ -n "${{BASH_VERSION:-}}" ]] && export -f {wrapper}',
            "",
        ]


def _gen_npx_block(lines: list[str]) -> None:
    """Append the npx case-statement wrapper for 'npx' intercept type entries."""
    npx_entries = [e for e in COMMAND_MAPPING if e.intercept_type == "npx"]
    if not npx_entries:
        return
    lines += ["npx() {", '    case "${1:-}" in']
    for entry in npx_entries:
        tool = entry.subcommands[0] if entry.subcommands else ""
        if not tool:
            continue
        lines.append(f"        {tool})")
        lines.append(_msg_printf(entry, indent=12))
        lines.append(f"            {entry.sm_command}")
        lines.append("            ;;")

    lines += [
        "        *)",
        '            command npx "$@"',
        "            ;;",
        "    esac",
        "}",
        '[[ -n "${BASH_VERSION:-}" ]] && export -f npx',
        "",
    ]


def _generate_aliases_sh(version: str) -> bytes:
    """Generate ``~/.slopmop/aliases.sh`` content from ``COMMAND_MAPPING``."""
    lines: list[str] = [
        "#!/usr/bin/env bash",
        f"# Generated by sm mutinize v{version} — DO NOT EDIT",
        f'# Regenerate: sm mutinize install --confirm "{MUTINIZE_CONFIRM_PHRASE}"',
        "# To bypass a specific intercept: use 'command <tool> <args>'",
        "",
    ]

    _gen_function_blocks(lines)
    _gen_subcommand_blocks(lines)
    _gen_npx_block(lines)
    return "\n".join(lines).encode("utf-8")


# ── File write helpers ────────────────────────────────────────────────────────


def _write_if_changed(path: Path, content: bytes) -> tuple[bool, str]:
    """Write ``content`` to ``path`` only if SHA256 differs.

    Returns ``(was_written, status_message)``.
    """
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as exc:
            return False, f"⚠️  Could not read {path}: {exc}"
        if hashlib.sha256(existing).hexdigest() == hashlib.sha256(content).hexdigest():
            return False, f"ℹ️  Already up to date: {path}"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_bytes(content)
    except OSError as exc:
        return False, f"⚠️  Could not write {path}: {exc}"
    return True, f"✅ Written: {path}"


# ── RC file helpers ───────────────────────────────────────────────────────────


def _get_rc_files() -> list[Path]:
    """Return shell rc files to update, based on current shell."""
    shell = os.environ.get("SHELL", "")
    home = Path.home()
    if "zsh" in shell:
        candidates = [home / ".zshrc"]
    elif "bash" in shell:
        candidates = [home / ".bashrc", home / ".bash_profile"]
    else:
        candidates = [home / ".zshrc", home / ".bashrc"]
    return [p for p in candidates if p.exists()] or candidates[:1]


def _rc_candidates() -> list[Path]:
    """All rc files that might contain a mutinize or legacy deep-hooks block."""
    home = Path.home()
    return [
        home / ".zshrc",
        home / ".zprofile",
        home / ".bashrc",
        home / ".bash_profile",
    ]


def _rc_has_mutinize(path: Path) -> bool:
    """Return True if the rc file contains the mutinize marker."""
    try:
        return MUTINIZE_MARKER in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _rc_has_legacy(path: Path) -> bool:
    """Return True if the rc file contains the old deep-hooks marker."""
    try:
        return _LEGACY_MARKER in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _strip_marker_block(content: str, start: str, end: str) -> str:
    """Remove a ``start`` … ``end`` marker block from ``content``.

    If the start marker is present but the end marker is absent (corrupted rc),
    the original content is returned unchanged rather than silently dropping
    everything after the start.
    """
    lines = content.splitlines(keepends=True)
    result: list[str] = []
    in_block = False
    found_end = False
    for line in lines:
        if start in line:
            in_block = True
            continue
        if end in line:
            in_block = False
            found_end = True
            continue
        if not in_block:
            result.append(line)
    if in_block and not found_end:
        return content
    return "".join(result)


# ── Subcommand handlers ───────────────────────────────────────────────────────


def _show_confirm_warning() -> None:
    print()
    print("⚠️  sm mutinize requires explicit confirmation")
    print("=" * 60)
    print()
    print("This will write shell function intercepts to your rc file:")
    print()
    print('  source "$HOME/.slopmop/aliases.sh"')
    print('  alias git="$HOME/.slopmop/bin/git_wrapper.sh"')
    print()
    print("What that means for you:")
    print("  • Commands like pytest, mypy, gh run are intercepted system-wide")
    print("  • Each intercepted command logs a message and runs sm instead")
    print("  • To bypass any intercept: use 'command <tool> <args>'")
    print("  • git commit --no-verify is blocked in ALL repos (git wrapper)")
    print("  • Other users on this machine are NOT affected")
    print("  • The aliases persist after slopmop is uninstalled until you run:")
    print("    sm mutinize uninstall")
    print()
    print("To proceed, add this flag exactly:")
    print(f'   --confirm "{MUTINIZE_CONFIRM_PHRASE}"')
    print()


def _mutinize_install(confirm: str = "") -> int:
    """Install aliases.sh + git_wrapper.sh and wire them in shell rc files."""
    if confirm != MUTINIZE_CONFIRM_PHRASE:
        _show_confirm_warning()
        return 1

    from slopmop import __version__

    errors = 0

    # 1. Generate and write aliases.sh
    aliases_content = _generate_aliases_sh(__version__)
    written, msg = _write_if_changed(_ALIASES_DEST, aliases_content)
    print(msg)
    if "⚠️" in msg:
        errors += 1
    if written:
        try:
            mode = _ALIASES_DEST.stat().st_mode
            _ALIASES_DEST.chmod(mode | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        except OSError as exc:
            print(f"⚠️  Could not set permissions on {_ALIASES_DEST}: {exc}")

    # 2. Install git_wrapper.sh
    try:
        wrapper_bytes = (
            importlib.resources.files("slopmop.data")
            .joinpath("git_wrapper.sh")
            .read_bytes()
        )
    except Exception as exc:
        print(f"⚠️  Could not load git_wrapper.sh from package: {exc}")
        return 1

    written, msg = _write_if_changed(_WRAPPER_DEST, wrapper_bytes)
    print(msg)
    if "⚠️" in msg:
        errors += 1
    if _WRAPPER_DEST.exists():
        try:
            mode = _WRAPPER_DEST.stat().st_mode
            _WRAPPER_DEST.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError as exc:
            print(f"⚠️  Could not set executable bit on {_WRAPPER_DEST}: {exc}")
            errors += 1

    # 3. Wire rc files
    rc_block = (
        f"\n{MUTINIZE_MARKER}\n"
        'alias git="$HOME/.slopmop/bin/git_wrapper.sh"\n'
        'source "$HOME/.slopmop/aliases.sh"\n'
        f"{MUTINIZE_END_MARKER}\n"
    )
    for rc_file in _get_rc_files():
        if _rc_has_mutinize(rc_file):
            print(f"ℹ️  Shell source already present in {rc_file}")
            continue
        try:
            with rc_file.open("a") as f:
                f.write(rc_block)
        except OSError as exc:
            print(f"⚠️  Could not write to {rc_file}: {exc}")
            errors += 1
            continue
        print(f"✅ Added aliases to {rc_file}")
        print(f"   Run: source {rc_file}")

    return 1 if errors else 0


def _mutinize_uninstall() -> int:
    """Remove aliases.sh, git_wrapper.sh, and all marker blocks from rc files."""
    # Strip marker blocks from rc files first (both new and legacy markers)
    for rc_file in _rc_candidates():
        if not rc_file.exists():
            continue
        try:
            content = rc_file.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"⚠️  {rc_file}: could not read — {exc}")
            continue
        original = content
        if MUTINIZE_MARKER in content:
            content = _strip_marker_block(content, MUTINIZE_MARKER, MUTINIZE_END_MARKER)
        if _LEGACY_MARKER in content:
            content = _strip_marker_block(content, _LEGACY_MARKER, _LEGACY_END_MARKER)
        if content != original:
            try:
                rc_file.write_text(content, encoding="utf-8")
                print(f"✅ Removed mutinize block from {rc_file}")
            except OSError as exc:
                print(f"⚠️  {rc_file}: could not write — {exc}")

    # Remove aliases.sh
    if _ALIASES_DEST.exists():
        _ALIASES_DEST.unlink()
        print(f"✅ Removed {_ALIASES_DEST}")
    else:
        print(f"ℹ️  {_ALIASES_DEST} not found (nothing to remove)")

    # Remove git_wrapper.sh last
    if _WRAPPER_DEST.exists():
        _WRAPPER_DEST.unlink()
        print(f"✅ Removed {_WRAPPER_DEST}")
    else:
        print(f"ℹ️  {_WRAPPER_DEST} not found (nothing to remove)")

    return 0


def _mutinize_status() -> int:
    """Show what mutinize components are installed."""
    print()
    print("⚓ sm mutinize status")
    print("=" * 60)
    print()

    # aliases.sh
    if _ALIASES_DEST.exists():
        print(f"  ✅ aliases.sh installed at {_ALIASES_DEST}")
    else:
        print(f"  ✗  aliases.sh not installed (run: sm mutinize install)")

    # git_wrapper.sh
    if _WRAPPER_DEST.exists():
        print(f"  ✅ git_wrapper.sh installed at {_WRAPPER_DEST}")
    else:
        print(f"  ✗  git_wrapper.sh not installed")

    # rc file wiring
    wired_new = [str(p) for p in _rc_candidates() if _rc_has_mutinize(p)]
    wired_legacy = [str(p) for p in _rc_candidates() if _rc_has_legacy(p)]

    if wired_new:
        print(f"  ✅ Shell source active in: {', '.join(wired_new)}")
    else:
        print("  ✗  No shell source found in rc files")

    if wired_legacy:
        print(
            f"  ⚠️  Legacy deep-hooks block still present in: {', '.join(wired_legacy)}"
        )
        print("      Run: sm mutinize uninstall && sm mutinize install to migrate")

    # intercept summary
    print()
    fn_count = sum(1 for e in COMMAND_MAPPING if e.intercept_type == "function")
    sub_count = len(
        {e.wrapper_command for e in COMMAND_MAPPING if e.intercept_type == "subcommand"}
    )
    npx_count = sum(1 for e in COMMAND_MAPPING if e.intercept_type == "npx")
    print(
        f"  Mapping: {fn_count} command functions, "
        f"{sub_count} subcommand wrapper(s), "
        f"{npx_count} npx intercepts"
    )
    print()
    print("Commands:")
    print("  sm mutinize install    # install (requires --confirm)")
    print("  sm mutinize uninstall  # remove all artifacts")
    print("  sm mutinize list       # show the full mapping table")
    print()
    return 0


def _mutinize_list() -> int:
    """Print the command mapping table."""
    # Group by category for display
    categories: dict[str, list[CommandMap]] = {}
    for entry in COMMAND_MAPPING:
        categories.setdefault(entry.category, []).append(entry)

    print()
    print("⚓ sm mutinize — command intercept mapping")
    print("=" * 72)
    print(f"  {'Forbidden command':<30}  {'sm replacement':<35}  Redirect")
    print("  " + "-" * 68)
    for category, entries in categories.items():
        print(f"\n  [{category}]")
        for entry in entries:
            sm = (
                entry.sm_command
                if entry.sm_command
                else f"→ {entry.suggestion or '(block)'}"
            )
            redirect = "✓" if entry.redirect and entry.sm_command else "✗ (block)"
            print(f"  {entry.forbidden:<30}  {sm:<35}  {redirect}")
    print()
    print("  To bypass any intercept: command <tool> <args>")
    print()
    return 0


# ── Public entry point ────────────────────────────────────────────────────────


def cmd_mutinize(args: argparse.Namespace) -> int:
    """Handle the ``sm mutinize`` command."""
    action = getattr(args, "mutinize_action", None) or "status"

    if action == "install":
        return _mutinize_install(confirm=getattr(args, "confirm", ""))
    elif action == "uninstall":
        return _mutinize_uninstall()
    elif action == "status":
        return _mutinize_status()
    elif action == "list":
        return _mutinize_list()
    else:
        print(f"❌ Unknown mutinize action: {action}")
        return 1
