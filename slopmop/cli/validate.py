"""Validate command for slop-mop CLI."""

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

from slopmop.checks import ensure_checks_registered
from slopmop.core.executor import CheckExecutor
from slopmop.core.registry import get_registry
from slopmop.reporting.console import ConsoleReporter


def _setup_self_validation(project_root: Path) -> str:
    """Set up isolated config for self-validation.

    Returns the temp directory path.
    """
    from slopmop.utils.generate_base_config import generate_base_config

    temp_config_dir = tempfile.mkdtemp(prefix="sb_self_validate_")
    temp_config_file = Path(temp_config_dir) / ".sb_config.json"

    # Generate config with auto-detection
    base_config = generate_base_config()

    # Enable Python gates for slopmop itself
    base_config["python"]["enabled"] = True
    for gate in ["lint-format", "tests", "coverage", "static-analysis"]:
        if gate in base_config["python"]["gates"]:
            base_config["python"]["gates"][gate]["enabled"] = True

    # Set test_dirs
    if "tests" in base_config["python"]["gates"]:
        base_config["python"]["gates"]["tests"]["test_dirs"] = ["tests"]

    # Set coverage threshold for self-validation
    if "coverage" in base_config["python"]["gates"]:
        base_config["python"]["gates"]["coverage"]["threshold"] = 80

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


def _print_header(
    project_root: Path, gates: List[str], args: argparse.Namespace
) -> None:
    """Print validation header."""
    print("\n🧹 ./sm validate - Quality Gate Validation")
    print("=" * 60)
    from slopmop.reporting import print_project_header

    print_project_header(str(project_root))
    if args.self_validate:
        print("🔄 Mode: Self-validation (using isolated config)")
    print(f"🔍 Quality Gates: {', '.join(gates)}")
    print("=" * 60)
    print()


def cmd_validate(args: argparse.Namespace) -> int:
    """Handle the validate command."""
    # Import here to avoid circular imports
    from slopmop.sm import load_config

    ensure_checks_registered()

    # Determine project root
    if args.self_validate:
        project_root = Path(__file__).parent.parent.parent.resolve()
    else:
        project_root = Path(args.project_root).resolve()

    if not project_root.is_dir():
        print(f"❌ Project root not found: {project_root}")
        return 1

    # Set up self-validation if needed
    temp_config_dir = None
    if args.self_validate:
        temp_config_dir = _setup_self_validation(project_root)

    # Determine gates
    gates, profile_name = _determine_gates(args)

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
    )
    executor.set_progress_callback(reporter.on_check_complete)

    # Print header
    if not args.quiet:
        _print_header(project_root, gates, args)

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

        # Print summary
        reporter.print_summary(summary)
        return 0 if summary.all_passed else 1
    finally:
        if temp_config_dir:
            _cleanup_self_validation(temp_config_dir)
