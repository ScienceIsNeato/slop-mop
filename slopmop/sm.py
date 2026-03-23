"""sm - Slop-Mop CLI with verb-based interface.

Usage:
    sm swab [--quality-gates GATES] [--verbose] [--quiet]
    sm scour [--quality-gates GATES] [--verbose] [--quiet]
    sm upgrade [--check] [--to-version VERSION]
    sm buff [PR_NUMBER]
    sm refit [--start | --iterate | --finish]
    sm agent install [--target TARGET] [--project-root PATH] [--force]
    sm config [--show] [--enable GATE] [--disable GATE] [--json FILE]
    sm init [--config FILE] [--non-interactive]
    sm commit-hooks status
    sm commit-hooks install
    sm commit-hooks uninstall
    sm help [GATE]

Verbs:
    swab          Quick validation (every commit)
    scour         Thorough validation (PR readiness — superset of swab)
    upgrade       Upgrade slop-mop and validate the result
    buff          Post-PR CI triage and next-step guidance
    refit         Repository onboarding — remediation planning and execution
    config        View or update configuration
    init          Interactive setup and project configuration
    agent         Install agent integration templates
    commit-hooks  Manage git pre-commit hooks
    help          Show help for quality gates
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

from slopmop import __version__
from slopmop.cli.parser_builders import (
    AgentParserBuilder,
    BuffParserBuilder,
    RefitParserBuilder,
)
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
        handlers=[logging.StreamHandler(sys.stderr)],
    )


def _add_output_flags(parser: argparse.ArgumentParser) -> None:
    """Add output-format and caching flags shared by validation verbs."""
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        default=None,
        help=(
            "Output results as JSON. Human-readable console output is the "
            "default; use --json for machine-oriented stdout."
        ),
    )
    parser.add_argument(
        "--no-json",
        dest="json_output",
        action="store_false",
        help="Force human-readable console output.",
    )
    parser.add_argument(
        "--sarif",
        dest="sarif_output",
        action="store_true",
        default=False,
        help=(
            "Emit SARIF 2.1.0 for GitHub Code Scanning. "
            "Writes to stdout unless --output-file is given. "
            "Upload with github/codeql-action/upload-sarif. "
            "In CI, also pass --no-auto-fix so the report describes "
            "the commit as-pushed, not as-would-be-after-formatting."
        ),
    )
    parser.add_argument(
        "--output-file",
        "-o",
        dest="output_file",
        metavar="PATH",
        default=None,
        help=(
            "Mirror structured output (--json or --sarif) to a file. "
            "Stdout output is unchanged."
        ),
    )
    parser.add_argument(
        "--json-file",
        dest="json_file",
        metavar="PATH",
        default=None,
        help=(
            "Write JSON results to a file, independent of the primary "
            "output mode. Allows emitting console + SARIF + JSON from "
            "a single run (e.g. --sarif -o scan.sarif --json-file results.json)."
        ),
    )
    parser.add_argument(
        "--no-cache",
        dest="no_cache",
        action="store_true",
        default=False,
        help=(
            "Disable fingerprint-based result caching. Forces all "
            "checks to run from scratch. Useful for troubleshooting "
            "or development."
        ),
    )


def _add_validation_flags(parser: argparse.ArgumentParser) -> None:
    """Add the common validation flags shared by swab, scour, and validate."""
    parser.add_argument(
        "--ignore-baseline-failures",
        action="store_true",
        help=(
            "After the run completes, downgrade failures already present "
            "in the local baseline snapshot. Checks still execute normally."
        ),
    )
    parser.add_argument(
        "--quality-gates",
        "-g",
        nargs="+",
        metavar="GATE",
        help="Specific quality gates to run (comma-separated or space-separated)",
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
        help=(
            "Time budget in seconds for swab runs. Gates with historical "
            "timing data are skipped when the budget would be exceeded. "
            "Overrides the config-file default. Set to 0 to disable."
        ),
    )
    _add_output_flags(parser)


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


def _add_buff_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the buff subcommand parser (post-PR validation loop)."""
    BuffParserBuilder(subparsers).build()


def _add_sail_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the sail subcommand parser (auto-advance workflow)."""
    sail_parser = subparsers.add_parser(
        "sail",
        help="Auto-advance the workflow — do the next obvious thing",
        description=(
            "Read the current workflow state and execute the next step. "
            "You don't need to know whether to swab, scour, or buff — "
            "sail figures it out."
        ),
    )
    sail_parser.add_argument(
        "--project-root",
        type=str,
        default=".",
        help=PROJECT_ROOT_HELP,
    )
    sail_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose output."
    )
    sail_parser.add_argument(
        "--quiet", "-q", action="store_true", help="Failures only."
    )
    sail_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit JSON output.",
    )
    sail_parser.add_argument(
        "--static", action="store_true", help="Disable dynamic display."
    )


def _add_refit_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the refit subcommand parser (structured remediation rail)."""
    RefitParserBuilder(subparsers).build()


