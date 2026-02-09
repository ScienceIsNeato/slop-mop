"""Status command for slop-mop CLI.

Runs all gates in a profile and prints a gate inventory showing
what's registered, what's applicable, what's passing, and what
needs fixing.  Unlike validate, there is no per-gate progress
output — just a quiet run followed by a full report.
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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
            return cat.emoji, cat.display_name
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
                line = _format_profile_gate(gate_name, results_map.get(gate))
            else:
                line = _format_non_profile_gate(
                    gate, gate_name, applicability, aliases, profile
                )

            print(line)


def _format_profile_gate(gate_name: str, result: Optional[CheckResult]) -> str:
    """Format a gate that's in the active profile."""
    _STATUS_DISPLAY = {
        CheckStatus.PASSED: ("✅", "passing"),
        CheckStatus.FAILED: ("❌", "FAILING"),
        CheckStatus.ERROR: ("💥", "ERROR"),
        CheckStatus.WARNED: ("⚠️", "WARNED"),
    }

    if result is None:
        return f"   ?  {gate_name:<28} — in profile, no result"

    if result.status in _STATUS_DISPLAY:
        icon, label = _STATUS_DISPLAY[result.status]
        return f"   {icon} {gate_name:<28} — {label}"

    if result.status == CheckStatus.NOT_APPLICABLE:
        reason = result.output or "not applicable"
        return f"   ⊘  {gate_name:<28} — n/a ({reason})"

    if result.status == CheckStatus.SKIPPED:
        reason = result.output or "skipped"
        return f"   ⏭️  {gate_name:<28} — skipped ({reason})"

    return f"   ?  {gate_name:<28} — unknown status"


def _format_non_profile_gate(
    gate: str,
    gate_name: str,
    applicability: Dict[str, Tuple[bool, str]],
    aliases: Dict[str, List[str]],
    profile: str,
) -> str:
    """Format a gate that's not in the active profile."""
    is_applicable, skip_reason = applicability.get(gate, (True, ""))
    if not is_applicable:
        return f"   ⊘  {gate_name:<28} — n/a ({skip_reason})"

    other = _find_other_profiles(gate, aliases, profile)
    if other:
        profiles_str = ", ".join(sorted(other))
        return f"   ·  {gate_name:<28}" f" — not in profile (in: {profiles_str})"
    return f"   ·  {gate_name:<28} — not in profile"


def _print_remediation(results_map: Dict[str, CheckResult]) -> None:
    """Print remediation guidance for failing gates."""
    failing = [
        r
        for r in results_map.values()
        if r.status in (CheckStatus.FAILED, CheckStatus.ERROR)
    ]
    warned = [r for r in results_map.values() if r.status == CheckStatus.WARNED]
    if not failing and not warned:
        return

    if failing:
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
            print(f"   Verify: ./sm validate {r.name}")

    if warned:
        print()
        print("⚠️  WARNINGS (non-blocking)")
        print("─" * 60)

        for r in warned:
            print()
            print(f"⚠️  {r.name}")
            if r.error:
                print(f"   {r.error}")
            if r.fix_suggestion:
                print(f"   Fix: {r.fix_suggestion}")


def _print_verdict(summary: ExecutionSummary) -> None:
    """Print the bottom-line verdict."""
    print()
    print("═" * 60)

    ran = [
        r
        for r in summary.results
        if r.status not in (CheckStatus.SKIPPED, CheckStatus.NOT_APPLICABLE)
    ]
    failing = [r for r in ran if r.status in (CheckStatus.FAILED, CheckStatus.ERROR)]
    warned = [r for r in ran if r.status == CheckStatus.WARNED]

    warn_suffix = f", {len(warned)} warned" if warned else ""

    if not failing:
        print(
            "✨ All applicable gates pass — "
            f"no AI slop detected in repo"
            f"{warn_suffix}"
            f" · ⏱️  {summary.total_duration:.1f}s"
        )
    else:
        passed_count = len([r for r in ran if r.status == CheckStatus.PASSED])
        print(
            f"🧹 {passed_count}/{len(ran)} gates passing, "
            f"{len(failing)} failing"
            f"{warn_suffix}"
            f" · ⏱️  {summary.total_duration:.1f}s"
        )
    print("═" * 60)


