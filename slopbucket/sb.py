"""sb - Slopbucket CLI with verb-based interface.

Usage:
    sb validate [--quality-gates GATES] [--self] [--verbose] [--quiet]
    sb validate <profile> [--verbose] [--quiet]
    sb config [--show] [--enable GATE] [--disable GATE] [--json FILE]
    sb help [GATE]

Verbs:
    validate    Run quality gate validation
    config      View or update configuration
    help        Show help for quality gates
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional

from slopbucket.core.executor import CheckExecutor
from slopbucket.core.registry import get_registry
from slopbucket.reporting.console import ConsoleReporter

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for CLI."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for sb CLI."""
    parser = argparse.ArgumentParser(
        prog="sb",
        description="""
🪣 sb - Slopbucket Quality Gate Framework

A language-agnostic, bolt-on code validation tool designed to catch AI-generated
slop before it lands in your codebase. Provides fast, actionable feedback for
both human developers and AI coding assistants.

Verbs:
  validate    Run quality gate validation on target project
  config      View or update quality gate configuration
  help        Show detailed help for quality gates

Quick Start:
  1. Clone slopbucket into your project as a subfolder
  2. Run: python setup.py (auto-configures for your project)
  3. Run: sb validate (runs full suite)
  4. Optional: sb config --show (see enabled gates)

Examples:
  sb validate                           Run full validation suite
  sb validate commit                    Run commit profile (fast)
  sb validate pr --verbose              Run PR profile with details
  sb validate --quality-gates python-tests,python-coverage
  sb validate --self                    Validate slopbucket itself
  sb config --show                      Show current configuration
  sb config --enable python-security    Enable a quality gate
  sb help python-lint-format            Show help for specific gate
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Subcommands (verbs)
    subparsers = parser.add_subparsers(dest="verb", help="Command to run")

    # === validate verb ===
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
        help="Run validation on slopbucket itself",
    )
    validate_parser.add_argument(
        "--project-root",
        type=str,
        default=".",
        help="Project root directory (default: current directory)",
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

    # === config verb ===
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
        "--project-root",
        type=str,
        default=".",
        help="Project root directory (default: current directory)",
    )

    # === help verb ===
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

    # Global options
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.0.0",
    )

    return parser


def ensure_checks_registered() -> None:
    """Ensure all checks are registered."""
    from slopbucket.checks import register_all_checks

    register_all_checks()


def cmd_validate(args: argparse.Namespace) -> int:
    """Handle the validate command."""
    ensure_checks_registered()

    # Determine project root
    if args.self_validate:
        # Find slopbucket's own root
        project_root = Path(__file__).parent.parent.resolve()
    else:
        project_root = Path(args.project_root).resolve()

    if not project_root.is_dir():
        print(f"❌ Project root not found: {project_root}")
        return 1

    # Determine which gates to run
    gates: List[str] = []

    if args.profile:
        gates = [args.profile]
    elif args.quality_gates:
        # Handle both comma-separated and space-separated
        for gate in args.quality_gates:
            gates.extend(g.strip() for g in gate.split(",") if g.strip())
    else:
        # Default to commit profile for validate without args
        gates = ["commit"]

    # Create executor
    registry = get_registry()
    executor = CheckExecutor(
        registry=registry,
        fail_fast=not args.no_fail_fast,
    )

    # Set up progress reporting
    reporter = ConsoleReporter(quiet=args.quiet, verbose=args.verbose)
    executor.set_progress_callback(reporter.on_check_complete)

    # Print header
    if not args.quiet:
        print("\n🪣 sb validate - Quality Gate Validation")
        print("=" * 60)
        print(f"📂 Project: {project_root}")
        if args.self_validate:
            print("🔄 Mode: Self-validation")
        print(f"🔍 Quality Gates: {', '.join(gates)}")
        print("=" * 60)
        print()

    # Run checks
    summary = executor.run_checks(
        project_root=str(project_root),
        check_names=gates,
        auto_fix=not args.no_auto_fix,
    )

    # Print summary
    reporter.print_summary(summary)
    return 0 if summary.all_passed else 1


def cmd_config(args: argparse.Namespace) -> int:
    """Handle the config command."""
    ensure_checks_registered()

    project_root = Path(args.project_root).resolve()
    config_file = project_root / "slopbucket.json"

    # Load existing config
    config = {}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text())
        except json.JSONDecodeError:
            print(f"⚠️  Invalid JSON in {config_file}")

    if args.json:
        # Update from JSON file
        json_path = Path(args.json)
        if not json_path.exists():
            print(f"❌ Config file not found: {args.json}")
            return 1
        try:
            new_config = json.loads(json_path.read_text())
            config.update(new_config)
            config_file.write_text(json.dumps(config, indent=2))
            print(f"✅ Configuration updated from {args.json}")
        except json.JSONDecodeError:
            print(f"❌ Invalid JSON in {args.json}")
            return 1
        return 0

    if args.enable:
        # Enable a gate
        disabled = config.get("disabled_gates", [])
        if args.enable in disabled:
            disabled.remove(args.enable)
            config["disabled_gates"] = disabled
            config_file.write_text(json.dumps(config, indent=2))
            print(f"✅ Enabled: {args.enable}")
        else:
            print(f"ℹ️  {args.enable} is already enabled")
        return 0

    if args.disable:
        # Disable a gate
        disabled = config.get("disabled_gates", [])
        if args.disable not in disabled:
            disabled.append(args.disable)
            config["disabled_gates"] = disabled
            config_file.write_text(json.dumps(config, indent=2))
            print(f"✅ Disabled: {args.disable}")
        else:
            print(f"ℹ️  {args.disable} is already disabled")
        return 0

    # Default: show config
    print("\n📋 Slopbucket Configuration")
    print("=" * 60)
    print(f"📂 Project: {project_root}")
    print(f"📄 Config file: {config_file}")
    print()

    registry = get_registry()

    # Show all available gates
    print("🔍 Available Quality Gates:")
    print("-" * 40)
    checks = registry.list_checks()
    disabled = config.get("disabled_gates", [])

    for name in sorted(checks):
        status = "❌ DISABLED" if name in disabled else "✅ ENABLED"
        definition = registry.get_definition(name)
        display = definition.name if definition else name
        print(f"  {status}  {display}")

    print()
    print("📦 Profiles (Aliases):")
    print("-" * 40)
    for alias, gates in sorted(registry.list_aliases().items()):
        print(f"  {alias}: {', '.join(gates)}")

    print()
    return 0


def cmd_help(args: argparse.Namespace) -> int:
    """Handle the help command."""
    ensure_checks_registered()

    registry = get_registry()

    if args.gate:
        # Show help for specific gate
        definition = registry.get_definition(args.gate)
        if not definition:
            # Check if it's an alias
            if registry.is_alias(args.gate):
                print(f"\n📦 Profile: {args.gate}")
                print("=" * 60)
                print(f"Expands to: {', '.join(registry.expand_alias(args.gate))}")
                print()
                return 0
            print(f"❌ Unknown quality gate: {args.gate}")
            print("   Run 'sb help' to see all available gates")
            return 1

        # Get the check class for more details
        check = registry.get_check(args.gate, {})
        if not check:
            print(f"❌ Could not instantiate: {args.gate}")
            return 1

        print(f"\n🔍 Quality Gate: {definition.name}")
        print("=" * 60)
        print(f"Flag: --quality-gates {definition.flag}")
        print(f"Auto-fix: {'Yes' if definition.auto_fix else 'No'}")
        if definition.depends_on:
            print(f"Depends on: {', '.join(definition.depends_on)}")
        print()
        print("Description:")
        print(f"  {check.__doc__ or 'No description available.'}")
        print()
        print("When to use:")
        print(f"  Run as part of 'commit' or 'pr' profiles, or individually")
        print()
        return 0

    # Show help for all gates
    print("\n🪣 Slopbucket Quality Gates")
    print("=" * 60)
    print()

    # Group by category
    python_gates = []
    js_gates = []
    general_gates = []

    for name in sorted(registry.list_checks()):
        if name.startswith("python-"):
            python_gates.append(name)
        elif name.startswith("js-") or name == "frontend-check":
            js_gates.append(name)
        else:
            general_gates.append(name)

    def print_gates(title: str, gates: List[str]) -> None:
        if not gates:
            return
        print(f"  {title}:")
        for name in gates:
            definition = registry.get_definition(name)
            display = definition.name if definition else name
            auto_fix = "🔧" if definition and definition.auto_fix else "  "
            print(f"    {auto_fix} {name:<30} {display}")
        print()

    print_gates("🐍 Python", python_gates)
    print_gates("📜 JavaScript", js_gates)
    print_gates("📋 General", general_gates)

    print("📦 Profiles:")
    for alias, gates in sorted(registry.list_aliases().items()):
        print(f"    {alias:<30} {len(gates)} gates")

    print()
    print("Legend: 🔧 = supports auto-fix")
    print()
    print("For detailed help on a gate: sb help <gate-name>")
    print()
    return 0


def main(args: Optional[List[str]] = None) -> int:
    """Main entry point for sb CLI."""
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
    elif parsed_args.verb == "config":
        return cmd_config(parsed_args)
    elif parsed_args.verb == "help":
        return cmd_help(parsed_args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