def _add_upgrade_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the upgrade subcommand parser."""
    upgrade_parser = subparsers.add_parser(
        "upgrade",
        help="Upgrade slop-mop and validate the result",
        description=(
            "Upgrade the installed slop-mop package, back up local config/state, "
            "run built-in upgrade migrations, and validate the upgraded install."
        ),
    )
    upgrade_parser.add_argument(
        "--check",
        action="store_true",
        help="Show the upgrade plan without changing anything.",
    )
    upgrade_parser.add_argument(
        "--to-version",
        metavar="VERSION",
        help="Upgrade to a specific published slop-mop version.",
    )
    upgrade_parser.add_argument(
        "--project-root",
        type=str,
        default=".",
        help=PROJECT_ROOT_HELP,
    )
    upgrade_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed upgrade steps and validation command output.",
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
        "--json",
        metavar="FILE",
        help="Update configuration from JSON file",
    )
    config_parser.add_argument(
        "--swabbing-time",
        type=int,
        metavar="SECONDS",
        help="Set the swabbing-time budget (seconds). 0 or negative disables the limit.",
    )
    config_parser.add_argument(
        "--swab-off",
        metavar="GATE",
        help="Keep a gate out of swab while still running it during scour.",
    )
    config_parser.add_argument(
        "--swab-on",
        metavar="GATE",
        help="Make a gate run during both swab and scour.",
    )
    config_parser.add_argument(
        "--current-pr-number",
        type=int,
        metavar="PR",
        help="Set the working pull request number for buff commands.",
    )
    config_parser.add_argument(
        "--clear-current-pr",
        action="store_true",
        help="Clear the working pull request number.",
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
        "hook_verb",
        nargs="?",
        default="swab",
        help="Command to run on commit: swab (default) or scour",
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


def _add_agent_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the agent subcommand parser."""
    AgentParserBuilder(subparsers).build()


def _add_doctor_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the doctor subcommand parser.

    ``sm doctor`` diagnoses environment problems (missing tools, PATH
    collisions, stale locks, broken config) using the same resolution
    logic the gates use, so it reports what the gates will actually
    experience.  ``--fix`` repairs state that slop-mop itself owns —
    never project venvs, never node_modules.
    """
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Diagnose environment health and optionally fix owned state",
        description=(
            "Run environment diagnostics: runtime/platform summary, "
            "active sm resolution, tool inventory, project dependency "
            "health, and .slopmop/ state integrity.  Read-only by default; "
            "--fix repairs stale locks, missing state dirs, and "
            "restorable broken config.  Output pastes cleanly into "
            "bug reports."
        ),
    )
    doctor_parser.add_argument(
        "checks",
        nargs="*",
        metavar="CHECK",
        help=(
            "Check name(s) or glob pattern(s) to run "
            "(e.g. state.lock, state.*, sm_env.tool_inventory). "
            "Defaults to all checks."
        ),
    )
    doctor_parser.add_argument(
        "--list-checks",
        action="store_true",
        dest="list_checks",
        help="List check names and descriptions, then exit.",
    )
    doctor_parser.add_argument(
        "--fix",
        action="store_true",
        help=(
            "Attempt safe repair of slop-mop-owned state: remove stale "
            "sm.lock, create/repair .slopmop/, restore config from "
            "backup.  Never touches project venvs or node_modules."
        ),
    )
    doctor_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the --fix confirmation prompt.",
    )
    doctor_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        default=None,
        help="Output results as JSON. Auto-detected when stdout is not a TTY.",
    )
    doctor_parser.add_argument(
        "--no-json",
        dest="json_output",
        action="store_false",
        help="Force human-readable output even when stdout is not a TTY.",
    )
    doctor_parser.add_argument(
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
        help="Show project dashboard (config, gates, hooks)",
        description=(
            "Display project dashboard with configuration summary, "
            "gate inventory (with historical results), and hook "
            "installation status.  Does not run any gates."
        ),
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
        help="Show additional detail (e.g. per-gate timing stats)",
    )
    status_parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Minimal output",
    )
    status_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        default=None,
        help=("Output results as JSON. Auto-detected when stdout is not a TTY."),
    )
    status_parser.add_argument(
        "--no-json",
        dest="json_output",
        action="store_false",
        help="Force pretty output even when stdout is not a TTY.",
    )
    status_parser.add_argument(
        "--generate-baseline-snapshot",
        action="store_true",
        help=(
            "Capture a local baseline snapshot from the latest persisted "
            "run artifact (.slopmop/last_*.json)."
        ),
    )


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for sm CLI."""
    parser = argparse.ArgumentParser(
        prog="./sm",
        description=(textwrap.dedent("""
🪣 sm - Slop-Mop Quality Gate Framework

A language-agnostic, bolt-on code validation tool designed to catch AI-generated
slop before it lands in your codebase. Provides fast, actionable feedback for
both human developers and AI coding assistants.

Verbs:
  swab        Quick validation — runs on every commit
  scour       Thorough validation — PR readiness (superset of swab)
  upgrade     Upgrade slop-mop and validate the result
  buff        Post-PR CI triage and next-step guidance
  refit       Structured remediation planning and continuation
  agent       Install agent integration templates
  config      View or update quality gate configuration
  help        Show detailed help for quality gates

Quick Start:
  1. Add slop-mop as a git submodule
  2. Run: ./slop-mop/scripts/setup.sh (creates venv, installs tools, adds ./sm)
  3. Run: sm init (auto-detect project, write config)
  4. Run: sm swab (run quick quality gates)

Examples:
  sm swab                               Quick validation (every commit)
  sm scour                              Thorough validation (PR readiness)
  sm upgrade --check                    Preview an upgrade without mutating
  sm buff                               Post-PR CI triage
  sm refit --start                      Generate a remediation plan
  sm swab -g python,quality             Run specific gate groups
  sm scour --verbose                    Thorough with details
  sm config --show                      Show current configuration
  sm config --enable python-security    Enable a quality gate
  sm help python-lint-format            Show help for specific gate
""")),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="verb", help="Command to run")

    _add_swab_parser(subparsers)
    _add_scour_parser(subparsers)
    _add_upgrade_parser(subparsers)
    _add_buff_parser(subparsers)
    _add_sail_parser(subparsers)
    _add_refit_parser(subparsers)
    _add_status_parser(subparsers)
    _add_doctor_parser(subparsers)
    _add_config_parser(subparsers)
    _add_help_parser(subparsers)
    _add_init_parser(subparsers)
    _add_agent_parser(subparsers)
    _add_hooks_parser(subparsers)

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    return parser


