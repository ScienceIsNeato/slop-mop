"""Status command for slop-mop CLI.

Project dashboard — shows configuration, gate inventory with
historical results, and hook installation status.  Does NOT run any
gates; use ``sm swab`` or ``sm scour`` for that.
"""

import argparse
import json
import sys
import textwrap
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, cast

from slopmop.baseline import (
    baseline_snapshot_path,
    generate_baseline_snapshot,
    latest_run_artifact_path,
    load_baseline_snapshot,
)
from slopmop.checks import ensure_checks_registered
from slopmop.checks.base import GateCategory, GateLevel
from slopmop.core.registry import get_registry
from slopmop.reporting.timings import TimingStats, load_timings
from slopmop.workflow.state_machine import WorkflowState
from slopmop.workflow.state_store import read_phase, read_state

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
HISTORICAL_STATUS_NOTE = (
    "Historical dashboard only: uses recorded run history and does not execute gates."
)

# Shared role → badge map lives in constants.py alongside STATUS_EMOJI —
# imported rather than duplicated so `sm status` and the ConsoleAdapter
# post-run summary can't drift.  Re-exported as an underscored module
# alias to keep existing call sites (`_ROLE_BADGES.get(...)`) unchanged.
from slopmop.constants import ROLE_BADGES as _ROLE_BADGES


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
    latest_result: Optional[str] = None,
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
    history_result: Optional[str] = None
    if history is not None and history.results:
        history_result = history.results[-1]

    if not is_applicable:
        icon = "⊘"
        suffix = f"n/a ({skip_reason})"
    elif latest_result or history_result:
        last_result = latest_result or history_result or "unknown"
        _RESULT_ICONS = {
            "passed": "✅",
            "failed": "❌",
            "error": "💥",
            "warned": "⚠️",
            "skipped": "⏭️",
            "not_applicable": "⊘",
        }
        icon = _RESULT_ICONS.get(last_result, "?")
        sparkline = (
            history.sparkline(max_width=10, colors_enabled=colors_enabled)
            if history is not None
            else ""
        )
        # Build suffix from last result + sparkline
        suffix = f"last: {last_result}"
        if sparkline:
            suffix = f"last: {last_result}  {sparkline}"
    else:
        icon = "·"
        suffix = (
            "no history (run sm scour)" if in_scour and not in_swab else "no history"
        )

    # Use dynamic width — gate names can exceed 28 chars
    name_width = max(len(gate_name), 28)
    return f"   {icon} {role_badge}{gate_name:<{name_width}} [{level_tag}] {suffix}"


def _print_gate_inventory(
    all_gates: List[str],
    swab_gates: Set[str],
    scour_gates: Set[str],
    applicability: Dict[str, Tuple[bool, str]],
    roles: Dict[str, str],
    history: Dict[str, TimingStats],
    colors_enabled: bool,
    latest_results: Optional[Dict[str, str]] = None,
) -> None:
    """Print the full gate inventory grouped by category.

    Shows every registered gate with role, level membership,
    applicability, and last-known result from historical timing data.
    N/A gates are collapsed into a single summary line at the bottom
    to keep the inventory focused on actionable results.
    """
    by_category: Dict[str, List[str]] = defaultdict(list)
    na_gates: List[Tuple[str, str]] = []  # (full_name, reason)
    for gate in all_gates:
        is_app, reason = applicability.get(gate, (True, ""))
        if not is_app:
            na_gates.append((gate, reason))
        else:
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

            line = _format_gate_line(
                gate_name,
                role=roles.get(gate, ""),
                in_swab=gate in swab_gates,
                in_scour=gate in scour_gates and gate not in swab_gates,
                is_applicable=True,
                skip_reason="",
                history=history.get(gate),
                latest_result=(latest_results or {}).get(gate),
                colors_enabled=colors_enabled,
            )
            print(line)

    if na_gates:
        names = [g.split(":", 1)[1] for g, _ in sorted(na_gates)]
        prefix = f"   ⊘ {len(na_gates)} n/a: "
        body = ", ".join(names)
        wrapped = textwrap.fill(
            body,
            width=76,
            initial_indent=prefix,
            subsequent_indent=" " * len(prefix),
        )
        print()
        print(wrapped)


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


# ── Section: Workflow Position ────────────────────────────────────


def _gather_workflow_data(root: Path) -> Dict[str, Any]:
    """Single source of truth for workflow-position data.

    Returns a canonical dict consumed by both the human-readable
    printer and the JSON serialiser — no duplicated logic.
    """
    state = read_state(root) or WorkflowState.IDLE
    phase = read_phase(root)
    return {
        "state": state.value,
        "state_id": state.state_id,
        "position": state.position,
        "next_action": state.next_action,
        "phase": phase.value,
    }


