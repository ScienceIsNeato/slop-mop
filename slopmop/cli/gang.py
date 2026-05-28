"""sm gang — press-gang agents into seamanship.

Seizes forbidden instinct commands (``pytest``, ``gh run``, ``mypy``, etc.)
and conscripts them into their correct ``sm`` equivalents, logging a message
on each intercept.  No command volunteers; each is pressed into service at
the shell level, machine-wide — like a press-gang seizing sailors and
forcing them aboard.

Historical note: a press gang was a squad authorized by the Royal Navy to
forcibly conscript ("press") men into naval service against their will.
``sm gang press`` does the same to raw tool commands; ``sm gang discharge``
releases them — the naval term for dismissal from service.

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
import subprocess
import tempfile
from pathlib import Path

from slopmop.data.command_mapping import COMMAND_MAPPING, CommandMap

# ── Constants ─────────────────────────────────────────────────────────────────

GANG_MARKER = "# BEGIN sm-gang"
GANG_END_MARKER = "# END sm-gang"

# Migration: old marker written by sm mutinize (before rename to sm gang)
_MUTINIZE_MARKER = "# BEGIN sm-mutinize"
_MUTINIZE_END_MARKER = "# END sm-mutinize"

# Backward-compat: old "deep hooks" marker written by commit-hooks --deep
_LEGACY_MARKER = "# MANAGED BY SLOP-MOP DEEP"
_LEGACY_END_MARKER = "# END SLOP-MOP DEEP"

GANG_CONFIRM_PHRASE = "I understand this aliases commands system-wide on this machine"

_SLOPMOP_HOME = Path.home() / ".slopmop"
_ALIASES_DEST = _SLOPMOP_HOME / "aliases.sh"
_WRAPPER_DEST = _SLOPMOP_HOME / "bin" / "git_wrapper.sh"


# ── Shell alias generation ────────────────────────────────────────────────────


def _escape(s: str) -> str:
    """Escape single quotes and backslashes for embedding in a printf string."""
    return s.replace("\\", "\\\\").replace("'", "'\\''")


def _msg_printf(forbidden: str, indent: int, suggestion: str = "") -> str:
    """Return a printf line that shows the intercept message."""
    spaces = " " * indent
    msg = (
        f"\\033[1m[slop-mop]\\033[0m \\033[31m\\xe2\\x9b\\x94 {_escape(forbidden)} blocked\\033[0m\\n"
        f"  Stop. File a barnacle: sm barnacle\\n"
        f"  Tell the human what you were doing and wait."
    )
    if suggestion:
        msg += f"\\n  {suggestion}"
    return f"{spaces}printf " f"'{msg}\\n' >&2"


def _gen_slopmop_guard(lines: list[str]) -> None:
    """Append a helper that returns true only when inside a slop-mop repo."""
    lines += [
        "_sm_in_slopmop_repo() {",
        '    local _d="$PWD"',
        '    while [[ "$_d" != "/" ]]; do',
        '        [[ -d "$_d/.slopmop" ]] && return 0',
        '        _d="$(dirname "$_d")"',
        "    done",
        "    return 1",
        "}",
        '[[ -n "${BASH_VERSION:-}" ]] && export -f _sm_in_slopmop_repo',
        "",
    ]


def _gen_function_blocks(lines: list[str]) -> None:
    """Append bash function wrappers for 'function' intercept type entries."""
    seen_cmds: set[str] = set()
    for entry in COMMAND_MAPPING:
        if entry.intercept_type != "function":
            continue
        cmd = entry.forbidden.split()[0]
        if cmd in seen_cmds:
            continue
        seen_cmds.add(cmd)
        lines.append(f"{cmd}() {{")
        lines.append(
            f'    command -v sm &>/dev/null || {{ command {cmd} "$@"; return; }}'
        )
        lines.append(f'    _sm_in_slopmop_repo || {{ command {cmd} "$@"; return; }}')
        lines.append(_msg_printf(cmd, indent=4))
        lines.append("    return 1")
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
            f'    command -v sm &>/dev/null || {{ command {wrapper} "$@"; return; }}',
            f'    _sm_in_slopmop_repo || {{ command {wrapper} "$@"; return; }}',
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
            lines.append(
                _msg_printf(
                    f"{wrapper} {' '.join(entry.subcommands)}",
                    indent=12,
                    suggestion=entry.suggestion,
                )
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
    lines += [
        "npx() {",
        '    command -v sm &>/dev/null || { command npx "$@"; return; }',
        '    _sm_in_slopmop_repo || { command npx "$@"; return; }',
        '    case "${1:-}" in',
    ]
    for entry in npx_entries:
        tool = entry.subcommands[0] if entry.subcommands else ""
        if not tool:
            continue
        lines.append(f"        {tool})")
        lines.append(_msg_printf(f"npx {tool}", indent=12, suggestion=entry.suggestion))
        lines.append("            return 1")
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
        f"# Generated by sm gang v{version} — DO NOT EDIT",
        f'# Regenerate: sm gang press --confirm "{GANG_CONFIRM_PHRASE}"',
        "#",
        "# To remove ALL intercepts without relying on 'sm gang discharge':",
        "#   for f in ~/.zshrc ~/.zprofile ~/.bashrc ~/.bash_profile; do",
        "#     sed -i.bak '/# BEGIN sm-gang/,/# END sm-gang/d' \"$f\" 2>/dev/null || true",
        "#   done",
        "#   rm -f ~/.slopmop/aliases.sh ~/.slopmop/bin/git_wrapper.sh",
        "",
    ]

    _gen_slopmop_guard(lines)
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


def _validate_bash_syntax(content: bytes) -> tuple[bool, str]:
    """Run bash -n on content to catch syntax errors before writing.

    Returns (ok, error_message). Skips check if bash is unavailable.
    """
    with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as f:
        f.write(content)
        tmp = Path(f.name)
    try:
        result = subprocess.run(
            ["bash", "-n", str(tmp)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False, result.stderr.strip()
        return True, ""
    except FileNotFoundError:
        return True, ""
    finally:
        tmp.unlink(missing_ok=True)


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
    """All rc files that might contain a gang or legacy deep-hooks block."""
    home = Path.home()
    return [
        home / ".zshrc",
        home / ".zprofile",
        home / ".bashrc",
        home / ".bash_profile",
    ]


def _rc_has_gang(path: Path) -> bool:
    """Return True if the rc file contains the gang marker."""
    try:
        return GANG_MARKER in path.read_text(encoding="utf-8", errors="replace")
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
    print("⚠️  sm gang requires explicit confirmation")
    print("=" * 60)
    print()
    print("This will write shell function intercepts to your rc file:")
    print()
    print('  source "$HOME/.slopmop/aliases.sh"')
    print('  alias git="$HOME/.slopmop/bin/git_wrapper.sh"')
    print()
    print("What that means for you:")
    print("  • Commands are intercepted in ALL repositories on this machine,")
    print("    not just slop-mop repos — your other projects are affected")
    print("  • Each intercepted command logs a message and runs sm instead")
    print("  • If slopmop is later uninstalled, intercepts fall through gracefully")
    print("  • git commit --no-verify is blocked in ALL repos (git wrapper)")
    print("  • Other users on this machine are NOT affected")
    print("  • To remove: sm gang discharge")
    print("  • Emergency removal without sm:")
    print("      for f in ~/.zshrc ~/.zprofile ~/.bashrc ~/.bash_profile; do")
    print(
        "        sed -i.bak '/# BEGIN sm-gang/,/# END sm-gang/d' \"$f\" 2>/dev/null || true"
    )
    print("      done")
    print("      rm -f ~/.slopmop/aliases.sh ~/.slopmop/bin/git_wrapper.sh")
    print()
    print("To proceed, add this flag exactly:")
    print(f'   --confirm "{GANG_CONFIRM_PHRASE}"')
    print()


def _wire_rc_files(rc_block_body: str) -> int:
    """Append the gang marker block to each detected rc file; return error count."""
    errors = 0
    for rc_file in _get_rc_files():
        if _rc_has_gang(rc_file):
            print(f"ℹ️  Shell source already present in {rc_file}")
            continue
        # Migrate: strip old sm-mutinize block before writing new sm-gang block
        if rc_file.exists() and _MUTINIZE_MARKER in rc_file.read_text(
            encoding="utf-8", errors="replace"
        ):
            try:
                content = rc_file.read_text(encoding="utf-8", errors="replace")
                content = _strip_marker_block(
                    content, _MUTINIZE_MARKER, _MUTINIZE_END_MARKER
                )
                rc_file.write_text(content, encoding="utf-8")
                print(f"ℹ️  Migrated old sm-mutinize block in {rc_file}")
            except OSError as exc:
                print(f"⚠️  Could not migrate old block in {rc_file}: {exc}")
                errors += 1
                continue
        # Prepend \n only if the file doesn't already end with one, so the
        # GANG_MARKER is never concatenated onto the preceding line (which
        # would cause _strip_marker_block to silently eat that line on uninstall).
        try:
            existing_text = (
                rc_file.read_text(encoding="utf-8", errors="replace")
                if rc_file.exists()
                else ""
            )
        except OSError:
            existing_text = ""
        separator = "\n" if existing_text and not existing_text.endswith("\n") else ""
        rc_block = separator + rc_block_body
        try:
            with rc_file.open("a") as f:
                f.write(rc_block)
        except OSError as exc:
            print(f"⚠️  Could not write to {rc_file}: {exc}")
            errors += 1
            continue
        print(f"✅ Added aliases to {rc_file}")
        print(f"   Run: source {rc_file}")
    return errors


def _gang_press(confirm: str = "") -> int:
    """Press aliases.sh + git_wrapper.sh and wire them in shell rc files."""
    if confirm != GANG_CONFIRM_PHRASE:
        _show_confirm_warning()
        return 1

    from slopmop import __version__

    shell = os.environ.get("SHELL", "")
    if "fish" in shell:
        print(
            "⚠️  Fish shell detected. sm gang installs bash/zsh intercepts only — "
            "fish sessions will not be press-ganged. "
            "Run 'sm gang press' from bash or zsh to wire those shells."
        )

    errors = 0

    # 1. Generate and write aliases.sh
    aliases_content = _generate_aliases_sh(__version__)
    ok, err = _validate_bash_syntax(aliases_content)
    if not ok:
        print(f"⚠️  Generated aliases.sh failed bash syntax check — aborting: {err}")
        return 1
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
            errors += 1

    # 2. Press git_wrapper.sh
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
    rc_block_body = (
        f"{GANG_MARKER}\n"
        "\n"
        'alias git="$HOME/.slopmop/bin/git_wrapper.sh"\n'
        'source "$HOME/.slopmop/aliases.sh"\n'
        f"{GANG_END_MARKER}\n"
    )
    errors += _wire_rc_files(rc_block_body)

    return 1 if errors else 0


def _gang_discharge() -> int:
    """Remove aliases.sh, git_wrapper.sh, and all marker blocks from rc files."""
    errors = 0

    # Strip marker blocks from rc files first (both new and legacy markers)
    for rc_file in _rc_candidates():
        if not rc_file.exists():
            continue
        try:
            content = rc_file.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"⚠️  {rc_file}: could not read — {exc}")
            errors += 1
            continue
        original = content
        if GANG_MARKER in content:
            content = _strip_marker_block(content, GANG_MARKER, GANG_END_MARKER)
        if _MUTINIZE_MARKER in content:
            content = _strip_marker_block(
                content, _MUTINIZE_MARKER, _MUTINIZE_END_MARKER
            )
        if _LEGACY_MARKER in content:
            content = _strip_marker_block(content, _LEGACY_MARKER, _LEGACY_END_MARKER)
        if content != original:
            try:
                rc_file.write_text(content, encoding="utf-8")
                print(f"✅ Removed gang block from {rc_file}")
            except OSError as exc:
                print(f"⚠️  {rc_file}: could not write — {exc}")
                errors += 1

    # Remove aliases.sh
    if _ALIASES_DEST.exists():
        try:
            _ALIASES_DEST.unlink()
            print(f"✅ Removed {_ALIASES_DEST}")
        except OSError as exc:
            print(f"⚠️  Could not remove {_ALIASES_DEST}: {exc}")
            errors += 1
    else:
        print(f"ℹ️  {_ALIASES_DEST} not found (nothing to remove)")

    # Remove git_wrapper.sh last
    if _WRAPPER_DEST.exists():
        try:
            _WRAPPER_DEST.unlink()
            print(f"✅ Removed {_WRAPPER_DEST}")
        except OSError as exc:
            print(f"⚠️  Could not remove {_WRAPPER_DEST}: {exc}")
            errors += 1
    else:
        print(f"ℹ️  {_WRAPPER_DEST} not found (nothing to remove)")

    return 1 if errors else 0


def _gang_status() -> int:
    """Show what gang components are installed."""
    print()
    print("⚓ sm gang status")
    print("=" * 60)
    print()

    # aliases.sh
    if _ALIASES_DEST.exists():
        print(f"  ✅ aliases.sh installed at {_ALIASES_DEST}")
    else:
        print(f"  ✗  aliases.sh not installed (run: sm gang press)")

    # git_wrapper.sh
    if _WRAPPER_DEST.exists():
        print(f"  ✅ git_wrapper.sh installed at {_WRAPPER_DEST}")
    else:
        print(f"  ✗  git_wrapper.sh not installed")

    # rc file wiring
    wired_new = [str(p) for p in _rc_candidates() if _rc_has_gang(p)]
    wired_legacy = [str(p) for p in _rc_candidates() if _rc_has_legacy(p)]

    if wired_new:
        print(f"  ✅ Shell source active in: {', '.join(wired_new)}")
    else:
        print("  ✗  No shell source found in rc files")

    if wired_legacy:
        print(
            f"  ⚠️  Legacy deep-hooks block still present in: {', '.join(wired_legacy)}"
        )
        print("      Run: sm gang discharge && sm gang press to migrate")

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
    print("  sm gang press      # install intercepts (requires --confirm)")
    print("  sm gang discharge  # remove all artifacts")
    print("  sm gang list       # show active intercept counts")
    print()
    return 0


def _gang_list() -> int:
    """Print a summary of active intercept counts."""
    fn_cmds = {
        e.forbidden.split()[0]
        for e in COMMAND_MAPPING
        if e.intercept_type == "function"
    }
    sub_wrappers = {
        e.wrapper_command for e in COMMAND_MAPPING if e.intercept_type == "subcommand"
    }
    npx_count = sum(1 for e in COMMAND_MAPPING if e.intercept_type == "npx")

    print()
    print("⚓ sm gang — active intercepts")
    print("=" * 40)
    print()
    print(f"  {len(fn_cmds)} command intercept(s)")
    print(f"  {len(sub_wrappers)} subcommand wrapper(s)")
    print(f"  {npx_count} npx intercept(s)")
    print()
    print("Commands:")
    print("  sm gang press      # install intercepts (requires --confirm)")
    print("  sm gang discharge  # remove all artifacts")
    print("  sm gang status     # check installation")
    print()
    print("  Emergency removal without sm:")
    print("    for f in ~/.zshrc ~/.zprofile ~/.bashrc ~/.bash_profile; do")
    print(
        "      sed -i.bak '/# BEGIN sm-gang/,/# END sm-gang/d' \"$f\" 2>/dev/null || true"
    )
    print("    done")
    print("    rm -f ~/.slopmop/aliases.sh ~/.slopmop/bin/git_wrapper.sh")
    print()
    return 0


# ── Public entry point ────────────────────────────────────────────────────────


def cmd_gang(args: argparse.Namespace) -> int:
    """Handle the ``sm gang`` command."""
    action = getattr(args, "gang_action", None) or "status"

    if action == "press":
        return _gang_press(confirm=getattr(args, "confirm", ""))
    elif action == "discharge":
        return _gang_discharge()
    elif action == "status":
        return _gang_status()
    elif action == "list":
        return _gang_list()
    else:
        print(f"❌ Unknown gang action: {action}")
        return 1