def main(args: Optional[List[str]] = None) -> int:
    """Main entry point for sm CLI."""
    from slopmop import MissingDependencyError
    from slopmop.cli import (
        cmd_agent,
        cmd_buff,
        cmd_commit_hooks,
        cmd_config,
        cmd_help,
        cmd_init,
        cmd_refit,
        cmd_sail,
        cmd_scour,
        cmd_status,
        cmd_swab,
        cmd_upgrade,
    )

    parser = create_parser()
    parsed_args = parser.parse_args(args)

    # Setup logging
    if hasattr(parsed_args, "verbose") and parsed_args.verbose:
        setup_logging(verbose=True)
    else:
        setup_logging(verbose=False)

    try:
        return _dispatch(
            parsed_args,
            parser,
            cmd_swab=cmd_swab,
            cmd_scour=cmd_scour,
            cmd_upgrade=cmd_upgrade,
            cmd_buff=cmd_buff,
            cmd_sail=cmd_sail,
            cmd_refit=cmd_refit,
            cmd_status=cmd_status,
            cmd_config=cmd_config,
            cmd_help=cmd_help,
            cmd_init=cmd_init,
            cmd_agent=cmd_agent,
            cmd_commit_hooks=cmd_commit_hooks,
        )
    except MissingDependencyError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1


def _dispatch(
    parsed_args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    **handlers: Any,
) -> int:
    """Route parsed arguments to the appropriate verb handler."""
    # Handle verbs
    if parsed_args.verb == "swab":
        return handlers["cmd_swab"](parsed_args)
    elif parsed_args.verb == "scour":
        return handlers["cmd_scour"](parsed_args)
    elif parsed_args.verb == "upgrade":
        return handlers["cmd_upgrade"](parsed_args)
    elif parsed_args.verb == "buff":
        return handlers["cmd_buff"](parsed_args)
    elif parsed_args.verb == "sail":
        return handlers["cmd_sail"](parsed_args)
    elif parsed_args.verb == "refit":
        return handlers["cmd_refit"](parsed_args)
    elif parsed_args.verb == "status":
        return handlers["cmd_status"](parsed_args)
    elif parsed_args.verb == "doctor":
        return handlers["cmd_doctor"](parsed_args)
    elif parsed_args.verb == "config":
        return handlers["cmd_config"](parsed_args)
    elif parsed_args.verb == "help":
        return handlers["cmd_help"](parsed_args)
    elif parsed_args.verb == "init":
        return handlers["cmd_init"](parsed_args)
    elif parsed_args.verb == "agent":
        return handlers["cmd_agent"](parsed_args)
    elif parsed_args.verb == "commit-hooks":
        return handlers["cmd_commit_hooks"](parsed_args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