def _print_workflow_position(workflow: Dict[str, Any]) -> None:
    """Human-readable adapter for workflow-position data."""
    print()
    print("\U0001f4cd WORKFLOW POSITION")
    print("\u2500" * 60)
    print(
        f"   {workflow['state_id']} ({workflow['state'].upper()}) "
        f"\u2014 Next: {workflow['next_action']}"
    )
    print(f"   Phase: {workflow['phase']}")


# ── Section: CI Summary ─────────────────────────────────────────


def _gather_ci_data(root: Path) -> Optional[Dict[str, Any]]:
    """Single source of truth for CI summary data.

    Returns a canonical dict consumed by both the human-readable
    printer and the JSON serialiser, or ``None`` when no PR is
    detected / ``gh`` is unavailable.
    """
    from slopmop.cli.ci import _categorize_checks, _detect_pr_number, _fetch_checks

    pr = _detect_pr_number(root)
    if pr is None:
        return None

    checks, err = _fetch_checks(root, pr)
    if checks is None or err:
        return None

    if not checks:
        return {"pr_number": pr, "passed": 0, "failed": 0, "pending": 0, "failures": []}

    completed, in_progress, failed = _categorize_checks(checks)
    return {
        "pr_number": pr,
        "passed": len(completed),
        "failed": len(failed),
        "pending": len(in_progress),
        "failures": [name for name, _, _, _ in failed],
    }


def _print_ci_summary(ci: Optional[Dict[str, Any]]) -> None:
    """Human-readable adapter for CI summary data.

    Silently returns when *ci* is ``None`` (no PR detected).
    This is the lightweight overview — ``sm buff status`` is the
    detailed view.
    """
    if ci is None:
        return

    pr = ci["pr_number"]
    total = ci["passed"] + ci["failed"] + ci["pending"]
    if total == 0:
        return

    print()
    print(f"🔄 CI STATUS (PR #{pr})")
    print("─" * 60)

    parts = [f"✅ {ci['passed']} passed"]
    if ci["failed"]:
        parts.append(f"❌ {ci['failed']} failed")
    if ci["pending"]:
        parts.append(f"🔄 {ci['pending']} pending")
    print(f"   {' · '.join(parts)} (of {total})")

    for name in ci["failures"][:3]:
        print(f"   ✗ {name}")
    if len(ci["failures"]) > 3:
        print(f"   … and {len(ci['failures']) - 3} more")

    if not ci["failed"] and not ci["pending"]:
        print("   All checks green ✨")


# ── Section: Baseline Snapshot ──────────────────────────────────


def _gather_baseline_snapshot_data(root: Path) -> Optional[Dict[str, Any]]:
    """Return baseline snapshot metadata for status display."""
    snapshot = load_baseline_snapshot(root)
    if snapshot is None:
        return {
            "present": False,
            "help": "Collect baseline via `sm status --generate-baseline-snapshot` after `sm scour`.",
        }

    data: Dict[str, Any] = {
        "present": True,
        "path": str(baseline_snapshot_path(root)),
        "source_file": snapshot.get("source_file"),
    }
    captured_at = snapshot.get("captured_at")
    if isinstance(captured_at, str) and captured_at:
        data["captured_at"] = captured_at
    fingerprints: object = snapshot.get("failure_fingerprints")
    if isinstance(fingerprints, list):
        fingerprint_list = cast(List[object], fingerprints)
        data["tracked_failures"] = len(fingerprint_list)

    source_artifact = snapshot.get("source_artifact")
    if isinstance(source_artifact, dict):
        failure_counts = _failure_counts_from_artifact(
            cast(Dict[str, Any], source_artifact)
        )
        if failure_counts:
            data["failed_gates"] = len(failure_counts)
            data["failure_counts"] = failure_counts
    return data


def _print_baseline_snapshot(baseline: Optional[Dict[str, Any]]) -> None:
    """Human-readable baseline snapshot adapter."""
    if baseline is None:
        return

    print()
    print("🧷 BASELINE SNAPSHOT")
    print("─" * 60)
    if baseline.get("present") is False:
        help_msg = baseline.get("help")
        print("   Missing")
        if isinstance(help_msg, str) and help_msg:
            print(f"   {help_msg}")
        return

    print(f"   Path: {baseline['path']}")
    source_file = baseline.get("source_file")
    if isinstance(source_file, str) and source_file:
        print(f"   Source: {source_file}")
    failed_gates = baseline.get("failed_gates")
    if isinstance(failed_gates, int):
        print(f"   Failed gates: {failed_gates}")
    tracked_failures = baseline.get("tracked_failures")
    if isinstance(tracked_failures, int):
        print(f"   Tracked failures: {tracked_failures}")
    captured_at = baseline.get("captured_at")
    if isinstance(captured_at, str) and captured_at:
        print(f"   Captured: {captured_at}")
    failure_counts = baseline.get("failure_counts")
    if isinstance(failure_counts, list) and failure_counts:
        print()
        print("   Gate                               Failures")
        print("   ───────────────────────────────────────────")
        for row in cast(List[object], failure_counts):
            if not isinstance(row, dict):
                continue
            typed_row = cast(Dict[str, Any], row)
            name = typed_row.get("name")
            count = typed_row.get("count")
            if isinstance(name, str) and isinstance(count, int):
                print(f"   {name:<34} {count:>8}")


