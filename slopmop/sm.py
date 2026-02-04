"""sb - Slop-Mop CLI with verb-based interface.

Usage:
    sm validate [--quality-gates GATES] [--self] [--verbose] [--quiet]
    sm validate <profile> [--verbose] [--quiet]
    sm config [--show] [--enable GATE] [--disable GATE] [--json FILE]
    sm init [--config FILE] [--non-interactive]
    sb commit-hooks status
    sb commit-hooks install <profile>
    sb commit-hooks uninstall
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

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from slopmop.core.executor import CheckExecutor
from slopmop.core.registry import get_registry
from slopmop.reporting.console import ConsoleReporter

logger = logging.getLogger(__name__)


def load_config(project_root: Path) -> Dict:
    """Load configuration from .sb_config.json.

    Args:
        project_root: Path to project root directory

    Returns:
        Configuration dictionary, or empty dict if not found
    """
    # Check for override via environment variable
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


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for sb CLI."""
    parser = argparse.ArgumentParser(
        prog="sb",
        description="""
🧹 sm - Slop-Mop Quality Gate Framework

A language-agnostic, bolt-on code validation tool designed to catch AI-generated
slop before it lands in your codebase. Provides fast, actionable feedback for
both human developers and AI coding assistants.

Verbs:
  validate    Run quality gate validation on target project
  config      View or update quality gate configuration
  help        Show detailed help for quality gates

Quick Start:
  1. Clone slopmop into your project as a subfolder
  2. Run: python setup.py (auto-configures for your project)
  3. Run: sm validate (runs full suite)
  4. Optional: sm config --show (see enabled gates)

Examples:
  sm validate                           Run full validation suite
  sm validate commit                    Run commit profile (fast)
  sm validate pr --verbose              Run PR profile with details
  sm validate --quality-gates python-tests,python-coverage
  sm validate --self                    Validate slopmop itself
  sm config --show                      Show current configuration
  sm config --enable python-security    Enable a quality gate
  sm help python-lint-format            Show help for specific gate
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
        help="Run validation on slopmop itself",
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

    # === init verb ===
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
        help="Project root directory (default: current directory)",
    )

    # === commit-hooks verb ===
    hooks_parser = subparsers.add_parser(
        "commit-hooks",
        help="Manage git pre-commit hooks",
        description="Install, uninstall, or check status of sb-managed git hooks.",
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
        help="Project root directory (default: current directory)",
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
        help="Project root directory (default: current directory)",
    )

    # commit-hooks uninstall
    hooks_uninstall = hooks_subparsers.add_parser(
        "uninstall",
        help="Remove all sb-managed commit hooks",
    )
    hooks_uninstall.add_argument(
        "--project-root",
        type=str,
        default=".",
        help="Project root directory (default: current directory)",
    )

    # === ci verb ===
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
        help="Project root directory (default: current directory)",
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
    from slopmop.checks import register_all_checks

    register_all_checks()


def cmd_validate(args: argparse.Namespace) -> int:
    """Handle the validate command."""
    import tempfile

    ensure_checks_registered()

    # Determine project root
    if args.self_validate:
        # Find slopmop's own root
        project_root = Path(__file__).parent.parent.resolve()
    else:
        project_root = Path(args.project_root).resolve()

    if not project_root.is_dir():
        print(f"❌ Project root not found: {project_root}")
        return 1

    # For --self validation, use a temp config to protect user's real config
    temp_config_dir = None
    original_config_file = project_root / ".sb_config.json"

    if args.self_validate:
        # Generate a fresh config in a temp location for self-validation
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

        # Use the temp config for validation (set env var for config loading)
        os.environ["SB_CONFIG_FILE"] = str(temp_config_file)

    # Determine which gates to run
    gates: List[str] = []
    profile_name: Optional[str] = None  # Track the profile/alias for iteration guidance

    if args.profile:
        gates = [args.profile]
        profile_name = args.profile
    elif args.quality_gates:
        # Handle both comma-separated and space-separated
        for gate in args.quality_gates:
            gates.extend(g.strip() for g in gate.split(",") if g.strip())
        # No profile when using -g (explicit gate list)
        profile_name = None
    else:
        # Default to commit profile for validate without args
        gates = ["commit"]
        profile_name = "commit"

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
        print("\n🧹 sm validate - Quality Gate Validation")
        print("=" * 60)
        print(f"📂 Project: {project_root}")
        if args.self_validate:
            print("🔄 Mode: Self-validation (using isolated config)")
        print(f"🔍 Quality Gates: {', '.join(gates)}")
        print("=" * 60)
        print()

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
        # Clean up temp config dir if used
        if temp_config_dir:
            import shutil

            os.environ.pop("SB_CONFIG_FILE", None)
            shutil.rmtree(temp_config_dir, ignore_errors=True)


def cmd_config(args: argparse.Namespace) -> int:
    """Handle the config command."""
    ensure_checks_registered()

    project_root = Path(args.project_root).resolve()
    config_file = project_root / ".sb_config.json"

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
    print("\n📋 Slop-Mop Configuration")
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
            print("   Run 'sm help' to see all available gates")
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
    print("\n🧹 Slop-Mop Quality Gates")
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
    print("For detailed help on a gate: sm help <gate-name>")
    print()
    return 0


def detect_project_type(project_root: Path) -> Dict[str, Any]:
    """Auto-detect project type and characteristics.

    Returns a dict with detected features:
    - has_python: bool
    - has_javascript: bool
    - has_typescript: bool
    - has_tests_dir: bool
    - has_pytest: bool
    - has_jest: bool
    - python_version: str or None
    - test_dirs: list of test directory paths
    - recommended_profile: str
    - recommended_gates: list of str
    """
    detected: Dict[str, Any] = {
        "has_python": False,
        "has_javascript": False,
        "has_typescript": False,
        "has_tests_dir": False,
        "has_pytest": False,
        "has_jest": False,
        "python_version": None,
        "test_dirs": [],
        "recommended_profile": "commit",
        "recommended_gates": [],
    }

    # Check for Python
    py_indicators = ["setup.py", "pyproject.toml", "requirements.txt", "Pipfile"]
    for indicator in py_indicators:
        if (project_root / indicator).exists():
            detected["has_python"] = True
            break
    if not detected["has_python"]:
        # Check for .py files
        detected["has_python"] = any(project_root.glob("**/*.py"))

    # Check for JavaScript/TypeScript
    js_indicators = ["package.json", "tsconfig.json"]
    for indicator in js_indicators:
        if (project_root / indicator).exists():
            detected["has_javascript"] = True
            break
    if not detected["has_javascript"]:
        detected["has_javascript"] = any(project_root.glob("**/*.js")) or any(
            project_root.glob("**/*.ts")
        )

    # Check specifically for TypeScript (tsconfig.json or .ts files)
    ts_indicators = ["tsconfig.json", "tsconfig.ci.json"]
    for indicator in ts_indicators:
        if (project_root / indicator).exists():
            detected["has_typescript"] = True
            break
    if not detected["has_typescript"]:
        detected["has_typescript"] = any(project_root.glob("**/*.ts"))

    # Check for test directories
    test_dirs = []
    for test_dir in ["tests", "test", "spec", "__tests__"]:
        test_path = project_root / test_dir
        if test_path.is_dir():
            test_dirs.append(str(test_path.relative_to(project_root)))
            detected["has_tests_dir"] = True

    detected["test_dirs"] = test_dirs

    # Check for pytest
    pyproject = project_root / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text()
        if "pytest" in content:
            detected["has_pytest"] = True

    setup_cfg = project_root / "setup.cfg"
    if setup_cfg.exists():
        content = setup_cfg.read_text()
        if "pytest" in content:
            detected["has_pytest"] = True

    if (project_root / "pytest.ini").exists() or (
        project_root / "conftest.py"
    ).exists():
        detected["has_pytest"] = True

    # Check for Jest
    package_json = project_root / "package.json"
    if package_json.exists():
        try:
            pkg = json.loads(package_json.read_text())
            if "jest" in pkg.get("devDependencies", {}):
                detected["has_jest"] = True
            if "jest" in pkg.get("dependencies", {}):
                detected["has_jest"] = True
            if "test" in pkg.get("scripts", {}):
                script = pkg["scripts"]["test"]
                if "jest" in script:
                    detected["has_jest"] = True
        except json.JSONDecodeError:
            pass

    # Determine recommended profile and gates
    recommended = []
    if detected["has_python"]:
        recommended.extend(
            [
                "python-lint-format",
                "python-tests",
                "python-static-analysis",
            ]
        )
        if detected["has_pytest"]:
            recommended.append("python-coverage")

    if detected["has_javascript"]:
        recommended.extend(["js-lint-format", "js-tests"])
        if detected["has_jest"]:
            recommended.append("js-coverage")
        # Add TypeScript type checking if TypeScript is detected
        if detected["has_typescript"]:
            recommended.append("javascript-types")

    detected["recommended_gates"] = recommended

    # Recommend profile
    if detected["has_python"] and detected["has_javascript"]:
        detected["recommended_profile"] = "pr"
    elif detected["has_python"]:
        detected["recommended_profile"] = "python"
    elif detected["has_javascript"]:
        detected["recommended_profile"] = "javascript"
    else:
        detected["recommended_profile"] = "commit"

    return detected


def prompt_user(question: str, default: str = "") -> str:
    """Prompt user for input with optional default."""
    if default:
        prompt = f"{question} [{default}]: "
    else:
        prompt = f"{question}: "
    response = input(prompt).strip()
    return response if response else default


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """Prompt user for yes/no with default."""
    default_str = "Y/n" if default else "y/N"
    response = input(f"{question} [{default_str}]: ").strip().lower()
    if not response:
        return default
    return response in ("y", "yes", "1", "true")


def _deep_merge(base: Dict[str, Any], updates: Dict[str, Any]) -> None:
    """Deep merge updates into base dict, modifying base in place.

    For nested dicts, recursively merges. For other values, updates
    take precedence (overwrite base).

    Args:
        base: Base dictionary to merge into
        updates: Dictionary with values to merge in
    """
    for key, value in updates.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def cmd_init(args: argparse.Namespace) -> int:
    """Handle the init command - interactive project setup."""
    project_root = Path(args.project_root).resolve()

    if not project_root.is_dir():
        print(f"❌ Project root not found: {project_root}")
        return 1

    config_file = project_root / ".sb_config.json"
    setup_config_file = Path(args.config) if args.config else None

    print("\n🧹 Slop-Mop Interactive Setup")
    print("=" * 60)
    print(f"📂 Project: {project_root}")
    print()

    # Load pre-populated config if provided
    preconfig: Dict[str, Any] = {}
    if setup_config_file and setup_config_file.exists():
        try:
            preconfig = json.loads(setup_config_file.read_text())
            print(f"📋 Loaded config from: {setup_config_file}")
        except json.JSONDecodeError:
            print(f"⚠️  Invalid JSON in {setup_config_file}, ignoring")

    # Auto-detect project characteristics
    print("🔍 Detecting project type...")
    detected = detect_project_type(project_root)

    print()
    print("📊 Detection Results:")
    print("-" * 40)
    print(f"  Python project:      {'✅' if detected['has_python'] else '❌'}")
    print(f"  JavaScript project:  {'✅' if detected['has_javascript'] else '❌'}")
    print(f"  Has test directory:  {'✅' if detected['has_tests_dir'] else '❌'}")
    if detected["test_dirs"]:
        print(f"  Test directories:    {', '.join(detected['test_dirs'])}")
    print(f"  Pytest detected:     {'✅' if detected['has_pytest'] else '❌'}")
    print(f"  Jest detected:       {'✅' if detected['has_jest'] else '❌'}")
    print()
    print(f"  Recommended profile: {detected['recommended_profile']}")
    if detected["recommended_gates"]:
        print(f"  Recommended gates:   {', '.join(detected['recommended_gates'])}")
    print()

    # Build configuration
    config: Dict[str, Any] = {}

    if args.non_interactive:
        # Use detected defaults and preconfig
        config = {
            "project_type": (
                "python"
                if detected["has_python"]
                else "javascript" if detected["has_javascript"] else "mixed"
            ),
            "default_profile": preconfig.get(
                "default_profile", detected["recommended_profile"]
            ),
            "test_dirs": preconfig.get("test_dirs", detected["test_dirs"]),
            "disabled_gates": preconfig.get("disabled_gates", []),
            "enabled_gates": preconfig.get(
                "enabled_gates", detected["recommended_gates"]
            ),
        }
        print("🤖 Non-interactive mode: using detected defaults")
    else:
        # Interactive prompts
        print("📝 Configuration (press Enter for defaults)")
        print("-" * 40)

        # Default profile
        default_profile = preconfig.get(
            "default_profile", detected["recommended_profile"]
        )
        config["default_profile"] = prompt_user(
            "Default validation profile", default_profile
        )

        # Test directories
        default_test_dirs = preconfig.get("test_dirs", detected["test_dirs"])
        test_dirs_str = prompt_user(
            "Test directories (comma-separated)",
            ",".join(default_test_dirs) if default_test_dirs else "tests",
        )
        config["test_dirs"] = [d.strip() for d in test_dirs_str.split(",") if d.strip()]

        # Ask about specific gates to disable
        config["disabled_gates"] = preconfig.get("disabled_gates", [])

        if detected["has_python"]:
            if not prompt_yes_no("Enable Python security scanning", True):
                config["disabled_gates"].extend(
                    ["python-security", "python-security-local"]
                )

            if not prompt_yes_no("Enable code complexity checks", True):
                config["disabled_gates"].append("python-complexity")

        if detected["has_javascript"]:
            if not prompt_yes_no("Enable JavaScript linting", True):
                config["disabled_gates"].append("js-lint-format")

        # Coverage threshold
        default_threshold = preconfig.get("coverage_threshold", 80)
        threshold_str = prompt_user(
            "Minimum coverage threshold (%)", str(default_threshold)
        )
        try:
            config["coverage_threshold"] = int(threshold_str)
        except ValueError:
            config["coverage_threshold"] = 80

        print()

    # Write configuration
    print("💾 Writing configuration...")

    # Generate base config from check classes (IaC pattern)
    from slopmop.utils.generate_base_config import (
        backup_config,
        generate_base_config,
        write_template_config,
    )

    # Always generate the template file (shows all options, for git history)
    template_path = write_template_config(project_root)
    print(f"📄 Template saved to: {template_path}")

    base_config = generate_base_config()

    # Apply detected project settings to the base config
    if detected["has_python"]:
        base_config["python"]["enabled"] = True
        if detected["test_dirs"]:
            if "tests" in base_config["python"]["gates"]:
                base_config["python"]["gates"]["tests"]["test_dirs"] = detected[
                    "test_dirs"
                ]
        # Enable standard gates
        for gate in ["lint-format", "tests", "coverage", "static-analysis"]:
            if gate in base_config["python"]["gates"]:
                base_config["python"]["gates"][gate]["enabled"] = True

    if detected["has_javascript"]:
        base_config["javascript"]["enabled"] = True
        # Enable standard gates
        for gate in ["lint-format", "tests"]:
            if gate in base_config["javascript"]["gates"]:
                base_config["javascript"]["gates"][gate]["enabled"] = True

    # Apply user config overrides
    base_config["default_profile"] = config.get("default_profile", "commit")

    # Apply disabled gates from user config
    for gate_full_name in config.get("disabled_gates", []):
        # Handle old-style gate names like "python-security"
        if ":" not in gate_full_name and "-" in gate_full_name:
            # Try to parse as category-gatename (e.g., "python-security")
            parts = gate_full_name.split("-", 1)
            if len(parts) == 2:
                category, gate = parts[0], parts[1]
                if category in base_config and "gates" in base_config[category]:
                    if gate in base_config[category]["gates"]:
                        base_config[category]["gates"][gate]["enabled"] = False

    # Apply coverage threshold if set
    if "coverage_threshold" in config:
        if "python" in base_config and "gates" in base_config["python"]:
            if "coverage" in base_config["python"]["gates"]:
                base_config["python"]["gates"]["coverage"]["threshold"] = config[
                    "coverage_threshold"
                ]
        if "javascript" in base_config and "gates" in base_config["javascript"]:
            if "coverage" in base_config["javascript"]["gates"]:
                base_config["javascript"]["gates"]["coverage"]["threshold"] = config[
                    "coverage_threshold"
                ]

    # Merge with existing config if present (preserve user customizations)
    if config_file.exists():
        try:
            existing = json.loads(config_file.read_text())
            # Back up before overwriting
            backup_path = backup_config(config_file)
            if backup_path:
                print(f"📦 Backed up existing config to: {backup_path}")
            # Deep merge: existing values take precedence for user customizations
            # but new structure is used as base
            _deep_merge(base_config, existing)
        except json.JSONDecodeError:
            pass

    config_file.write_text(json.dumps(base_config, indent=2) + "\n")
    print(f"✅ Configuration saved to: {config_file}")

    # Show next steps
    print()
    print("🚀 Setup Complete!")
    print("=" * 60)
    print()
    print("Next steps:")
    print(
        f"  1. Run 'sm validate' to run the {config.get('default_profile', 'commit')} profile"
    )
    print("  2. Run 'sm validate pr' before opening a pull request")
    print("  3. Run 'sm config' to view or modify gate settings")
    print("  4. Run 'sm help' to see all available quality gates")
    print()
    print("Quick validation:")
    print("  sm validate quick    # Fast lint-only check")
    print("  sm validate commit   # Standard pre-commit validation")
    print("  sm validate pr       # Full PR validation")
    print()

    return 0


# =============================================================================
# COMMIT-HOOKS COMMAND
# =============================================================================

# Marker to identify sb-managed hooks
SB_HOOK_MARKER = "# MANAGED BY SLOPBUCKET - DO NOT EDIT"
SB_HOOK_END_MARKER = "# END SLOPBUCKET HOOK"


def _get_git_hooks_dir(project_root: Path) -> Optional[Path]:
    """Find the .git/hooks directory for a project."""
    git_dir = project_root / ".git"
    if not git_dir.is_dir():
        # Check if it's a worktree (git file instead of dir)
        git_file = project_root / ".git"
        if git_file.is_file():
            content = git_file.read_text().strip()
            if content.startswith("gitdir:"):
                git_path = Path(content.split(":", 1)[1].strip())
                if not git_path.is_absolute():
                    git_path = project_root / git_path
                return git_path / "hooks"
        return None
    return git_dir / "hooks"


def _generate_hook_script(profile: str) -> str:
    """Generate the pre-commit hook script content."""
    return f"""{SB_HOOK_MARKER}
#!/bin/sh
#
# Pre-commit hook managed by slopmop
# Profile: {profile}
# To remove: sb commit-hooks uninstall
#

# Run slopmop validation
sm validate {profile}

# Capture exit code
result=$?

if [ $result -ne 0 ]; then
    echo ""
    echo "❌ Commit blocked by slopmop quality gates"
    echo "   Run 'sm validate {profile}' to see details"
    echo ""
    exit 1
fi

exit 0
{SB_HOOK_END_MARKER}
"""


def _parse_hook_info(hook_content: str) -> Optional[dict]:
    """Parse sb-managed hook to extract info."""
    if SB_HOOK_MARKER not in hook_content:
        return None

    # Extract profile from comment
    import re

    match = re.search(r"# Profile: (\w+)", hook_content)
    profile = match.group(1) if match else "unknown"

    return {"profile": profile, "managed": True}


def cmd_commit_hooks(args: argparse.Namespace) -> int:
    """Handle the commit-hooks command."""
    project_root = Path(args.project_root).resolve()

    if not args.hooks_action:
        # Default to status
        args.hooks_action = "status"

    hooks_dir = _get_git_hooks_dir(project_root)

    if not hooks_dir:
        print(f"❌ Not a git repository: {project_root}")
        print("   Initialize git first: git init")
        return 1

    if args.hooks_action == "status":
        return _hooks_status(project_root, hooks_dir)
    elif args.hooks_action == "install":
        return _hooks_install(project_root, hooks_dir, args.profile)
    elif args.hooks_action == "uninstall":
        return _hooks_uninstall(project_root, hooks_dir)
    else:
        print(f"❌ Unknown action: {args.hooks_action}")
        return 1


def _hooks_status(project_root: Path, hooks_dir: Path) -> int:
    """Show status of installed hooks."""
    print()
    print("🪝 Git Hooks Status")
    print("=" * 60)
    print(f"📂 Project: {project_root}")
    print(f"📁 Hooks dir: {hooks_dir}")
    print()

    if not hooks_dir.exists():
        print("ℹ️  No hooks directory found")
        print("   Install a hook: sb commit-hooks install <profile>")
        return 0

    # Check for common hook types
    hook_types = ["pre-commit", "pre-push", "commit-msg"]
    found_sb_hooks = []
    found_other_hooks = []

    for hook_type in hook_types:
        hook_file = hooks_dir / hook_type
        if hook_file.exists():
            content = hook_file.read_text()
            info = _parse_hook_info(content)
            if info:
                found_sb_hooks.append((hook_type, info))
            else:
                found_other_hooks.append(hook_type)

    if found_sb_hooks:
        print("🧹 Slop-Mop-managed hooks:")
        for hook_type, info in found_sb_hooks:
            print(f"   ✅ {hook_type}: profile={info['profile']}")
        print()

    if found_other_hooks:
        print("📋 Other hooks (not managed by sb):")
        for hook_type in found_other_hooks:
            print(f"   • {hook_type}")
        print()

    if not found_sb_hooks and not found_other_hooks:
        print("ℹ️  No commit hooks installed")
        print()

    print("Commands:")
    print("   sb commit-hooks install <profile>  # Install pre-commit hook")
    print("   sb commit-hooks uninstall          # Remove sb hooks")
    print()
    return 0


def _hooks_install(project_root: Path, hooks_dir: Path, profile: str) -> int:
    """Install a pre-commit hook."""
    # Ensure hooks directory exists
    hooks_dir.mkdir(parents=True, exist_ok=True)

    hook_file = hooks_dir / "pre-commit"

    # Check for existing hook
    if hook_file.exists():
        content = hook_file.read_text()
        if SB_HOOK_MARKER in content:
            print(f"ℹ️  Updating existing slopmop hook...")
        else:
            print(f"⚠️  Existing pre-commit hook found at: {hook_file}")
            print("   This hook is not managed by slopmop.")
            print()
            print("Options:")
            print("   1. Back up your existing hook and run install again")
            print("   2. Manually add 'sm validate' to your existing hook")
            print()
            return 1

    # Write the hook
    hook_content = _generate_hook_script(profile)
    hook_file.write_text(hook_content)

    # Make executable (Unix)
    import stat

    hook_file.chmod(
        hook_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    )

    print()
    print("✅ Pre-commit hook installed!")
    print("=" * 60)
    print(f"📂 Project: {project_root}")
    print(f"📄 Hook: {hook_file}")
    print(f"🎯 Profile: {profile}")
    print()
    print("The hook will run 'sm validate {profile}' before each commit.")
    print("Commits will be blocked if quality gates fail.")
    print()
    print("To remove: sb commit-hooks uninstall")
    print()
    return 0


def _hooks_uninstall(project_root: Path, hooks_dir: Path) -> int:
    """Remove all sb-managed hooks."""
    if not hooks_dir.exists():
        print("ℹ️  No hooks directory found")
        return 0

    removed = []
    hook_types = ["pre-commit", "pre-push", "commit-msg"]

    for hook_type in hook_types:
        hook_file = hooks_dir / hook_type
        if hook_file.exists():
            content = hook_file.read_text()
            if SB_HOOK_MARKER in content:
                hook_file.unlink()
                removed.append(hook_type)

    print()
    if removed:
        print("✅ Removed slopmop-managed hooks:")
        for hook_type in removed:
            print(f"   • {hook_type}")
    else:
        print("ℹ️  No slopmop-managed hooks found")
    print()
    return 0


def cmd_ci(args: argparse.Namespace) -> int:
    """Handle the ci command - check CI status for current PR."""
    import subprocess
    import time

    project_root = Path(args.project_root).resolve()

    # Detect PR number if not provided
    pr_number = args.pr_number
    if pr_number is None:
        try:
            result = subprocess.run(
                ["gh", "pr", "view", "--json", "number"],
                cwd=project_root,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                pr_number = data.get("number")
        except (subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError):
            pass

    if pr_number is None:
        print("❌ Could not detect PR number")
        print("   Run from a branch with an open PR, or specify: sm ci <pr_number>")
        return 2

    print()
    print("🧹 sm ci - CI Status Check")
    print("=" * 60)
    print(f"📂 Project: {project_root}")
    print(f"🔀 PR: #{pr_number}")
    if args.watch:
        print(f"👀 Watch mode: polling every {args.interval}s")
    print("=" * 60)
    print()

    while True:
        # Get check status
        try:
            result = subprocess.run(
                [
                    "gh",
                    "pr",
                    "checks",
                    str(pr_number),
                    "--json",
                    "name,state,bucket,link",
                ],
                cwd=project_root,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            print("❌ GitHub CLI (gh) not found")
            print("   Install: https://cli.github.com/")
            return 2

        # Handle "no checks" case (gh returns error for this)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "no checks" in stderr.lower():
                print("ℹ️  No CI checks found for this PR")
                print("   (CI workflow may not be set up yet)")
                return 0
            print(f"❌ Failed to get check status: {stderr}")
            return 1

        try:
            checks = json.loads(result.stdout)
        except json.JSONDecodeError:
            # Empty output is OK - means no checks
            if not result.stdout.strip():
                print("ℹ️  No CI checks found for this PR")
                return 0
            print(f"❌ Failed to parse check data: {result.stdout}")
            return 1

        if not checks:
            print("ℹ️  No CI checks found for this PR")
            return 0

        # Categorize checks using 'bucket' field (pass, fail, pending, skipping, cancel)
        completed = []
        in_progress = []
        failed = []

        for check in checks:
            bucket = check.get("bucket", "").lower()
            name = check.get("name", "Unknown")
            url = check.get("link", "")
            state = check.get("state", "")

            if bucket == "pass":
                completed.append((name, "✅", "passed"))
            elif bucket == "fail":
                failed.append((name, "❌", "failed", url))
            elif bucket == "cancel":
                failed.append((name, "🚫", "cancelled", url))
            elif bucket in ("pending", "skipping"):
                in_progress.append((name, "🔄", state or bucket))
            else:
                in_progress.append((name, "❓", state or bucket))

        # Print status
        total = len(checks)
        passed_count = len(completed)
        failed_count = len(failed)
        pending_count = len(in_progress)

        if failed:
            print("🧹 SLOP IN CI")
            print()
            print(
                f"   ✅ {passed_count} passed · ❌ {failed_count} failed · 🔄 {pending_count} pending"
            )
            print()
            print("❌ FAILED:")
            for name, _, conclusion, url in failed:
                print(f"   • {name}: {conclusion}")
                if url:
                    print(f"     └─ {url}")
            print()

            if in_progress:
                print("🔄 IN PROGRESS:")
                for name, _, state in in_progress:
                    print(f"   • {name}: {state}")
                print()

            if args.watch and in_progress:
                print(f"⏳ Waiting {args.interval}s before next check...")
                time.sleep(args.interval)
                print()
                continue

            return 1

        elif in_progress:
            print("🔄 CI IN PROGRESS")
            print()
            print(f"   ✅ {passed_count} passed · 🔄 {pending_count} pending")
            print()
            print("🔄 IN PROGRESS:")
            for name, _, state in in_progress:
                print(f"   • {name}: {state}")
            print()

            if args.watch:
                print(f"⏳ Waiting {args.interval}s before next check...")
                time.sleep(args.interval)
                print()
                continue
            else:
                print("💡 Use --watch to poll until complete")
                return 1

        else:
            # All passed!
            print(f"✨ CI CLEAN · {passed_count}/{total} checks passed")
            print()
            for name, emoji, conclusion in completed:
                print(f"   {emoji} {name}")
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
