"""sm - Slop-Mop CLI with verb-based interface.

Usage:
    sm validate [--quality-gates GATES] [--self] [--verbose] [--quiet]
    sm validate <profile> [--verbose] [--quiet]
    sm config [--show] [--enable GATE] [--disable GATE] [--json FILE]
    sm init [--config FILE] [--non-interactive]
    sm commit-hooks status
    sm commit-hooks install <profile>
    sm commit-hooks uninstall
    sm ci [PR_NUMBER] [--watch]
    sm help [GATE]

Verbs:
    validate      Run quality gate validation
    config        View or update configuration
    init          Interactive setup and project configuration
    commit-hooks  Manage git pre-commit hooks
    ci            Check CI status for current PR
    help          Show help for quality gates
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from slopmop.constants import PROJECT_ROOT_HELP

logger = logging.getLogger(__name__)


def load_config(project_root: Path) -> Dict[str, Any]:
    """Load configuration from .sb_config.json.

    Args:
        project_root: Path to project root directory

    Returns:
        Configuration dictionary, or empty dict if not found
    """
    config_file = os.environ.get("SB_CONFIG_FILE")
    if config_file:
        config_path = Path(config_file)
    else:
        config_path = project_root / ".sb_config.json"

    if config_path.exists():
        try:
            return json.loads(config_path.read_text())
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse config: {e}")
            return {}
    return {}


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for CLI."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def _add_validate_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the validate subcommand parser."""
    validate_parser = subparsers.add_parser(
        "validate",
        help="Run quality gate validation",
        description="Run quality gate validation on the target project.",
    )
    validate_parser.add_argument(
        "profile",
        nargs="?",
        default=None,
        help="Profile to run: commit, pr, quick, python, javascript, e2e",
    )
    validate_parser.add_argument(
        "--quality-gates",
        "-g",
        nargs="+",
        metavar="GATE",
        help="Specific quality gates to run (comma-separated or space-separated)",
    )
    validate_parser.add_argument(
        "--self",
        action="store_true",
        dest="self_validate",
        help="Run validation on slopmop itself",
    )
    validate_parser.add_argument(
        "--project-root",
        type=str,
        default=".",
        help=PROJECT_ROOT_HELP,
    )
    validate_parser.add_argument(
        "--no-auto-fix",
        action="store_true",
        help="Disable automatic fixing of issues",
    )
    validate_parser.add_argument(
        "--no-fail-fast",
        action="store_true",
        help="Continue running checks even after failures",
    )
    validate_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )
    validate_parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Minimal output (only show failures)",
    )
    validate_parser.add_argument(
        "--static",
        action="store_true",
        help="Disable dynamic display (use static line-by-line output)",
    )
    validate_parser.add_argument(
        "--clear-history",
        action="store_true",
        help="Clear all timing history before running",
    )


def _add_config_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the config subcommand parser."""
    config_parser = subparsers.add_parser(
        "config",
        help="View or update configuration",
        description="View or update quality gate configuration.",
    )
    config_parser.add_argument(
        "--show",
        action="store_true",
        help="Show current configuration and enabled gates",
    )
    config_parser.add_argument(
        "--enable",
        metavar="GATE",
        help="Enable a specific quality gate",
    )
    config_parser.add_argument(
        "--disable",
        metavar="GATE",
        help="Disable a specific quality gate",
    )
    config_parser.add_argument(
        "--include-dir",
        metavar="CATEGORY:DIR",
        help="Add directory to include list (e.g., python:src or quality:lib)",
    )
    config_parser.add_argument(
        "--exclude-dir",
        metavar="CATEGORY:DIR",
        help="Add directory to exclude list (e.g., overconfidence:py-tests or quality:vendor)",
    )
    config_parser.add_argument(
        "--json",
        metavar="FILE",
        help="Update configuration from JSON file",
    )
    config_parser.add_argument(
        "--project-root",
        type=str,
        default=".",
        help=PROJECT_ROOT_HELP,
    )


def _add_help_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the help subcommand parser."""
    help_parser = subparsers.add_parser(
        "help",
        help="Show help for quality gates",
        description="Show detailed help for quality gates.",
    )
    help_parser.add_argument(
        "gate",
        nargs="?",
        default=None,
        help="Specific gate to show help for (omit for all gates)",
    )


