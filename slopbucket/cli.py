"""Command-line interface for slopbucket.

This module provides the main entry point for the slopbucket CLI tool.
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import List, Optional

from slopbucket.core.executor import CheckExecutor
from slopbucket.core.registry import get_registry
from slopbucket.core.result import ExecutionSummary
from slopbucket.reporting.console import ConsoleReporter

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for CLI.

    Args:
        verbose: Enable verbose (DEBUG) logging
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for slopbucket CLI.

    Returns:
        Configured ArgumentParser
    """
    parser = argparse.ArgumentParser(
        prog="slopbucket",
        description="""
🪣 slopbucket - AI-Focused Quality Gate Framework

A language-agnostic, bolt-on code validation tool designed to catch AI-generated
slop before it lands in your codebase. Provides fast, actionable feedback for
both human developers and AI coding assistants.

Philosophy:
  - Fail fast: Stop at the first failure to save time
  - Maximum value, minimum time: Prioritize quick, high-impact checks
  - AI-friendly output: Clear errors with exact fixes
  - Zero configuration required: Works out of the box
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --checks commit          Run fast commit validation
  %(prog)s --checks pr              Run full PR validation (all checks)
  %(prog)s --checks python-lint-format python-tests
                                    Run specific checks
  %(prog)s --list-checks            List all available checks
  %(prog)s --list-aliases           List all check aliases

Check Aliases (expand to predefined check groups):
  commit      Fast validation for commits (lint, tests, coverage)
  pr          Full PR validation (all checks)
  quick       Ultra-fast lint-only check
  security    Security-focused checks only

For more information, see: https://github.com/ScienceIsNeato/slopbucket
""",
    )

    # Required argument group
    checks_group = parser.add_argument_group("checks")
    checks_group.add_argument(
        "--checks",
        nargs="+",
        metavar="CHECK",
        help="Checks or aliases to run. Examples: commit, pr, python-lint-format",
    )

    # Options
    options_group = parser.add_argument_group("options")
    options_group.add_argument(
        "--project-root",
        type=str,
        default=".",
        help="Project root directory (default: current directory)",
    )
    options_group.add_argument(
        "--no-auto-fix",
        action="store_true",
        help="Disable automatic fixing of issues",
    )
    options_group.add_argument(
        "--no-fail-fast",
        action="store_true",
        help="Continue running checks even after failures",
    )
    options_group.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )
    options_group.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Minimal output (only show failures)",
    )

    # Info commands
    info_group = parser.add_argument_group("information")
    info_group.add_argument(
        "--list-checks",
        action="store_true",
        help="List all available checks",
    )
    info_group.add_argument(
        "--list-aliases",
        action="store_true",
        help="List all check aliases",
    )
    info_group.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.0.0",
    )

    return parser


def list_checks() -> None:
    """Print all available checks."""
    registry = get_registry()
    checks = registry.list_checks()

    print("\n📋 Available Checks:")
    print("=" * 60)

    if not checks:
        print("  No checks registered. Run setup to initialize checks.")
        return

    for name in sorted(checks):
        definition = registry.get_definition(name)
        if definition:
            print(f"  {definition.name}")
            if definition.depends_on:
                print(f"      depends on: {', '.join(definition.depends_on)}")
        else:
            print(f"  {name}")

    print()


def list_aliases() -> None:
    """Print all check aliases."""
    registry = get_registry()
    aliases = registry.list_aliases()

    print("\n📦 Check Aliases:")
    print("=" * 60)

    if not aliases:
        print("  No aliases registered.")
        return

    for alias, checks in sorted(aliases.items()):
        print(f"\n  {alias}:")
        for check in checks:
            print(f"    - {check}")

    print()


def print_summary(summary: ExecutionSummary, quiet: bool = False) -> int:
    """Print execution summary and return exit code.

    Args:
        summary: Execution summary
        quiet: Minimal output mode

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    reporter = ConsoleReporter(quiet=quiet)
    reporter.print_summary(summary)

    return 0 if summary.all_passed else 1


def run_checks(
    check_names: List[str],
    project_root: str,
    auto_fix: bool = True,
    fail_fast: bool = True,
    verbose: bool = False,
    quiet: bool = False,
) -> int:
    """Run specified checks and return exit code.

    Args:
        check_names: Checks or aliases to run
        project_root: Project root directory
        auto_fix: Whether to auto-fix issues
        fail_fast: Stop on first failure
        verbose: Verbose output
        quiet: Minimal output

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    # Validate project root
    root_path = Path(project_root).resolve()
    if not root_path.is_dir():
        print(f"❌ Project root not found: {project_root}")
        return 1

    # Initialize registry with checks
    from slopbucket.checks import register_all_checks

    register_all_checks()

    # Create executor
    registry = get_registry()
    executor = CheckExecutor(
        registry=registry,
        fail_fast=fail_fast,
    )

    # Set up progress reporting
    reporter = ConsoleReporter(quiet=quiet, verbose=verbose)
    executor.set_progress_callback(reporter.on_check_complete)

    # Print header
    if not quiet:
        print("\n🪣 slopbucket - Quality Gate Framework")
        print("=" * 60)
        print(f"📂 Project: {root_path}")
        print(f"🔍 Checks: {', '.join(check_names)}")
        print("=" * 60)
        print()

    # Run checks
    start_time = time.time()
    summary = executor.run_checks(
        project_root=str(root_path),
        check_names=check_names,
        auto_fix=auto_fix,
    )

    # Print summary
    return print_summary(summary, quiet=quiet)


def main(args: Optional[List[str]] = None) -> int:
    """Main entry point for slopbucket CLI.

    Args:
        args: Command-line arguments (default: sys.argv[1:])

    Returns:
        Exit code
    """
    parser = create_parser()
    parsed_args = parser.parse_args(args)

    # Setup logging
    setup_logging(verbose=parsed_args.verbose)

    # Handle info commands
    if parsed_args.list_checks:
        # Initialize checks first
        from slopbucket.checks import register_all_checks

        register_all_checks()
        list_checks()
        return 0

    if parsed_args.list_aliases:
        from slopbucket.checks import register_all_checks

        register_all_checks()
        list_aliases()
        return 0

    # Require --checks if not info command
    if not parsed_args.checks:
        parser.print_help()
        print("\n❌ Error: --checks is required")
        print("   Example: slopbucket --checks commit")
        return 1

    # Run checks
    return run_checks(
        check_names=parsed_args.checks,
        project_root=parsed_args.project_root,
        auto_fix=not parsed_args.no_auto_fix,
        fail_fast=not parsed_args.no_fail_fast,
        verbose=parsed_args.verbose,
        quiet=parsed_args.quiet,
    )


if __name__ == "__main__":
    sys.exit(main())