def _failure_counts_from_artifact(
    source_artifact: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Build per-gate failure counts from a persisted run artifact."""
    raw_results = source_artifact.get("results")
    if not isinstance(raw_results, list):
        return []

    failure_rows: List[Dict[str, Any]] = []
    for raw_entry in cast(List[object], raw_results):
        if not isinstance(raw_entry, dict):
            continue
        entry = cast(Dict[str, Any], raw_entry)
        if entry.get("status") != "failed":
            continue

        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue

        count = 1
        findings = entry.get("findings")
        if isinstance(findings, list) and findings:
            count = len(cast(List[object], findings))

        failure_rows.append({"name": name, "count": count})

    failure_rows.sort(
        key=lambda row: (-(cast(int, row["count"])), cast(str, row["name"]))
    )
    return failure_rows


def _load_latest_run_artifact(root: Path) -> Optional[Dict[str, Any]]:
    """Load the newest canonical full-run artifact, if present."""
    artifact_path = latest_run_artifact_path(root)
    if artifact_path is None:
        return None
    try:
        raw = json.loads(artifact_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    artifact = cast(Dict[str, Any], raw)
    artifact["source_file"] = artifact_path.name
    return artifact


def _load_persisted_run_artifacts(root: Path) -> List[Dict[str, Any]]:
    """Load all canonical persisted run artifacts, newest first."""
    artifacts: List[Dict[str, Any]] = []
    for name in ("last_swab.json", "last_scour.json"):
        artifact_path = root / ".slopmop" / name
        if not artifact_path.exists() or not artifact_path.is_file():
            continue
        try:
            raw = json.loads(artifact_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        artifact = cast(Dict[str, Any], raw)
        artifact["source_file"] = artifact_path.name
        artifact["source_mtime"] = artifact_path.stat().st_mtime
        artifacts.append(artifact)
    artifacts.sort(
        key=lambda artifact: float(cast(Any, artifact.get("source_mtime", 0.0))),
        reverse=True,
    )
    return artifacts


def _load_latest_gate_results(
    root: Path, history: Dict[str, TimingStats]
) -> Dict[str, str]:
    """Return the latest per-gate statuses from artifacts, with history fallback."""
    results: Dict[str, str] = {}
    for artifact in _load_persisted_run_artifacts(root):
        passed = artifact.get("passed_gates")
        if isinstance(passed, list):
            for item in cast(List[object], passed):
                if isinstance(item, str) and item not in results:
                    results[item] = "passed"

        raw_results = artifact.get("results")
        if isinstance(raw_results, list):
            for raw_entry in cast(List[object], raw_results):
                if not isinstance(raw_entry, dict):
                    continue
                entry = cast(Dict[str, Any], raw_entry)
                name = entry.get("name")
                status = entry.get("status")
                if (
                    isinstance(name, str)
                    and isinstance(status, str)
                    and name not in results
                ):
                    results[name] = status

    for gate_name, stats in history.items():
        if gate_name not in results and stats.results:
            results[gate_name] = stats.results[-1]

    return results


def _gather_recent_run_data(root: Path) -> Optional[Dict[str, Any]]:
    """Return the newest canonical run artifact summary for status display."""
    artifact = _load_latest_run_artifact(root)
    if artifact is None:
        return None

    summary = artifact.get("summary")
    if not isinstance(summary, dict):
        return None

    return {
        "source_file": artifact.get("source_file"),
        "summary": cast(Dict[str, Any], summary),
        "failure_counts": _failure_counts_from_artifact(artifact),
    }


# ── Section: Recent History ──────────────────────────────────────


def _print_recent_history(
    history: Dict[str, TimingStats],
    recent_run: Optional[Dict[str, Any]] = None,
) -> None:
    """Print a compact summary of recent gate runs."""
    if recent_run is not None:
        recent_run_dict = cast(Dict[str, Any], recent_run)
        summary = recent_run_dict.get("summary")
        if isinstance(summary, dict):
            summary_dict = cast(Dict[str, Any], summary)
            passed = int(summary_dict.get("passed", 0))
            failed = int(summary_dict.get("failed", 0))
            warned = int(summary_dict.get("warned", 0))
            errors = int(summary_dict.get("errors", 0))
            skipped = int(summary_dict.get("skipped", 0))
            tracked = passed + failed + warned + errors + skipped

            print()
            print(RECENT_HISTORY_HEADER)
            print("─" * 60)

            source_file = recent_run_dict.get("source_file")
            if isinstance(source_file, str) and source_file:
                print(f"   Source: {source_file}")

            summary_parts: List[str] = []
            if passed:
                summary_parts.append(f"{passed} passed")
            if failed:
                summary_parts.append(f"{failed} failed")
            if warned:
                summary_parts.append(f"{warned} warned")
            if errors:
                summary_parts.append(f"{errors} errored")
            if skipped:
                summary_parts.append(f"{skipped} skipped")
            print(
                f"   Last recorded: {', '.join(summary_parts)} ({tracked} gates tracked)"
            )

            failure_counts = recent_run_dict.get("failure_counts")
            if isinstance(failure_counts, list):
                rows = cast(List[object], failure_counts)
                print(f"   Failed gates: {len(rows)}")
                if rows:
                    print()
                    print("   Gate                               Failures")
                    print("   ───────────────────────────────────────────")
                    for raw_row in rows:
                        if not isinstance(raw_row, dict):
                            continue
                        row = cast(Dict[str, Any], raw_row)
                        name = row.get("name")
                        count = row.get("count")
                        if isinstance(name, str) and isinstance(count, int):
                            print(f"   {name:<34} {count:>8}")
                return

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
    print(f"   Last recorded: {', '.join(parts)} ({total} gates tracked)")


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
    latest_results: Dict[str, str],
    recent_run: Optional[Dict[str, Any]],
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
        latest_result = latest_results.get(gate)
        if latest_result:
            entry["last_result"] = latest_result
        elif hist and hist.results:
            entry["last_result"] = hist.results[-1]
        if hist and hist.results:
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

    result["workflow"] = _gather_workflow_data(root)

    ci = _gather_ci_data(root)
    if ci is not None:
        result["ci"] = ci

    if recent_run is not None:
        result["recent_run"] = recent_run

    return result


def run_status(
    project_root: str,
    quiet: bool = False,
    verbose: bool = False,
    json_output: Optional[bool] = None,
    generate_baseline_snapshot_flag: bool = False,
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

    snapshot_info: Optional[Dict[str, str]] = None
    if generate_baseline_snapshot_flag:
        try:
            snapshot_path, source_path = generate_baseline_snapshot(root)
            snapshot_info = {
                "snapshot_path": str(snapshot_path),
                "source_path": str(source_path),
            }
        except (FileNotFoundError, ValueError) as exc:
            print(f"❌ {exc}")
            return 1

    baseline = _gather_baseline_snapshot_data(root)

    # Register user-defined custom gates from config
    from slopmop.checks.custom import register_custom_gates

    register_custom_gates(config)

    # ── Gate lists ────────────────────────────────────────────────
    all_gates = registry.list_checks()
    swab_gates = set(registry.get_gate_names_for_level(GateLevel.SWAB, config))
    scour_only_gates = (
        set(registry.get_gate_names_for_level(GateLevel.SCOUR, config)) - swab_gates
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
    latest_results = _load_latest_gate_results(root, history)
    recent_run = _gather_recent_run_data(root)

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
            latest_results,
            recent_run,
        )
        if baseline is not None:
            data["baseline_snapshot"] = baseline
        if snapshot_info is not None:
            data["baseline_snapshot_generated"] = snapshot_info
        print(json.dumps(data, separators=(",", ":")))
        return 0

    # ── Pretty output ─────────────────────────────────────────────
    colors_enabled = sys.stdout.isatty()

    if not quiet:
        print()
        print("🪣 slop-mop · project dashboard")
        print("═" * 60)
        print(f"{HISTORICAL_STATUS_NOTE}")
        print("Fresh checks: `sm swab` or `sm scour --no-cache`.")

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
        scour_gates=set(registry.get_gate_names_for_level(GateLevel.SCOUR, config)),
        applicability=applicability,
        roles=roles,
        history=history,
        latest_results=latest_results,
        colors_enabled=colors_enabled,
    )

    _print_recent_history(history, recent_run)

    _print_hooks_status(root)

    workflow = _gather_workflow_data(root)
    _print_workflow_position(workflow)

    ci = _gather_ci_data(root)
    _print_ci_summary(ci)

    _print_baseline_snapshot(baseline)

    if snapshot_info is not None:
        print()
        print("🧷 BASELINE SNAPSHOT GENERATED")
        print("─" * 60)
        print(f"   Saved: {snapshot_info['snapshot_path']}")
        print(f"   Source: {snapshot_info['source_path']}")

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
        generate_baseline_snapshot_flag=getattr(
            args, "generate_baseline_snapshot", False
        ),
    )
