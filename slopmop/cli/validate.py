"""Validate command for slop-mop CLI.

Provides ``sm swab`` (quick, every-commit) and ``sm scour`` (thorough, PR)
top-level commands, plus the legacy ``sm validate`` shim.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

from slopmop.checks import ensure_checks_registered
from slopmop.checks.base import GateLevel
from slopmop.core.executor import CheckExecutor
from slopmop.core.registry import get_registry
from slopmop.core.result import CheckResult, CheckStatus
from slopmop.reporting.console import ConsoleReporter
from slopmop.reporting.dynamic import DynamicDisplay
from slopmop.reporting.timings import clear_timings


def _setup_self_validation(project_root: Path) -> str:
    """Set up isolated config for self-validation.

    Returns the temp directory path.
    """
    from slopmop.utils.generate_base_config import generate_base_config

    temp_config_dir = tempfile.mkdtemp(prefix="sb_self_validate_")
    temp_config_file = Path(temp_config_dir) / ".sb_config.json"

    # Generate config with auto-detection
    base_config = generate_base_config()

    # Enable all gates that match the commit profile for slopmop itself.
    # Organized by flaw category — each gate listed explicitly so drift
    # between this config and the commit profile alias is obvious.

    # laziness: py-lint, complexity, dead-code
    if "laziness" in base_config:
        base_config["laziness"]["enabled"] = True
        gates = base_config["laziness"].get("gates", {})
        for gate in ["py-lint", "complexity", "dead-code"]:
            if gate in gates:
                gates[gate]["enabled"] = True

    # overconfidence: py-static-analysis, py-types, py-tests
    if "overconfidence" in base_config:
        base_config["overconfidence"]["enabled"] = True
        gates = base_config["overconfidence"].get("gates", {})
        for gate in ["py-tests", "py-static-analysis", "py-types"]:
            if gate in gates:
                gates[gate]["enabled"] = True
        if "py-tests" in gates:
            gates["py-tests"]["test_dirs"] = ["tests"]

    # deceptiveness: py-coverage, bogus-tests, gate-dodging
    if "deceptiveness" in base_config:
        base_config["deceptiveness"]["enabled"] = True
        gates = base_config["deceptiveness"].get("gates", {})
        for gate in ["py-coverage", "bogus-tests", "gate-dodging"]:
            if gate in gates:
                gates[gate]["enabled"] = True
        if "py-coverage" in gates:
            gates["py-coverage"]["threshold"] = 80

    # myopia: security-scan, source-duplication, string-duplication, loc-lock
    if "myopia" in base_config:
        base_config["myopia"]["enabled"] = True
        gates = base_config["myopia"].get("gates", {})
        for gate in [
            "security-scan",
            "source-duplication",
            "string-duplication",
            "loc-lock",
        ]:
            if gate in gates:
                gates[gate]["enabled"] = True

    # Write temp config
    temp_config_file.write_text(json.dumps(base_config, indent=2) + "\n")

    # Use the temp config for validation
    os.environ["SB_CONFIG_FILE"] = str(temp_config_file)

    return temp_config_dir


def _cleanup_self_validation(temp_config_dir: str) -> None:
    """Clean up self-validation temp directory."""
    os.environ.pop("SB_CONFIG_FILE", None)
    shutil.rmtree(temp_config_dir, ignore_errors=True)


def _determine_gates(args: argparse.Namespace) -> tuple[List[str], Optional[str]]:
    """Determine which gates to run and the profile name.

    Returns (gates_list, profile_name).
    """
    if args.profile:
        return [args.profile], args.profile
    elif args.quality_gates:
        gates: List[str] = []
        for gate in args.quality_gates:
            gates.extend(g.strip() for g in gate.split(",") if g.strip())
        return gates, None
    else:
        return ["commit"], "commit"


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
    project_root: Path, gates: List[str], args: argparse.Namespace
) -> None:
    """Print validation header."""
    print("\u2728 scanning the code for slop to mop")
    print()


def _setup_dynamic_display(
    executor: "CheckExecutor",
    reporter: "ConsoleReporter",
    quiet: bool,
    project_root: Path,
) -> "DynamicDisplay":
    """Configure and start the dynamic display, wiring all executor callbacks.

    Also adds a combined progress callback so failure details are printed via
    the console reporter even when the dynamic display is active.

    Args:
        executor: The check executor to wire callbacks onto.
        reporter: The console reporter (used for failure details).
        quiet: Whether to suppress output.
        project_root: Project root for loading historical timings.

    Returns:
        The started DynamicDisplay instance.
    """
    display = DynamicDisplay(quiet=quiet)
    display.load_historical_timings(str(project_root))
    display.start()
    executor.set_start_callback(display.on_check_start)
    executor.set_disabled_callback(display.on_check_disabled)
    executor.set_na_callback(display.on_check_not_applicable)
    executor.set_total_callback(display.set_total_checks)
    executor.set_pending_callback(display.register_pending_checks)

    # Combined callback: update display AND print failure details via reporter
    _reporter_cb = reporter.on_check_complete

    def _combined(result: CheckResult) -> None:
        display.on_check_complete(result)
        if result.failed or result.status == CheckStatus.ERROR:
            _reporter_cb(result)

    executor.set_progress_callback(_combined)
    return display


# ─── Shared execution pipeline ───────────────────────────────────────────


def _run_validation(
    args: argparse.Namespace,
    gates: List[str],
    profile_name: Optional[str],
) -> int:
    """Core validation pipeline shared by swab, scour, and validate.

    Args:
        args: Parsed CLI arguments (must have project_root, self_validate,
              quiet, verbose, no_fail_fast, no_auto_fix, static,
              clear_history flags).
        gates: List of gate names or aliases to run.
        profile_name: Display label (e.g. "swab", "scour", "commit").

    Returns:
        Exit code (0 = all passed, 1 = failures).
    """
    from slopmop.sm import load_config

    # Determine project root
    if args.self_validate:
        project_root = Path(__file__).parent.parent.parent.resolve()
    else:
        project_root = Path(args.project_root).resolve()

    if not project_root.is_dir():
        print(f"❌ Project root not found: {project_root}")
        return 1

    # Clear timing history if requested
    if getattr(args, "clear_history", False):
        if clear_timings(str(project_root)):
            if not args.quiet:
                print("🗑️  Timing history cleared")

    # Set up self-validation if needed
    temp_config_dir = None
    if args.self_validate:
        temp_config_dir = _setup_self_validation(project_root)

    # Create executor
    registry = get_registry()
    executor = CheckExecutor(
        registry=registry,
        fail_fast=not args.no_fail_fast,
    )

    # Set up progress reporting
    reporter = ConsoleReporter(
        quiet=args.quiet,
        verbose=args.verbose,
        profile=profile_name,
        project_root=str(project_root),
    )

    # Determine if we should use dynamic display
    use_dynamic = (
        sys.stdout.isatty()
        and not os.environ.get("NO_COLOR")
        and not args.quiet
        and not getattr(args, "static", False)
    )

    # Print header BEFORE starting dynamic display
    if not args.quiet:
        _print_header(project_root, gates, args)

    # Handle time budget (preview feature)
    swabbing_time = getattr(args, "swabbing_time", None)
    if swabbing_time is not None and not args.quiet:
        print(f"⏱️  Time budget: {swabbing_time}s (preview — not yet enforced)")
        print()

    # Set up dynamic display if appropriate
    dynamic_display: Optional[DynamicDisplay] = None
    if use_dynamic:
        dynamic_display = _setup_dynamic_display(
            executor, reporter, args.quiet, project_root
        )
    else:
        # Fall back to traditional reporter
        executor.set_progress_callback(reporter.on_check_complete)

    # Load configuration
    config = load_config(project_root)

    try:
        # Run checks
        summary = executor.run_checks(
            project_root=str(project_root),
            check_names=gates,
            config=config,
            auto_fix=not args.no_auto_fix,
        )

        # Stop dynamic display before printing summary
        if dynamic_display:
            dynamic_display.stop()
            dynamic_display.save_historical_timings(str(project_root))

        # Print summary
        reporter.print_summary(summary)
        return 0 if summary.all_passed else 1
    finally:
        # Ensure display is stopped on any exit
        if dynamic_display:
            dynamic_display.stop()
        if temp_config_dir:
            _cleanup_self_validation(temp_config_dir)


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


def cmd_validate(args: argparse.Namespace) -> int:
    """Handle the validate command (DEPRECATED — use swab/scour)."""
    ensure_checks_registered()

    # Deprecation warning
    print(
        "⚠️  'sm validate' is deprecated and will be removed in a future version.",
        file=sys.stderr,
    )

    gates, profile_name = _determine_gates(args)

    if profile_name == "pr":
        print("   Use 'sm scour' instead of 'sm validate pr'", file=sys.stderr)
    elif profile_name == "commit":
        print("   Use 'sm swab' instead of 'sm validate commit'", file=sys.stderr)
    else:
        print(
            "   Use 'sm swab' (quick) or 'sm scour' (thorough) instead",
            file=sys.stderr,
        )
    print(file=sys.stderr)

    return _run_validation(args, gates, profile_name)