def _add_init_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the init subcommand parser."""
    init_parser = subparsers.add_parser(
        "init",
        help="Interactive setup and project configuration",
        description="Auto-detect project type and configure slopmop.",
    )
    init_parser.add_argument(
        "--config",
        "-c",
        metavar="FILE",
        help="Pre-populated config file (setup_config.json) for non-interactive setup",
    )
    init_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip prompts, use detected defaults or config file",
    )
    init_parser.add_argument(
        "--project-root",
        type=str,
        default=".",
        help=PROJECT_ROOT_HELP,
    )


def _add_hooks_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the commit-hooks subcommand parser."""
    hooks_parser = subparsers.add_parser(
        "commit-hooks",
        help="Manage git pre-commit hooks",
        description="Install, uninstall, or check status of sm-managed git hooks.",
    )
    hooks_subparsers = hooks_parser.add_subparsers(
        dest="hooks_action",
        help="Hook management action",
    )

    # commit-hooks status
    hooks_status = hooks_subparsers.add_parser(
        "status",
        help="Show currently installed commit hooks",
    )
    hooks_status.add_argument(
        "--project-root",
        type=str,
        default=".",
        help=PROJECT_ROOT_HELP,
    )

    # commit-hooks install
    hooks_install = hooks_subparsers.add_parser(
        "install",
        help="Install a pre-commit hook that runs the specified profile",
    )
    hooks_install.add_argument(
        "profile",
        help="Profile to run on commit (e.g., commit, quick, pr)",
    )
    hooks_install.add_argument(
        "--project-root",
        type=str,
        default=".",
        help=PROJECT_ROOT_HELP,
    )

    # commit-hooks uninstall
    hooks_uninstall = hooks_subparsers.add_parser(
        "uninstall",
        help="Remove all sm-managed commit hooks",
    )
    hooks_uninstall.add_argument(
        "--project-root",
        type=str,
        default=".",
        help=PROJECT_ROOT_HELP,
    )


def _add_ci_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the ci subcommand parser."""
    ci_parser = subparsers.add_parser(
        "ci",
        help="Check CI status for current PR",
        description="Check if CI checks are passing on the current PR.",
    )
    ci_parser.add_argument(
        "pr_number",
        nargs="?",
        type=int,
        default=None,
        help="PR number to check (auto-detects from current branch if omitted)",
    )
    ci_parser.add_argument(
        "--watch",
        "-w",
        action="store_true",
        help="Poll CI status until all checks complete",
    )
    ci_parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Polling interval in seconds (default: 30)",
    )
    ci_parser.add_argument(
        "--project-root",
        type=str,
        default=".",
        help=PROJECT_ROOT_HELP,
    )


def _add_status_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the status subcommand parser."""
    status_parser = subparsers.add_parser(
        "status",
        help="Run all gates and show full report card",
        description="Run all gates without fail-fast and print a report card.",
    )
    status_parser.add_argument(
        "profile",
        nargs="?",
        default="pr",
        help="Profile to report on (default: pr)",
    )
    status_parser.add_argument(
        "--project-root",
        type=str,
        default=".",
        help=PROJECT_ROOT_HELP,
    )
    status_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )
    status_parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Minimal output (report card only)",
    )
    status_parser.add_argument(
        "--static",
        action="store_true",
        help="Disable dynamic display (use static line-by-line output)",
    )


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for sm CLI."""
    parser = argparse.ArgumentParser(
        prog="./sm",
        description="""
🪣 sm - Slop-Mop Quality Gate Framework

A language-agnostic, bolt-on code validation tool designed to catch AI-generated
slop before it lands in your codebase. Provides fast, actionable feedback for
both human developers and AI coding assistants.

Verbs:
  validate    Run quality gate validation on target project
  config      View or update quality gate configuration
  help        Show detailed help for quality gates

Quick Start:
  1. Add slop-mop as a git submodule
  2. Run: ./slop-mop/scripts/setup.sh (creates venv, installs tools, adds ./sm)
  3. Run: ./sm init (auto-detect project, write config)
  4. Run: ./sm validate commit (run quality gates)

Examples:
  ./sm validate                           Run full validation suite
  ./sm validate commit                    Run commit profile (fast)
  ./sm validate pr --verbose              Run PR profile with details
  ./sm validate --quality-gates python-tests,python-coverage
  ./sm validate --self                    Validate slopmop itself
  ./sm config --show                      Show current configuration
  ./sm config --enable python-security    Enable a quality gate
  ./sm help python-lint-format            Show help for specific gate
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="verb", help="Command to run")

    _add_validate_parser(subparsers)
    _add_status_parser(subparsers)
    _add_config_parser(subparsers)
    _add_help_parser(subparsers)
    _add_init_parser(subparsers)
    _add_hooks_parser(subparsers)
    _add_ci_parser(subparsers)

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.0.0",
    )

    return parser


def main(args: Optional[List[str]] = None) -> int:
    """Main entry point for sm CLI."""
    from slopmop.cli import (
        cmd_ci,
        cmd_commit_hooks,
        cmd_config,
        cmd_help,
        cmd_init,
        cmd_status,
        cmd_validate,
    )

    parser = create_parser()
    parsed_args = parser.parse_args(args)

    # Setup logging
    if hasattr(parsed_args, "verbose") and parsed_args.verbose:
        setup_logging(verbose=True)
    else:
        setup_logging(verbose=False)

    # Handle verbs
    if parsed_args.verb == "validate":
        return cmd_validate(parsed_args)
    elif parsed_args.verb == "status":
        return cmd_status(parsed_args)
    elif parsed_args.verb == "config":
        return cmd_config(parsed_args)
    elif parsed_args.verb == "help":
        return cmd_help(parsed_args)
    elif parsed_args.verb == "init":
        return cmd_init(parsed_args)
    elif parsed_args.verb == "commit-hooks":
        return cmd_commit_hooks(parsed_args)
    elif parsed_args.verb == "ci":
        return cmd_ci(parsed_args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
