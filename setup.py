#!/usr/bin/env python3
"""
Slopbucket — AI-optimized code validation gate.

The single entry point for all quality checks. Drop this repo as a git
submodule and run validation from anywhere.

QUICK START:
    python slopbucket/setup.py --help           # See all options
    python slopbucket/setup.py --checks commit  # Fast pre-commit validation
    python slopbucket/setup.py --checks pr      # Full PR validation

PROFILES (predefined check groups):
    commit          Fast pre-commit (~2-3 min, runs in parallel)
    pr              Full PR validation (all checks)
    security-local  Security without network calls
    security        Full security audit
    format          Auto-fix formatting only
    lint            Static analysis (flake8 + mypy)
    tests           Test suite + coverage
    full            Maximum validation (everything)

INDIVIDUAL CHECKS:
    python-format           Black + isort + autoflake (auto-fixes)
    python-lint             Flake8 critical errors
    python-types            Mypy strict type checking
    python-tests            Pytest with coverage
    python-coverage         Global coverage threshold (80%)
    python-diff-coverage    Coverage on changed files (80%)
    python-complexity       Cyclomatic complexity (radon)
    python-security         Bandit + semgrep + detect-secrets + safety
    python-security-local   Security without network
    python-duplication      Code duplication (jscpd)
    js-format               ESLint + Prettier
    js-tests                Jest test runner
    js-coverage             Jest coverage threshold
    template-validation     Jinja2 template syntax

EXAMPLES:
    # Pre-commit: fast, parallel, fail-fast
    python slopbucket/setup.py --checks commit

    # PR: everything, verbose output
    python slopbucket/setup.py --checks pr --verbose

    # Just security (local, no network)
    python slopbucket/setup.py --checks security-local

    # Mix profiles and individual checks
    python slopbucket/setup.py --checks format python-tests

    # Sequential execution (useful for debugging)
    python slopbucket/setup.py --checks commit --no-parallel

    # List all available checks without running them
    python slopbucket/setup.py --list

OPTIONS:
    --checks <names>        Profile or check names to run (required unless --list)
    --verbose               Show detailed execution logs
    --no-parallel           Run checks sequentially (useful for debugging)
    --no-fail-fast          Continue on failure instead of stopping
    --timeout <seconds>     Per-check timeout (default: 900s / 15 min)
    --list                  List all available profiles and checks
    --help                  Show this help message
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure slopbucket is importable regardless of where setup.py is called from
_SETUP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SETUP_DIR))

from slopbucket.check_discovery import load_checks  # noqa: E402
from slopbucket.config import (  # noqa: E402
    CHECK_REGISTRY,
    PROFILE_DESCRIPTIONS,
    PROFILES,
    RunnerConfig,
    resolve_checks,
)
from slopbucket.runner import Runner  # noqa: E402


def configure_logging(verbose: bool = False) -> None:
    """Set up logging based on verbosity."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def list_checks() -> None:
    """Print all available profiles and checks."""
    print()
    print("  SLOPBUCKET — Available Checks & Profiles")
    print("  " + "=" * 50)

    print()
    print("  PROFILES (predefined check groups):")
    print("  " + "-" * 50)
    for name, description in PROFILE_DESCRIPTIONS.items():
        checks = PROFILES[name]
        print(f"    {name:<20} {description}")
        print(f"    {'':20} └─ {', '.join(checks)}")
        print()

    print()
    print("  INDIVIDUAL CHECKS:")
    print("  " + "-" * 50)
    for name, check_def in sorted(CHECK_REGISTRY.items()):
        print(f"    {name:<30} {check_def.description}")
        print(f"    {'':30} [{check_def.language}/{check_def.category}]")
    print()


def main() -> int:
    """Main entry point — parse args, load checks, run, report."""
    parser = argparse.ArgumentParser(
        prog="slopbucket",
        description="AI-optimized code validation gate",
        add_help=False,  # Custom help via --help handling
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--checks",
        nargs="+",
        help="Profile name(s) or individual check name(s)",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument(
        "--no-parallel", action="store_true", help="Run checks sequentially"
    )
    parser.add_argument(
        "--no-fail-fast", action="store_true", help="Continue after first failure"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=900,
        help="Per-check timeout in seconds (default: 900)",
    )
    parser.add_argument("--list", action="store_true", help="List checks and profiles")
    parser.add_argument("--help", action="store_true", help="Show detailed help")

    args = parser.parse_args()

    # Handle --help
    if args.help:
        print(__doc__)
        return 0

    # Handle --list
    if args.list:
        list_checks()
        return 0

    # Require --checks unless --list or --help
    if not args.checks:
        print("Error: --checks is required. Use --help for usage or --list for available checks.")
        return 1

    configure_logging(args.verbose)

    # Resolve check names to CheckDef objects
    check_defs = resolve_checks(args.checks)
    if not check_defs:
        print(f"Error: No checks matched: {args.checks}")
        print("Run --list to see available checks and profiles.")
        return 1

    # Load check classes
    try:
        checks = load_checks(check_defs)
    except Exception as e:
        print(f"Error loading checks: {e}")
        return 1

    # Configure runner
    runner_config = RunnerConfig(
        parallel=not args.no_parallel,
        fail_fast=not args.no_fail_fast,
        verbose=args.verbose,
        timeout_secs=args.timeout,
        working_dir=os.getcwd(),
    )

    # Determine profile name for display
    profile_name = args.checks[0] if len(args.checks) == 1 and args.checks[0] in PROFILES else "custom"

    # Execute
    runner = Runner(runner_config)
    summary = runner.run(checks, profile_name=profile_name)

    # Print results
    print(summary.format_summary())

    return 0 if summary.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
