"""Validation commands for slop-mop CLI.

Provides ``sm swab`` (quick, every-commit) and ``sm scour`` (thorough, PR)
top-level commands.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional, cast

from slopmop.checks import ensure_checks_registered
from slopmop.checks.base import GateLevel
from slopmop.core.executor import CheckExecutor
from slopmop.core.registry import get_registry
from slopmop.core.result import CheckResult, CheckStatus
from slopmop.reporting.console import ConsoleReporter
from slopmop.reporting.dynamic import DynamicDisplay
from slopmop.reporting.timings import clear_timings, load_timing_averages


def _is_json_mode(args: argparse.Namespace) -> bool:
    """Determine whether output should be JSON.

    Resolution order:
    1. Explicit --json → True
    2. Explicit --no-json → False
    3. Auto-detect: not a TTY → True (piped to AI agent)
    4. Default: False (interactive terminal)
    """
    explicit = getattr(args, "json_output", None)
    if explicit is not None:
        return explicit
    return not sys.stdout.isatty()


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
    from slopmop.sm import load_config

    # Determine project root
    project_root = Path(args.project_root).resolve()

    if not project_root.is_dir():
        print(f"❌ Project root not found: {project_root}")
        return 1

    json_mode = _is_json_mode(args)

    # Clear timing history if requested
    if getattr(args, "clear_history", False):
        if clear_timings(str(project_root)):
            if not args.quiet and not json_mode:
                print("🗑️  Timing history cleared")

    # Create executor
    # Scour never uses fail-fast — it runs every gate to give the full picture.
    # Swab respects the --no-fail-fast flag (default: fail-fast ON).
    registry = get_registry()
    use_fail_fast = False if level_name == "scour" else not args.no_fail_fast
    executor = CheckExecutor(
        registry=registry,
        fail_fast=use_fail_fast,
    )

    # Set up progress reporting
    reporter = ConsoleReporter(
        quiet=args.quiet,
        verbose=args.verbose,
        verb=level_name,
        project_root=str(project_root),
    )

    # Load configuration (must happen early — swabbing-time default lives here)
    config = load_config(project_root)

    # Register user-defined custom gates from config
    from slopmop.checks.custom import register_custom_gates

    custom_names = register_custom_gates(config)

    # Custom gates are registered AFTER the initial gate_names list was
    # computed by cmd_swab/cmd_scour.  Append any newly registered names
    # so they actually run.  (Explicit -g lists are left untouched.)
    if level_name is not None and custom_names:
        gates = list(gates) + custom_names

    # Determine if we should use dynamic display
    # JSON mode suppresses all interactive output
    use_dynamic = (
        not json_mode
        and sys.stdout.isatty()
        and not os.environ.get("NO_COLOR")
        and not args.quiet
        and not getattr(args, "static", False)
    )

    # Handle time budget (swabbing-time).
    # Only applies to swab, not scour.  Read from CLI flag first,
    # fall back to config value.  <= 0 means no limit.
    swabbing_time: Optional[int] = getattr(args, "swabbing_time", None)
    if swabbing_time is None:
        config_val = config.get("swabbing_time")
        if isinstance(config_val, (int, float)) and config_val > 0:
            swabbing_time = int(config_val)

    # Only enforce for swab runs
    if level_name != "swab":
        swabbing_time = None

    # Print header BEFORE starting dynamic display
    if not args.quiet and not json_mode:
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
    elif not json_mode:
        # Fall back to traditional reporter (no progress in JSON mode)
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
        )

        # Stop dynamic display before printing summary
        if dynamic_display:
            dynamic_display.stop()
            dynamic_display.save_historical_timings(str(project_root))

            # Deferred failures are NOT printed here — print_summary()
            # already shows failure details via _print_failure_sections.
            # Printing them individually via on_check_complete() too
            # caused double-reported failures (token sink #1).

        # SARIF emission is orthogonal to the json/console choice — it's
        # a third output format with its own shape.  We handle it first
        # and write to the requested destination, then fall through to
        # whatever human-facing output was selected.  This lets CI do
        # both: SARIF to a file (for upload-sarif) AND human output to
        # the job log (for someone reading the Actions run).
        sarif_requested = getattr(args, "sarif_output", False)
        output_file = getattr(args, "output_file", None)
        if sarif_requested:
            from slopmop.reporting.sarif import SarifReporter

            sarif = SarifReporter(str(project_root)).generate(summary)
            payload = json.dumps(sarif, indent=2)
            if output_file:
                Path(output_file).write_text(payload, encoding="utf-8")
                # When SARIF goes to a file, console output continues
                # below — the human still wants to see pass/fail.
            else:
                # SARIF to stdout is terminal: we emitted the payload,
                # nothing more to say.  Mixing SARIF and console text
                # on the same stream would corrupt both.
                print(payload)
                return 0 if summary.all_passed else 1

        if json_mode:
            # Write failure/error logs the same way the human path does,
            # so JSON consumers can reference the same log files.
            log_files: dict[str, str] = {}
            for result in summary.results:
                if result.failed or result.status == CheckStatus.ERROR:
                    log_path = reporter.write_failure_log(result)
                    if log_path:
                        log_files[result.name] = log_path

            # Build enriched JSON — everything the human display shows,
            # structured for machine consumption.
            output = summary.to_dict()

            # Schema version — lets consumers look up field semantics
            # without the JSON needing to self-document every key.
            output["schema"] = "slopmop/v1"

            # Add run context
            if level_name:
                output["level"] = level_name

            # Attach log file paths to individual results
            # (results only contains non-passing checks in compact mode)
            if log_files and isinstance(output.get("results"), list):
                for entry in cast(List[dict[str, object]], output["results"]):
                    gate_name = str(entry.get("name", ""))
                    if gate_name in log_files:
                        entry["log_file"] = log_files[gate_name]

            # Add next-steps guidance (same commands the human display shows)
            failed_results = [
                r for r in summary.results if r.status == CheckStatus.FAILED
            ]
            error_results = [
                r for r in summary.results if r.status == CheckStatus.ERROR
            ]
            first_failure = (
                failed_results[0]
                if failed_results
                else (error_results[0] if error_results else None)
            )
            if first_failure:
                output["next_steps"] = [
                    f"sm swab -g {first_failure.name} --verbose",
                ]

            json_payload = json.dumps(output, separators=(",", ":"))
            if output_file and not sarif_requested:
                # --output-file with --json (but not --sarif) redirects
                # JSON there.  When BOTH --sarif and --json are set with
                # one --output-file, SARIF wins the file and JSON goes
                # to stdout — the file can only hold one format.
                Path(output_file).write_text(json_payload, encoding="utf-8")
            else:
                print(json_payload)
        else:
            reporter.print_summary(summary)

        return 0 if summary.all_passed else 1
    finally:
        # Ensure display is stopped on any exit
        if dynamic_display:
            dynamic_display.stop()


# ─── Top-level commands ──────────────────────────────────────────────────


def cmd_swab(args: argparse.Namespace) -> int:
    """Handle the swab command (quick, every-commit validation)."""
    ensure_checks_registered()

    # Explicit -g overrides level-based discovery
    explicit = _parse_quality_gates(args)
    if explicit:
        return _run_validation(args, explicit, None)

    registry = get_registry()
    gate_names = registry.get_gate_names_for_level(GateLevel.SWAB)
    return _run_validation(args, gate_names, "swab")


def cmd_scour(args: argparse.Namespace) -> int:
    """Handle the scour command (thorough, PR-readiness validation)."""
    ensure_checks_registered()

    # Explicit -g overrides level-based discovery
    explicit = _parse_quality_gates(args)
    if explicit:
        return _run_validation(args, explicit, None)

    registry = get_registry()
    gate_names = registry.get_gate_names_for_level(GateLevel.SCOUR)
    return _run_validation(args, gate_names, "scour")
