"""Status command for slop-mop CLI.

Project dashboard — shows configuration, gate inventory with
historical results, and hook installation status.  Does NOT run any
gates; use ``sm swab`` or ``sm scour`` for that.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from slopmop.checks import ensure_checks_registered
from slopmop.checks.base import GateCategory, GateLevel
from slopmop.core.registry import get_registry
from slopmop.reporting.timings import TimingStats, load_timings

# ── Helpers ──────────────────────────────────────────────────────

# Category display order — controls section ordering in the inventory
_CATEGORY_ORDER = [
    "overconfidence",
    "deceptiveness",
    "laziness",
    "myopia",
    "general",
]

# Marker written into slop-mop-managed git hooks.
# Import the canonical marker from hooks.py to keep in sync.
from slopmop.cli.hooks import SB_HOOK_MARKER as _SB_HOOK_MARKER


def _get_category_display(category_key: str) -> Tuple[str, str]:
    """Get emoji and display name for a category key."""
    for cat in GateCategory:
        if cat.key == category_key:
            return cat.emoji, cat.display_name
    return "❓", category_key.title()


def _find_other_aliases(
    gate: str, aliases: Dict[str, List[str]], current_level: str
) -> List[str]:
    """Find aliases that include a gate, excluding the current level."""
    return [
        alias
        for alias, gates in aliases.items()
        if gate in gates and alias != current_level
    ]


# ── Section: Config Summary ─────────────────────────────────────


def _print_config_summary(
    root: Path,
    config: Dict[str, Any],
    swab_count: int,
    scour_count: int,
    disabled: List[str],
) -> None:
    """Print project configuration overview."""
    from slopmop.checks.base import count_source_scope
    from slopmop.reporting import print_project_header

    print_project_header(str(root))

    config_file = root / ".sb_config.json"
    if config_file.exists():
        print(f"📄 Config: {config_file}")
    else:
        print("📄 Config: none (using defaults)")

    swabbing_time = config.get("swabbing_time")
    if isinstance(swabbing_time, (int, float)) and swabbing_time > 0:
        print(f"⏱️  Time budget: {int(swabbing_time)}s")

    print(f"🔍 Gates: {swab_count} swab · {scour_count} scour-only")

    # Project scope — lightweight file/LOC count
    scope = count_source_scope(str(root))
    if scope.files > 0:
        print(f"📏 Scope: {scope.format_compact()}")

    if disabled:
        print(f"🚫 Disabled: {len(disabled)} gate(s)")
        for name in sorted(disabled):
            print(f"      {name}")


# ── Section: Gate Inventory ──────────────────────────────────────


RECENT_HISTORY_HEADER = "📊 RECENT HISTORY"

# Role badges — same glyphs as ConsoleAdapter (reporting/adapters.py) so
# the dashboard inventory and the post-run summary speak the same visual
# language.  Wrench = foundation (wraps tooling), microscope = diagnostic
# (novel analysis).  Not imported to keep status.py free of adapter
# dependencies; the sibling map is keyed off the same CheckRole enum
# values so drift requires an enum change in base.py first.
_ROLE_BADGES: Dict[str, str] = {
    "foundation": "🔧 ",
    "diagnostic": "🔬 ",
}


def _format_gate_line(
    gate_name: str,
    *,
    role: str,
    in_swab: bool,
    in_scour: bool,
    is_applicable: bool,
    skip_reason: str,
    history: Optional[TimingStats],
    colors_enabled: bool,
) -> str:
    """Format a single gate line for the inventory.

    Shows role, applicability, level membership, and last-known result
    from historical timing data (no live execution).  The role badge
    answers "is this a standard-tool wrapper or slop-mop's own analysis"
    at a glance — useful when triaging which gates to disable or tune.
    """
    # Level badge
    if in_swab:
        level_tag = "swab"
    elif in_scour:
        level_tag = "scour"
    else:
        level_tag = "     "

    # Role badge — empty string for unknown (custom gates may not set it)
    role_badge = _ROLE_BADGES.get(role, "")

    # Applicability / history-based status
    if not is_applicable:
        icon = "⊘"
        suffix = f"n/a ({skip_reason})"
    elif history and history.results:
        last_result = history.results[-1]
        _RESULT_ICONS = {
            "passed": "✅",
            "failed": "❌",
            "error": "💥",
            "warned": "⚠️",
            "skipped": "⏭️",
            "not_applicable": "⊘",
        }
        icon = _RESULT_ICONS.get(last_result, "?")
        sparkline = history.sparkline(max_width=10, colors_enabled=colors_enabled)
        # Build suffix from last result + sparkline
        suffix = last_result
        if sparkline:
            suffix = f"{last_result}  {sparkline}"
    else:
        icon = "·"
        suffix = "no history"

    return f"   {icon} {role_badge}{gate_name:<28} [{level_tag}] {suffix}"


def _print_gate_inventory(
    all_gates: List[str],
    swab_gates: Set[str],
    scour_gates: Set[str],
    applicability: Dict[str, Tuple[bool, str]],
    roles: Dict[str, str],
    history: Dict[str, TimingStats],
    colors_enabled: bool,
) -> None:
    """Print the full gate inventory grouped by category.

    Shows every registered gate with role, level membership,
    applicability, and last-known result from historical timing data.
    """
    by_category: Dict[str, List[str]] = defaultdict(list)
    for gate in all_gates:
        cat_key = gate.split(":")[0]
        by_category[cat_key].append(gate)

    sorted_cats = sorted(
        by_category.keys(),
        key=lambda k: _CATEGORY_ORDER.index(k) if k in _CATEGORY_ORDER else 999,
    )

    print()
    print("📋 GATE INVENTORY")
    print("─" * 60)

    for cat_key in sorted_cats:
        gates = sorted(by_category[cat_key])
        emoji, display = _get_category_display(cat_key)
        print()
        print(f"{emoji} {display}")

        for gate in gates:
            gate_name = gate.split(":", 1)[1]
            is_app, reason = applicability.get(gate, (True, ""))

            line = _format_gate_line(
                gate_name,
                role=roles.get(gate, ""),
                in_swab=gate in swab_gates,
                in_scour=gate in scour_gates and gate not in swab_gates,
                is_applicable=is_app,
                skip_reason=reason,
                history=history.get(gate),
                colors_enabled=colors_enabled,
            )
            print(line)


# ── Section: Hook Status ────────────────────────────────────────


def _print_hooks_status(root: Path) -> None:
    """Print git hook installation status."""
    git_dir = root / ".git"
    hooks_dir = git_dir / "hooks"

    print()
    print("🪝 HOOKS")
    print("─" * 60)

    if not hooks_dir.exists():
        print("   No hooks directory found")
        print("   Install: sm commit-hooks install")
        return

    hook_types = ["pre-commit", "pre-push", "commit-msg"]
    sm_hooks: List[Tuple[str, str]] = []
    other_hooks: List[str] = []

    for hook_type in hook_types:
        hook_file = hooks_dir / hook_type
        if hook_file.exists():
            content = hook_file.read_text()
            if _SB_HOOK_MARKER in content:
                # Extract the verb from the hook script
                verb = "unknown"
                for line in content.splitlines():
                    if "sm " in line and "swab" in line:
                        verb = "swab"
                        break
                    elif "sm " in line and "scour" in line:
                        verb = "scour"
                        break
                sm_hooks.append((hook_type, verb))
            else:
                other_hooks.append(hook_type)

    if sm_hooks:
        for hook_type, verb in sm_hooks:
            print(f"   ✅ {hook_type}: {verb}")
    if other_hooks:
        for hook_type in other_hooks:
            print(f"   •  {hook_type}: non-sm hook")
    if not sm_hooks and not other_hooks:
        print("   No hooks installed")
        print("   Install: sm commit-hooks install")


# ── Section: Recent History ──────────────────────────────────────


def _print_recent_history(history: Dict[str, TimingStats]) -> None:
    """Print a compact summary of recent gate runs."""
    if not history:
        print()
        print(RECENT_HISTORY_HEADER)
        print("─" * 60)
        print("   No gate run history found. Run `sm swab` to populate.")
        return

    # Find most recent gate run across all checks
    # (TimingStats doesn't expose last_updated directly, but we
    #  can infer activity from sample counts)
    gates_with_results = {
        name: stats for name, stats in history.items() if stats.results
    }

    if not gates_with_results:
        print()
        print(RECENT_HISTORY_HEADER)
        print("─" * 60)
        print("   No result history yet. Run `sm swab` to populate.")
        return

    # Count last-known statuses
    last_results: Dict[str, int] = {}
    for stats in gates_with_results.values():
        last = stats.results[-1]
        last_results[last] = last_results.get(last, 0) + 1

    total = sum(last_results.values())

    print()
    print(RECENT_HISTORY_HEADER)
    print("─" * 60)

    parts: List[str] = []
    for status, count in sorted(last_results.items()):
        parts.append(f"{count} {status}")
    print(f"   Last known: {', '.join(parts)} ({total} gates tracked)")


# ── Main ─────────────────────────────────────────────────────────


def _build_status_dict(
    root: Path,
    config: Dict[str, Any],
    all_gates: List[str],
    swab_gates: Set[str],
    scour_only_gates: Set[str],
    disabled: List[str],
    applicability: Dict[str, Tuple[bool, str]],
    roles: Dict[str, str],
    history: Dict[str, TimingStats],
) -> Dict[str, Any]:
    """Build a JSON-serializable dict of project status."""
    gate_list: List[Dict[str, Any]] = []
    for gate in all_gates:
        is_app, reason = applicability.get(gate, (True, ""))
        hist = history.get(gate)
        entry: Dict[str, Any] = {
            "name": gate,
            "role": roles.get(gate),
            "applicable": is_app,
            "in_swab": gate in swab_gates,
            "in_scour": gate in swab_gates or gate in scour_only_gates,
        }
        if not is_app:
            entry["skip_reason"] = reason
        if hist and hist.results:
            entry["last_result"] = hist.results[-1]
            entry["history"] = hist.results[-10:]
        gate_list.append(entry)

    result: Dict[str, Any] = {
        "project_root": str(root),
        "config_file": str(root / ".sb_config.json"),
        "swabbing_time": config.get("swabbing_time"),
        "gates": {
            "swab_count": len(swab_gates),
            "scour_only_count": len(scour_only_gates),
            "disabled": sorted(disabled),
            "inventory": gate_list,
        },
    }

    # Project scope — same lightweight scan as the human output
    from slopmop.checks.base import count_source_scope

    scope = count_source_scope(str(root))
    if scope.files > 0:
        result["scope"] = scope.to_dict()

    return result


def run_status(
    project_root: str,
    quiet: bool = False,
    verbose: bool = False,
    json_output: Optional[bool] = None,
) -> int:
    """Show project dashboard without running any gates.

    Displays configuration summary, gate inventory with historical
    results, and hook installation status.  This is an observatory,
    not a validation command.

    Args:
        project_root: Absolute path to the project root.
        quiet: Suppress header.
        verbose: Show additional detail (e.g. per-gate timing stats).
        json_output: If True, emit JSON. If None, auto-detect from TTY.

    Returns:
        Always 0 (observatory — no pass/fail).
    """
    from slopmop.sm import load_config

    ensure_checks_registered()

    root = Path(project_root).resolve()
    if not root.is_dir():
        print(f"❌ Project root not found: {root}")
        return 1

    # Resolve JSON mode: explicit flag > auto-detect (not TTY → JSON)
    if json_output is None:
        json_mode = not sys.stdout.isatty()
    else:
        json_mode = json_output

    registry = get_registry()
    config = load_config(root)

    # Register user-defined custom gates from config
    from slopmop.checks.custom import register_custom_gates

    register_custom_gates(config)

    # ── Gate lists ────────────────────────────────────────────────
    all_gates = registry.list_checks()
    swab_gates = set(registry.get_gate_names_for_level(GateLevel.SWAB))
    scour_only_gates = (
        set(registry.get_gate_names_for_level(GateLevel.SCOUR)) - swab_gates
    )
    disabled = config.get("disabled_gates", [])

    # ── Applicability + role (no execution) ──────────────────────
    # We already instantiate each check to probe is_applicable(); the
    # role classvar comes for free on the same instance.  Collect both
    # in one pass so downstream formatters don't need registry access.
    applicability: Dict[str, Tuple[bool, str]] = {}
    roles: Dict[str, str] = {}
    for gate_name in all_gates:
        check = registry.get_check(gate_name, config)
        if check:
            is_app = check.is_applicable(str(root))
            reason = check.skip_reason(str(root)) if not is_app else ""
            applicability[gate_name] = (is_app, reason)
            roles[gate_name] = check.role.value
        else:
            applicability[gate_name] = (False, "check class not found")

    # ── Historical timing data ────────────────────────────────────
    history = load_timings(str(root))

    # ── JSON output ───────────────────────────────────────────────
    if json_mode:
        data = _build_status_dict(
            root,
            config,
            all_gates,
            swab_gates,
            scour_only_gates,
            disabled,
            applicability,
            roles,
            history,
        )
        print(json.dumps(data, separators=(",", ":")))
        return 0

    # ── Pretty output ─────────────────────────────────────────────
    colors_enabled = sys.stdout.isatty()

    if not quiet:
        print()
        print("🪣 slop-mop · project dashboard")
        print("═" * 60)

    _print_config_summary(
        root=root,
        config=config,
        swab_count=len(swab_gates),
        scour_count=len(scour_only_gates),
        disabled=disabled,
    )

    _print_gate_inventory(
        all_gates=all_gates,
        swab_gates=swab_gates,
        scour_gates=set(registry.get_gate_names_for_level(GateLevel.SCOUR)),
        applicability=applicability,
        roles=roles,
        history=history,
        colors_enabled=colors_enabled,
    )

    _print_recent_history(history)

    _print_hooks_status(root)

    print()
    print("═" * 60)
    print("Run `sm swab` to validate or `sm scour` for thorough check.")
    print()

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Handle the status command from argparse."""
    return run_status(
        project_root=args.project_root,
        quiet=args.quiet,
        verbose=args.verbose,
        json_output=getattr(args, "json_output", None),
    )
