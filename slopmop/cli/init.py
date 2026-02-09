"""Init command for slop-mop CLI.

Handles interactive and non-interactive project setup.
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, cast

from slopmop.cli.detection import detect_project_type


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
    """Deep merge updates into base dict, modifying base in place."""
    for key, value in updates.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(cast(Dict[str, Any], base[key]), cast(Dict[str, Any], value))
        else:
            base[key] = value


def _print_detection_results(detected: Dict[str, Any]) -> None:
    """Print project detection results."""
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

    # Show tool availability
    if detected.get("missing_tools"):
        print("⚠️  Missing Tools (checks will be disabled):")
        for tool_name, check_name, install_cmd in detected["missing_tools"]:
            print(f"     • {tool_name} → {check_name}")
            print(f"       Install: {install_cmd}")
        print()
        print("   After installing, re-run: sm init")
        print()

    print(f"  Recommended profile: {detected['recommended_profile']}")
    if detected["recommended_gates"]:
        print(f"  Recommended gates:   {', '.join(detected['recommended_gates'])}")
    print()


def _build_non_interactive_config(
    detected: Dict[str, Any], preconfig: Dict[str, Any]
) -> Dict[str, Any]:
    """Build config using detected defaults and preconfig."""
    config: Dict[str, Any] = {
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
        "enabled_gates": preconfig.get("enabled_gates", detected["recommended_gates"]),
    }
    print("🤖 Non-interactive mode: using detected defaults")
    return config


def _build_interactive_config(
    detected: Dict[str, Any], preconfig: Dict[str, Any]
) -> Dict[str, Any]:
    """Build config via interactive prompts."""
    print("📝 Configuration (press Enter for defaults)")
    print("-" * 40)

    config: Dict[str, Any] = {}

    # Default profile
    default_profile = preconfig.get("default_profile", detected["recommended_profile"])
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
    return config


def _apply_detected_settings(
    base_config: Dict[str, Any], detected: Dict[str, Any]
) -> None:
    """Apply detected project settings to the base config."""
    if detected["has_python"]:
        base_config["python"]["enabled"] = True
        if detected["test_dirs"]:
            if "tests" in base_config["python"]["gates"]:
                base_config["python"]["gates"]["tests"]["test_dirs"] = detected[
                    "test_dirs"
                ]
        for gate in [
            "lint-format",
            "tests",
            "coverage",
            "static-analysis",
            "type-checking",
        ]:
            if gate in base_config["python"]["gates"]:
                base_config["python"]["gates"][gate]["enabled"] = True

    if detected["has_javascript"]:
        base_config["javascript"]["enabled"] = True
        for gate in ["lint-format", "tests"]:
            if gate in base_config["javascript"]["gates"]:
                base_config["javascript"]["gates"][gate]["enabled"] = True


def _apply_user_config(base_config: Dict[str, Any], config: Dict[str, Any]) -> None:
    """Apply user config overrides to base config."""
    base_config["default_profile"] = config.get("default_profile", "commit")

    # Apply disabled gates
    for gate_full_name in config.get("disabled_gates", []):
        if ":" not in gate_full_name and "-" in gate_full_name:
            parts = gate_full_name.split("-", 1)
            if len(parts) == 2:
                category, gate = parts[0], parts[1]
                if category in base_config and "gates" in base_config[category]:
                    if gate in base_config[category]["gates"]:
                        base_config[category]["gates"][gate]["enabled"] = False

    # Apply coverage threshold
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


def _disable_checks_with_missing_tools(
    base_config: Dict[str, Any], detected: Dict[str, Any]
) -> None:
    """Disable checks whose required tools are missing.

    This prevents ERROR status from missing tools - if the tool isn't
    available, the check is disabled rather than failing.
    """
    missing_tools = detected.get("missing_tools", [])
    if not missing_tools:
        return

    for _tool_name, check_name, _install_cmd in missing_tools:
        # Parse check name: "quality:dead-code" -> category="quality", gate="dead-code"
        if ":" not in check_name:
            continue
        category, gate = check_name.split(":", 1)

        if category in base_config and "gates" in base_config[category]:
            if gate in base_config[category]["gates"]:
                base_config[category]["gates"][gate]["enabled"] = False


def _print_next_steps(config: Dict[str, Any]) -> None:
    """Print next steps after setup completion."""
    print()
    print("🚀 Setup Complete!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Review the report card below to see where the repo stands")
    print("  2. Disable any gates you're not ready for: sm config --disable <gate>")
    print("  3. Run 'sm validate commit' and fix what fails")
    print("  4. Gradually enable more gates and tighten thresholds over time")
    print()
    print("Quick reference:")
    print("  sm validate commit   # Fast pre-commit validation")
    print("  sm validate pr       # Full PR validation")
    print("  sm status            # Full report card (no fail-fast)")
    print("  sm config --show     # View current gate settings")
    print()


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
    from slopmop.reporting import print_project_header

    print_project_header(str(project_root))
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
    _print_detection_results(detected)

    # Build configuration
    if args.non_interactive:
        config = _build_non_interactive_config(detected, preconfig)
    else:
        config = _build_interactive_config(detected, preconfig)

    # Write configuration
    print("💾 Writing configuration...")

    from slopmop.utils.generate_base_config import (
        backup_config,
        generate_base_config,
        write_template_config,
    )

    template_path = write_template_config(project_root)
    print(f"📄 Template saved to: {template_path}")

    base_config = generate_base_config()
    _apply_detected_settings(base_config, detected)
    _apply_user_config(base_config, config)
    _disable_checks_with_missing_tools(base_config, detected)

    # Merge with existing config if present
    if config_file.exists():
        try:
            existing = json.loads(config_file.read_text())
            backup_path = backup_config(config_file)
            if backup_path:
                print(f"📦 Backed up existing config to: {backup_path}")
            _deep_merge(base_config, existing)
        except json.JSONDecodeError:
            pass

    config_file.write_text(json.dumps(base_config, indent=2) + "\n")
    print(f"✅ Configuration saved to: {config_file}")

    _print_next_steps(config)

    # Run status to show the user where the repo stands
    print("─" * 60)
    print("Running all gates to show current repo status...")
    print("─" * 60)

    from slopmop.cli.status import run_status

    run_status(project_root=str(project_root))

    return 0
