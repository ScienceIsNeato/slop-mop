"""Validation commands for slop-mop CLI.

Provides ``sm swab`` (quick, every-commit) and ``sm scour`` (thorough, PR)
top-level commands.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from slopmop.baseline import baseline_snapshot_path, filter_summary_against_baseline
from slopmop.checks import ensure_checks_registered
from slopmop.checks.base import GateLevel
from slopmop.core.executor import CheckExecutor
from slopmop.core.lock import SmLockError, max_expected_duration, sm_lock
from slopmop.core.registry import get_registry
from slopmop.core.result import CheckResult, CheckStatus
from slopmop.reporting.adapters import ConsoleAdapter, JsonAdapter, SarifAdapter
from slopmop.reporting.console import ConsoleReporter
from slopmop.reporting.dynamic import DynamicDisplay
from slopmop.reporting.report import RunReport
from slopmop.reporting.timings import clear_timings, load_timing_averages
from slopmop.workflow.state_machine import RepoPhase
from slopmop.workflow.state_store import read_phase


def _default_json_artifact_path(project_root: Path, artifact_name: str) -> str:
    """Return the default JSON artifact path anchored to the project root."""
    return str(project_root / ".slopmop" / artifact_name)


def _resolve_swabbing_time(
    args: argparse.Namespace,
    project_root: Path,
    preloaded_config: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """Resolve effective swabbing-time budget for this run.

    Resolution order:
    1. CLI ``--swabbing-time``
    2. ``.sb_config.json`` value
    3. None (no budget)
    """
    swabbing_time: Optional[int] = getattr(args, "swabbing_time", None)
    if swabbing_time is None:
        if preloaded_config is not None:
            config = preloaded_config
        else:
            from slopmop.sm import load_config

            config = load_config(project_root)
        config_val = config.get("swabbing_time")
        if isinstance(config_val, (int, float)) and config_val > 0:
            swabbing_time = int(config_val)

    if swabbing_time is not None and swabbing_time > 0:
        return int(swabbing_time)
    return None


def _is_json_mode(args: argparse.Namespace) -> bool:
    """Determine whether output should be JSON.

    Resolution order:
    1. Explicit --json → True
    2. Explicit --no-json → False
    3. Default: False (human-readable console output)
    """
    explicit = getattr(args, "json_output", None)
    if explicit is not None:
        return explicit
    return False


def _parse_quality_gates(args: argparse.Namespace) -> Optional[List[str]]:
    """Parse explicit -g quality gates from args, if any.

    Returns a flat list of gate names, or None if -g was not used.
    """
    if not getattr(args, "quality_gates", None):
        return None
    gates: List[str] = []
    for gate in args.quality_gates:
        gates.extend(g.strip() for g in gate.split(",") if g.strip())
    return gates


def _print_header(
    project_root: Path,
    gates: List[str],
    args: argparse.Namespace,
    swabbing_time: "Optional[int]" = None,
) -> None:
    """Print validation header.

    Single-line banner with optional time budget appended.
    """
    parts = ["\u2728 scanning the code for slop to mop"]
    if swabbing_time is not None and swabbing_time > 0:
        parts.append(f"  \u23f1\ufe0f  Time budget: {swabbing_time}s")
    print("".join(parts))
    print()


def _setup_dynamic_display(
    executor: "CheckExecutor",
    reporter: "ConsoleReporter",
    quiet: bool,
    project_root: Path,
) -> tuple["DynamicDisplay", List[CheckResult]]:
    """Configure and start the dynamic display, wiring all executor callbacks.

    Failure details are buffered during the live animation and returned
    so the caller can print them after ``display.stop()``.

    Args:
        executor: The check executor to wire callbacks onto.
        reporter: The console reporter (used for failure details).
        quiet: Whether to suppress output.
        project_root: Project root for loading historical timings.

    Returns:
        Tuple of (started DynamicDisplay, list to be filled with deferred
        failure CheckResults).
    """
    display = DynamicDisplay(quiet=quiet)
    display.load_historical_timings(str(project_root))
    display.start()
    executor.set_start_callback(display.on_check_start)
    executor.set_disabled_callback(display.on_check_disabled)
    executor.set_na_callback(display.on_check_not_applicable)
    executor.set_total_callback(display.set_total_checks)
    executor.set_pending_callback(display.register_pending_checks)

    # Buffer failures/errors — printing during the live animation corrupts
    # cursor tracking.  The caller drains this list after display.stop().
    deferred_failures: List[CheckResult] = []

    def _combined(result: CheckResult) -> None:
        display.on_check_complete(result)
        if result.failed or result.status == CheckStatus.ERROR:
            deferred_failures.append(result)

    executor.set_progress_callback(_combined)
    return display, deferred_failures


# ─── Shared execution pipeline ───────────────────────────────────────────


def _run_validation(
    args: argparse.Namespace,
    gates: List[str],
    level_name: Optional[str],
    *,
    preloaded_config: Optional[Dict[str, Any]] = None,
    custom_gates_registered: bool = False,
) -> int:
    """Core validation pipeline shared by swab and scour.

    Args:
        args: Parsed CLI arguments (must have project_root,
              quiet, verbose, no_fail_fast, no_auto_fix, static,
              clear_history flags).
        gates: List of gate names or aliases to run.
        level_name: Display label (e.g. "swab", "scour").

    Returns:
        Exit code (0 = all passed, 1 = failures).
    """

    # Determine project root
    project_root = Path(args.project_root).resolve()

    if not project_root.is_dir():
        print(f"❌ Project root not found: {project_root}")
        return 1

    # Acquire repo-level lock — prevents concurrent sm runs from racing.
    verb = level_name or "validation"
    lock_stale_after: Optional[float] = None
    lock_expected_duration: Optional[float] = None
    resolved_swabbing_time: Optional[int] = None

    timing_averages = load_timing_averages(str(project_root))
    historical_estimate = (
        sum(timing_averages.values())
        if timing_averages
        else max_expected_duration(project_root)
    )

    if level_name == "swab":
        resolved_swabbing_time = _resolve_swabbing_time(
            args,
            project_root,
            preloaded_config=preloaded_config,
        )
        if resolved_swabbing_time is not None:
            lock_stale_after = float(resolved_swabbing_time * 3)
            lock_expected_duration = min(
                max(float(resolved_swabbing_time), 1.0),
                max(float(historical_estimate), 1.0),
            )
        else:
            lock_expected_duration = max(float(historical_estimate), 1.0)
    else:
        lock_expected_duration = max(float(historical_estimate), 1.0)

    # Internal nested validation runs, such as refit re-checking a single gate
    # while already holding the repo lock, can opt out of reacquiring here.
    skip_repo_lock = os.environ.get("SLOPMOP_SKIP_REPO_LOCK", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if skip_repo_lock:
        return _run_validation_locked(
            args,
            gates,
            level_name,
            project_root,
            resolved_swabbing_time=resolved_swabbing_time,
            preloaded_config=preloaded_config,
            custom_gates_registered=custom_gates_registered,
        )

    try:
        with sm_lock(
            project_root,
            verb,
            stale_after_seconds=lock_stale_after,
            expected_duration_seconds=lock_expected_duration,
        ):
            return _run_validation_locked(
                args,
                gates,
                level_name,
                project_root,
                resolved_swabbing_time=resolved_swabbing_time,
                preloaded_config=preloaded_config,
                custom_gates_registered=custom_gates_registered,
            )
    except SmLockError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _run_validation_locked(
    args: argparse.Namespace,
    gates: List[str],
    level_name: Optional[str],
    project_root: Path,
    resolved_swabbing_time: Optional[int] = None,
    *,
    preloaded_config: Optional[Dict[str, Any]] = None,
    custom_gates_registered: bool = False,
) -> int:
    """Inner validation pipeline, called while holding the repo lock."""
    from slopmop.sm import load_config

    json_mode = _is_json_mode(args)

    # Clear timing history if requested
    if getattr(args, "clear_history", False):
        if clear_timings(str(project_root)):
            if not args.quiet and not json_mode:
                print("🗑️  Timing history cleared")

    # Create executor.
    # Scour never uses fail-fast — it runs every gate to give the full picture.
    # Swab respects the --no-fail-fast flag (default: fail-fast ON).
    # In REMEDIATION phase, result processing follows remediation order rather
    # than race-to-completion order. In MAINTENANCE, results are evaluated as
    # soon as they complete. Dispatch order stays unchanged in both modes.
    registry = get_registry()
    use_fail_fast = False if level_name == "scour" else not args.no_fail_fast
    process_results_in_remediation_order = (
        read_phase(project_root) == RepoPhase.REMEDIATION
    )
    executor = CheckExecutor(
        registry=registry,
        fail_fast=use_fail_fast,
        process_results_in_remediation_order=process_results_in_remediation_order,
    )

    # Set up progress reporting (per-check status lines during the run;
    # RunReport + ConsoleAdapter own the end-of-run summary)
    reporter = ConsoleReporter(quiet=args.quiet, verbose=args.verbose)

    # Load configuration (must happen early — swabbing-time default lives here)
    config = (
        preloaded_config if preloaded_config is not None else load_config(project_root)
    )

    # Register user-defined custom gates from config
    if not custom_gates_registered:
        from slopmop.checks.custom import register_custom_gates

        register_custom_gates(config)

    # Validate explicit -g gate names against the registry.
    # Level-based discovery (level_name != None) uses registry-produced
    # names, so they're guaranteed valid.  User-supplied names need
    # checking so typos don't silently produce an empty run.
    if level_name is None:
        available = set(registry.list_checks())
        unknown = [g for g in gates if g not in available]
        if unknown:
            print(
                f"❌ Unknown quality gate(s): {', '.join(unknown)}",
                file=sys.stderr,
            )
            print("\nAvailable gates:", file=sys.stderr)
            for gate in sorted(available):
                print(f"  {gate}", file=sys.stderr)
            return 1

    # Determine if we should use dynamic display
    # JSON mode suppresses all interactive output
    # SARIF-to-stdout mode also suppresses console output so the JSON
    # payload is not corrupted by progress/header text.
    sarif_to_stdout = getattr(args, "sarif_output", False) and not getattr(
        args, "output_file", None
    )
    use_dynamic = (
        not json_mode
        and not sarif_to_stdout
        and sys.stdout.isatty()
        and not os.environ.get("NO_COLOR")
        and not args.quiet
        and not getattr(args, "static", False)
    )

    # Handle time budget (swabbing-time).
    # Only applies to swab, not scour.  Read from CLI flag first,
    # fall back to config value.  <= 0 means no limit.
    swabbing_time: Optional[int] = resolved_swabbing_time
    if swabbing_time is None:
        swabbing_time = _resolve_swabbing_time(
            args,
            project_root,
            preloaded_config=preloaded_config,
        )

    # Only enforce for swab runs
    if level_name != "swab":
        swabbing_time = None

    # Print header BEFORE starting dynamic display
    if not args.quiet and not json_mode and not sarif_to_stdout:
        _print_header(project_root, gates, args, swabbing_time=swabbing_time)

    # Load timing history for budget filtering
    timings: Optional[dict[str, float]] = None
    if swabbing_time is not None and swabbing_time > 0:
        timings = load_timing_averages(str(project_root))

    # Set up dynamic display if appropriate
    dynamic_display: Optional[DynamicDisplay] = None
    deferred_failures: List[CheckResult] = []
    if use_dynamic:
        dynamic_display, deferred_failures = _setup_dynamic_display(
            executor, reporter, args.quiet, project_root
        )
    elif not json_mode and not sarif_to_stdout:
        # Fall back to traditional reporter (no progress in JSON mode
        # or SARIF-to-stdout mode)
        executor.set_progress_callback(reporter.on_check_complete)

    try:
        # Run checks
        summary = executor.run_checks(
            project_root=str(project_root),
            check_names=gates,
            config=config,
            auto_fix=not args.no_auto_fix,
            swabbing_time=swabbing_time,
            timings=timings,
            use_cache=not getattr(args, "no_cache", False),
        )

        # Stop dynamic display before printing summary
        if dynamic_display:
            dynamic_display.stop()
            dynamic_display.save_historical_timings(str(project_root))

            # Deferred failures are NOT printed here — the summary
            # adapter already shows failure details.  Printing them
            # individually via on_check_complete() too caused
            # double-reported failures (token sink #1).

        # ── Unified output pipeline ─────────────────────────────────
        # RunReport derives everything any adapter needs — once, here.
        # Adapters below are pure-transform: they format, they don't
        # compute.  Log writing is a side-effect owned by RunReport
        # (not adapters) so every format can reference the same files.
        baseline_metadata: Optional[Dict[str, object]] = None
        effective_summary = summary
        if getattr(args, "ignore_baseline_failures", False):
            from slopmop.baseline import load_baseline_snapshot

            snapshot = load_baseline_snapshot(project_root)
            if snapshot is None:
                print(
                    "❌ No baseline snapshot found. Run `sm status "
                    "--generate-baseline-snapshot` first.",
                    file=sys.stderr,
                )
                return 1
            filtered = filter_summary_against_baseline(
                summary,
                snapshot,
                snapshot_path=baseline_snapshot_path(project_root),
            )
            effective_summary = filtered.filtered_summary
            baseline_metadata = filtered.metadata

        report = RunReport.from_summary(
            effective_summary,
            level=level_name,
            project_root=str(project_root),
            registry=registry,
            sort_actionable_by_remediation_order=True,
            verbose=args.verbose,
        )
        report.baseline_filter = baseline_metadata

        sarif_requested = getattr(args, "sarif_output", False)
        output_file = getattr(args, "output_file", None)
        json_file = getattr(args, "json_file", None)

        # Log files are needed by both console and JSON.  SARIF doesn't
        # reference them but writing is cheap and idempotent, so do it
        # unconditionally when we have a project root.  Writing BEFORE
        # dispatch means adapters read log_files, never create them.
        report.write_logs()

        # --json-file is orthogonal to everything else.  When set,
        # always write JSON to that path, regardless of the primary
        # output mode.  This enables console + SARIF + JSON from one
        # run.
        if json_file:
            json_output = JsonAdapter.render(report)
            json_path = Path(json_file)
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(
                json.dumps(json_output, separators=(",", ":")),
                encoding="utf-8",
            )

        # SARIF emission is orthogonal to the json/console choice — it's
        # a third output format with its own shape.  Handle it first;
        # fall through to human-facing output unless SARIF goes to
        # stdout (in which case mixing would corrupt both streams).
        if sarif_requested:
            sarif_doc = SarifAdapter.render(report)
            payload = json.dumps(sarif_doc, indent=2)
            if output_file:
                Path(output_file).write_text(payload, encoding="utf-8")
                # SARIF went to a file — human output continues below.
            else:
                print(payload)
                return 0 if effective_summary.all_passed else 1

        if json_mode:
            output = JsonAdapter.render(report)
            json_payload = json.dumps(output, separators=(",", ":"))
            if output_file and not sarif_requested:
                # Mirror JSON to disk for archival, but keep stdout payload
                # so callers can consume it directly in pipelines.
                Path(output_file).write_text(json_payload, encoding="utf-8")
            print(json_payload)
        else:
            ConsoleAdapter(report).render()

        return 0 if effective_summary.all_passed else 1
    finally:
        # Ensure display is stopped on any exit
        if dynamic_display:
            dynamic_display.stop()


# ─── Top-level commands ──────────────────────────────────────────────────


def cmd_swab(args: argparse.Namespace) -> int:
    """Handle the swab command (quick, every-commit validation)."""
    ensure_checks_registered()

    # Explicit -g overrides level-based discovery; skip state hook for partial runs.
    explicit = _parse_quality_gates(args)
    if explicit:
        return _run_validation(args, explicit, None)

    from slopmop.checks.custom import register_custom_gates
    from slopmop.sm import load_config

    project_root = Path(getattr(args, "project_root", "."))
    if getattr(args, "json_file", None) is None:
        args.json_file = _default_json_artifact_path(project_root, "last_swab.json")

    config = load_config(project_root)
    register_custom_gates(config)
    registry = get_registry()
    gate_names = registry.get_gate_names_for_level(GateLevel.SWAB, config)
    exit_code = _run_validation(
        args,
        gate_names,
        "swab",
        preloaded_config=config,
        custom_gates_registered=True,
    )

    try:
        from slopmop.workflow.hooks import on_swab_complete

        on_swab_complete(
            Path(getattr(args, "project_root", ".")), passed=exit_code == 0
        )
    except Exception:
        pass

    return exit_code


def cmd_scour(args: argparse.Namespace) -> int:
    """Handle the scour command (thorough, PR-readiness validation)."""
    ensure_checks_registered()

    # Explicit -g overrides level-based discovery; skip state hook for partial runs.
    explicit = _parse_quality_gates(args)
    if explicit:
        return _run_validation(args, explicit, None)

    project_root = Path(getattr(args, "project_root", "."))
    if getattr(args, "json_file", None) is None:
        args.json_file = _default_json_artifact_path(project_root, "last_scour.json")

    from slopmop.checks.custom import register_custom_gates
    from slopmop.sm import load_config

    config = load_config(project_root)
    register_custom_gates(config)
    registry = get_registry()
    gate_names = registry.get_gate_names_for_level(GateLevel.SCOUR, config)
    exit_code = _run_validation(
        args,
        gate_names,
        "scour",
        preloaded_config=config,
        custom_gates_registered=True,
    )

    try:
        from slopmop.workflow.hooks import on_scour_complete

        config = _load_config_for_hook(project_root)
        disabled_gates = config.get("disabled_gates")
        all_gates_enabled = not disabled_gates
        on_scour_complete(
            project_root,
            passed=exit_code == 0,
            all_gates_enabled=all_gates_enabled,
        )
    except Exception:
        pass

    return exit_code


def _load_config_for_hook(project_root: Path) -> Dict[str, Any]:
    """Load raw config dict for hook use — never raises."""
    try:
        from slopmop.sm import load_config

        return load_config(project_root)
    except Exception:
        return {}
