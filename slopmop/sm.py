"""sm - Slop-Mop CLI with verb-based interface.

Usage:
    sm swab [--quality-gates GATES] [--self] [--verbose] [--quiet]
    sm scour [--quality-gates GATES] [--self] [--verbose] [--quiet]
    sm config [--show] [--enable GATE] [--disable GATE] [--json FILE]
    sm init [--config FILE] [--non-interactive]
    sm commit-hooks status
    sm commit-hooks install
    sm commit-hooks uninstall
    sm ci [PR_NUMBER] [--watch]
    sm help [GATE]

    (deprecated)
    sm validate [<profile>] [--quality-gates GATES] [--self]

Verbs:
    swab          Quick validation (every commit)
    scour         Thorough validation (PR readiness — superset of swab)
    validate      (deprecated) Use swab or scour instead
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

from slopmop import __version__
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


def _add_validation_flags(parser: argparse.ArgumentParser) -> None:
    """Add the common validation flags shared by swab, scour, and validate."""
    parser.add_argument(
        "--quality-gates",
        "-g",
        nargs="+",
        metavar="GATE",
        help="Specific quality gates to run (comma-separated or space-separated)",
    )
    parser.add_argument(
        "--self",
        action="store_true",
        dest="self_validate",
        help="Run validation on slopmop itself",
    )
    parser.add_argument(
        "--project-root",
        type=str,
        default=".",
        help=PROJECT_ROOT_HELP,
    )
    parser.add_argument(
        "--no-auto-fix",
        action="store_true",
        help="Disable automatic fixing of issues",
    )
    parser.add_argument(
        "--no-fail-fast",
        action="store_true",
        help="Continue running checks even after failures",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Minimal output (only show failures)",
    )
    parser.add_argument(
        "--static",
        action="store_true",
        help="Disable dynamic display (use static line-by-line output)",
    )
    parser.add_argument(
        "--clear-history",
        action="store_true",
        help="Clear all timing history before running",
    )
    parser.add_argument(
        "--swabbing-time",
        type=int,
        metavar="SECONDS",
        default=None,
        help="Time budget in seconds — skip gates that won't fit (preview)",
    )


def _add_swab_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the swab subcommand parser (quick, every-commit validation)."""
    swab_parser = subparsers.add_parser(
        "swab",
        help="Quick validation (every commit)",
        description=(
            "Run quick quality gate validation. Runs all swab-level gates — "
            "the checks you want on every commit. Use -g to override with "
            "specific gates."
        ),
    )
    _add_validation_flags(swab_parser)


def _add_scour_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the scour subcommand parser (thorough, PR-readiness validation)."""
    scour_parser = subparsers.add_parser(
        "scour",
        help="Thorough validation (PR readiness)",
        description=(
            "Run thorough quality gate validation. Runs ALL gates (swab + "
            "scour-level) — the full suite for PR readiness. Use -g to "
            "override with specific gates."
        ),
    )
    _add_validation_flags(scour_parser)


def _add_validate_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the validate subcommand parser (DEPRECATED)."""
    validate_parser = subparsers.add_parser(
        "validate",
        help="(deprecated) Use 'swab' or 'scour' instead",
        description=(
            "DEPRECATED: Use 'sm swab' (quick) or 'sm scour' (thorough) instead."
        ),
    )
    validate_parser.add_argument(
        "profile",
        nargs="?",
        default=None,
        help="Profile to run: commit, pr, quick, python, javascript, e2e",
    )
    _add_validation_flags(validate_parser)


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
        help="Install a pre-commit hook that runs sm swab",
    )
    hooks_install.add_argument(
        "profile",
        nargs="?",
        default="swab",
        help="Command to run on commit: swab (default), scour, or legacy profile",
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
        default="scour",
        help="Level or alias to report on (default: scour). Accepts swab, scour, or any alias.",
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
  swab        Quick validation — runs on every commit
  scour       Thorough validation — PR readiness (superset of swab)
  validate    (deprecated) Use swab or scour instead
  config      View or update quality gate configuration
  help        Show detailed help for quality gates

Quick Start:
  1. Add slop-mop as a git submodule
  2. Run: ./slop-mop/scripts/setup.sh (creates venv, installs tools, adds ./sm)
  3. Run: ./sm init (auto-detect project, write config)
  4. Run: ./sm swab (run quick quality gates)

Examples:
  ./sm swab                               Quick validation (every commit)
  ./sm scour                              Thorough validation (PR readiness)
  ./sm scour --self                       Validate slopmop itself
  ./sm swab -g python,quality             Run specific gate groups
  ./sm scour --verbose                    Thorough with details
  ./sm config --show                      Show current configuration
  ./sm config --enable python-security    Enable a quality gate
  ./sm help python-lint-format            Show help for specific gate
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="verb", help="Command to run")

    _add_swab_parser(subparsers)
    _add_scour_parser(subparsers)
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
        version=f"%(prog)s {__version__}",
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
        cmd_scour,
        cmd_status,
        cmd_swab,
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
    if parsed_args.verb == "swab":
        return cmd_swab(parsed_args)
    elif parsed_args.verb == "scour":
        return cmd_scour(parsed_args)
    elif parsed_args.verb == "validate":
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