def _print_recommendations(
    all_gates: List[str],
    profile_gates: Set[str],
    applicability: Dict[str, Tuple[bool, str]],
) -> None:
    """Print recommendations for expanding gate coverage.

    Suggests applicable gates that aren't in the current profile,
    giving users a clear path to increase strictness.
    """
    # Find applicable gates NOT in current profile
    recommended: List[str] = []
    for gate in all_gates:
        if gate not in profile_gates:
            is_applicable, _ = applicability.get(gate, (True, ""))
            if is_applicable:
                recommended.append(gate)

    if not recommended:
        return

    print()
    print("💡 RECOMMENDATIONS")
    print("─" * 60)
    print("These gates are applicable but not in your current profile:")
    print()

    for gate in sorted(recommended):
        print(f"   ./sm validate {gate:<30}  # try it out")

    print()
    print("Run individually to see results, then add to your profile incrementally.")
    print()


def _write_verbose_json(
    root: Path,
    profile: str,
    all_gates: List[str],
    profile_gates: Set[str],
    results_map: Dict[str, CheckResult],
    applicability: Dict[str, Tuple[bool, str]],
    summary: ExecutionSummary,
) -> str:
    """Write verbose JSON report to file.

    Returns:
        Path to the generated JSON file.
    """
    # Build gate details
    gate_details: List[Dict[str, Any]] = []
    for gate in sorted(all_gates):
        in_profile = gate in profile_gates
        result = results_map.get(gate)

        detail: Dict[str, Any] = {
            "name": gate,
            "in_profile": in_profile,
        }

        if result:
            detail["status"] = result.status.name
            detail["duration"] = round(result.duration, 2)
            if result.output:
                detail["output"] = result.output
            if result.error:
                detail["error"] = result.error
            if result.fix_suggestion:
                detail["fix_suggestion"] = result.fix_suggestion
        else:
            is_applicable, reason = applicability.get(gate, (True, ""))
            detail["status"] = "NOT_IN_PROFILE"
            detail["applicable"] = is_applicable
            if reason:
                detail["skip_reason"] = reason

        gate_details.append(detail)

    report: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "project_root": str(root),
        "profile": profile,
        "summary": {
            "total_gates": len(all_gates),
            "gates_in_profile": len(profile_gates),
            "passed": len(
                [r for r in summary.results if r.status == CheckStatus.PASSED]
            ),
            "failed": len(
                [r for r in summary.results if r.status == CheckStatus.FAILED]
            ),
            "errors": len(
                [r for r in summary.results if r.status == CheckStatus.ERROR]
            ),
            "skipped": len(
                [r for r in summary.results if r.status == CheckStatus.SKIPPED]
            ),
            "not_applicable": len(
                [r for r in summary.results if r.status == CheckStatus.NOT_APPLICABLE]
            ),
            "duration": summary.total_duration,
            "all_passed": summary.all_passed,
        },
        "gates": gate_details,
    }

    # Write to timestamped file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = root / f"sm_status_{timestamp}.json"
    output_file.write_text(json.dumps(report, indent=2) + "\n")
    return str(output_file)


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
        verbose: Write full JSON report to sm_status_<timestamp>.json.

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

    # Print recommendations for expanding coverage
    _print_recommendations(
        all_gates=all_gates,
        profile_gates=profile_gates,
        applicability=applicability,
    )

    # Write verbose JSON report
    if verbose:
        output_file = _write_verbose_json(
            root=root,
            profile=profile,
            all_gates=all_gates,
            profile_gates=profile_gates,
            results_map=results_map,
            applicability=applicability,
            summary=summary,
        )
        print(f"📄 Verbose report written to: {output_file}")
        print()

    return 0 if summary.all_passed else 1


def cmd_status(args: argparse.Namespace) -> int:
    """Handle the status command.

    Runs the specified profile (default: pr) with no per-gate
    progress, then prints a full gate inventory and remediation report.
    """
    return run_status(
        project_root=args.project_root,
        profile=args.profile or "pr",
        quiet=args.quiet,
        verbose=args.verbose,
    )
