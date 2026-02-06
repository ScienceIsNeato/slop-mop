"""Status command for slop-mop CLI.

Runs all gates in a profile and prints a gate inventory showing
what's registered, what's applicable, what's passing, and what
needs fixing.  Unlike validate, there is no per-gate progress
output — just a quiet run followed by a full report.
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

from slopmop.checks import ensure_checks_registered
from slopmop.checks.base import GateCategory
from slopmop.core.executor import CheckExecutor
from slopmop.core.registry import get_registry
from slopmop.core.result import CheckResult, CheckStatus, ExecutionSummary

# Category display order — controls section ordering in the inventory
_CATEGORY_ORDER = [
    "python",
    "quality",
    "security",
    "general",
    "javascript",
    "integration",
    "pr",
]


def _get_category_display(category_key: str) -> Tuple[str, str]:
    """Get emoji and display name for a category key."""
    for cat in GateCategory:
        if cat.key == category_key:
            return cat.emoji, cat._display_name
    return "❓", category_key.title()


def _find_other_profiles(
    gate: str, aliases: Dict[str, List[str]], current_profile: str
) -> List[str]:
    """Find profiles that include a gate, excluding the current one."""
    return [
        alias
        for alias, gates in aliases.items()
        if gate in gates and alias != current_profile
    ]


def _print_gate_inventory(
    all_gates: List[str],
    profile_gates: Set[str],
    results_map: Dict[str, CheckResult],
    applicability: Dict[str, Tuple[bool, str]],
    aliases: Dict[str, List[str]],
    profile: str,
) -> None:
    """Print the full gate inventory grouped by category.

    Shows every registered gate with its status relative to the
    current profile and run results.
    """
    # Group gates by category key
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

            if gate in profile_gates:
                result = results_map.get(gate)
                if result is None:
                    line = f"   ?  {gate_name:<28} — in profile, no result"
                elif result.status == CheckStatus.PASSED:
                    line = f"   ✅ {gate_name:<28} — passing"
                elif result.status == CheckStatus.FAILED:
                    line = f"   ❌ {gate_name:<28} — FAILING"
                elif result.status == CheckStatus.ERROR:
                    line = f"   💥 {gate_name:<28} — ERROR"
                elif result.status == CheckStatus.SKIPPED:
                    reason = result.output or "skipped"
                    line = f"   ⏭️  {gate_name:<28} — skipped ({reason})"
                else:
                    line = f"   ?  {gate_name:<28} — unknown status"
            else:
                is_applicable, skip_reason = applicability.get(gate, (True, ""))
                if not is_applicable:
                    line = f"   ⊘  {gate_name:<28} — not applicable" f" ({skip_reason})"
                else:
                    other = _find_other_profiles(gate, aliases, profile)
                    if other:
                        profiles_str = ", ".join(sorted(other))
                        line = (
                            f"   ·  {gate_name:<28}"
                            f" — not in profile (in: {profiles_str})"
                        )
                    else:
                        line = f"   ·  {gate_name:<28} — not in profile"

            print(line)


def _print_remediation(results_map: Dict[str, CheckResult]) -> None:
    """Print remediation guidance for failing gates."""
    failing = [
        r
        for r in results_map.values()
        if r.status in (CheckStatus.FAILED, CheckStatus.ERROR)
    ]
    if not failing:
        return

    print()
    print("🧹 REMEDIATION NEEDED")
    print("─" * 60)

    for r in failing:
        emoji = "❌" if r.status == CheckStatus.FAILED else "💥"
        print()
        print(f"{emoji} {r.name}")
        if r.error:
            print(f"   {r.error}")
        if r.fix_suggestion:
            print(f"   Fix: {r.fix_suggestion}")
        print(f"   Verify: sm validate {r.name}")


def _print_verdict(summary: ExecutionSummary) -> None:
    """Print the bottom-line verdict."""
    print()
    print("═" * 60)

    ran = [r for r in summary.results if r.status != CheckStatus.SKIPPED]
    failing = [r for r in ran if r.status in (CheckStatus.FAILED, CheckStatus.ERROR)]

    if not failing:
        print(
            "✨ All applicable gates pass — "
            f"no AI slop detected in repo · ⏱️  {summary.total_duration:.1f}s"
        )
    else:
        passed_count = len([r for r in ran if r.status == CheckStatus.PASSED])
        print(
            f"🧹 {passed_count}/{len(ran)} gates passing, "
            f"{len(failing)} failing "
            f"· ⏱️  {summary.total_duration:.1f}s"
        )
    print("═" * 60)
    print()


def run_status(
    project_root: str,
    profile: str = "pr",
    quiet: bool = False,
    verbose: bool = False,
) -> int:
    """Run all gates and print a gate inventory report.

    This is the shared implementation used by both ``sm status``
    and the post-init report.  It can be called directly without
    constructing an argparse.Namespace.

    The default profile is "pr" (broader than "commit") because
    status is an observatory, not an iterative validation loop.
    It's worth running security:full, diff-coverage, and JS gates
    here even if they'd slow down the commit workflow.

    Args:
        project_root: Absolute path to the project root.
        profile: Profile alias to run (default: "pr").
        quiet: Suppress header and progress indicator.
        verbose: Show verbose gate output (reserved for future use).

    Returns:
        0 if all gates pass, 1 otherwise.
    """
    from slopmop.sm import load_config

    ensure_checks_registered()

    root = Path(project_root).resolve()
    if not root.is_dir():
        print(f"❌ Project root not found: {root}")
        return 1

    registry = get_registry()
    config = load_config(root)

    # Enumerate all registered gates and profile membership
    all_gates = registry.list_checks()
    aliases = registry.list_aliases()
    profile_gate_list = (
        registry.expand_alias(profile) if registry.is_alias(profile) else [profile]
    )
    profile_gates = set(profile_gate_list)

    # Check applicability for gates NOT in the profile
    applicability: Dict[str, Tuple[bool, str]] = {}
    for gate_name in all_gates:
        if gate_name not in profile_gates:
            check = registry.get_check(gate_name, config)
            if check:
                is_app = check.is_applicable(str(root))
                reason = check.skip_reason(str(root)) if not is_app else ""
                applicability[gate_name] = (is_app, reason)
            else:
                applicability[gate_name] = (False, "check class not found")

    # Header
    if not quiet:
        print()
        print(f"🧹 Slop-Mop Status — {profile} profile")
        print("═" * 60)
        print(f"\nRunning {len(profile_gate_list)} gates...")
        sys.stdout.flush()

    # Run gates silently — no progress callback
    executor = CheckExecutor(
        registry=registry,
        fail_fast=False,
    )

    summary = executor.run_checks(
        project_root=str(root),
        check_names=[profile],
        config=config,
        auto_fix=False,
    )

    # Build results map
    results_map: Dict[str, CheckResult] = {r.name: r for r in summary.results}

    # Print inventory
    _print_gate_inventory(
        all_gates=all_gates,
        profile_gates=profile_gates,
        results_map=results_map,
        applicability=applicability,
        aliases=aliases,
        profile=profile,
    )

    # Print remediation for failures
    _print_remediation(results_map)

    # Print verdict
    _print_verdict(summary)

    return 0 if summary.all_passed else 1


def cmd_status(args: argparse.Namespace) -> int:
    """Handle the status command.

    Runs the specified profile (default: commit) with no per-gate
    progress, then prints a full gate inventory and remediation report.
    """
    return run_status(
        project_root=args.project_root,
        profile=args.profile or "pr",
        quiet=args.quiet,
        verbose=args.verbose,
    )
