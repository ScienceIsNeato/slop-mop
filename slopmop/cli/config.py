"""Config command for slop-mop CLI."""

import argparse
import json
from pathlib import Path
from typing import Any, Optional, Tuple, cast

from slopmop.checks import ensure_checks_registered
from slopmop.core.registry import get_registry


def _update_from_json(config_file: Path, config: dict[str, Any], json_path: str) -> int:
    """Update config from a JSON file."""
    json_file = Path(json_path)
    if not json_file.exists():
        print(f"❌ Config file not found: {json_path}")
        return 1
    try:
        new_config = json.loads(json_file.read_text())
        config.update(new_config)
        config_file.write_text(json.dumps(config, indent=2))
        print(f"✅ Configuration updated from {json_path}")
    except json.JSONDecodeError:
        print(f"❌ Invalid JSON in {json_path}")
        return 1
    return 0


def _enable_gate(config_file: Path, config: dict[str, Any], gate_name: str) -> int:
    """Enable a disabled gate."""
    disabled = config.get("disabled_gates", [])
    if gate_name in disabled:
        disabled.remove(gate_name)
        config["disabled_gates"] = disabled
        config_file.write_text(json.dumps(config, indent=2))
        print(f"✅ Enabled: {gate_name}")
    else:
        print(f"ℹ️  {gate_name} is already enabled")
    return 0


def _disable_gate(config_file: Path, config: dict[str, Any], gate_name: str) -> int:
    """Disable a gate."""
    disabled = config.get("disabled_gates", [])
    if gate_name not in disabled:
        disabled.append(gate_name)
        config["disabled_gates"] = disabled
        config_file.write_text(json.dumps(config, indent=2))
        print(f"✅ Disabled: {gate_name}")
    else:
        print(f"ℹ️  {gate_name} is already disabled")
    return 0


VALID_CATEGORIES = {
    "python",
    "javascript",
    "security",
    "quality",
    "integration",
}


def _parse_category_dir(spec: str) -> Optional[Tuple[str, str]]:
    """Parse CATEGORY:DIR specification.

    Returns:
        Tuple of (category, directory) or None if invalid.
    """
    if ":" not in spec:
        return None
    parts = spec.split(":", 1)
    if len(parts) != 2:
        return None
    category, directory = parts[0].lower(), parts[1]
    if category not in VALID_CATEGORIES:
        return None
    return category, directory


def _add_include_dir(config_file: Path, config: dict[str, Any], spec: str) -> int:
    """Add a directory to a category's include list."""
    parsed = _parse_category_dir(spec)
    if not parsed:
        print(f"❌ Invalid format: {spec}")
        print(f"   Expected: CATEGORY:DIR (e.g., python:src, quality:lib)")
        print(f"   Valid categories: {', '.join(sorted(VALID_CATEGORIES))}")
        return 1

    category, directory = parsed
    if category not in config:
        config[category] = {}
    if "include_dirs" not in config[category]:
        config[category]["include_dirs"] = []

    if directory in config[category]["include_dirs"]:
        print(f"ℹ️  {directory} is already in {category} include_dirs")
    else:
        config[category]["include_dirs"].append(directory)
        config_file.write_text(json.dumps(config, indent=2))
        print(f"✅ Added {directory} to {category} include_dirs")
    return 0


def _add_exclude_dir(config_file: Path, config: dict[str, Any], spec: str) -> int:
    """Add a directory to a category's exclude list."""
    parsed = _parse_category_dir(spec)
    if not parsed:
        print(f"❌ Invalid format: {spec}")
        print(
            f"   Expected: CATEGORY:DIR (e.g., overconfidence:py-tests, quality:vendor)"
        )
        print(f"   Valid categories: {', '.join(sorted(VALID_CATEGORIES))}")
        return 1

    category, directory = parsed
    if category not in config:
        config[category] = {}
    if "exclude_dirs" not in config[category]:
        config[category]["exclude_dirs"] = []

    if directory in config[category]["exclude_dirs"]:
        print(f"ℹ️  {directory} is already in {category} exclude_dirs")
    else:
        config[category]["exclude_dirs"].append(directory)
        config_file.write_text(json.dumps(config, indent=2))
        print(f"✅ Added {directory} to {category} exclude_dirs")
    return 0


def _show_config(project_root: Path, config_file: Path, config: dict[str, Any]) -> int:
    """Display current configuration."""
    print("\n📋 Slop-Mop Configuration")
    print("=" * 60)
    from slopmop.reporting import print_project_header

    print_project_header(str(project_root))
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


def cmd_config(args: argparse.Namespace) -> int:
    """Handle the config command."""
    ensure_checks_registered()

    project_root = Path(args.project_root).resolve()
    config_file = project_root / ".sb_config.json"

    # Load existing config
    config: dict[str, Any] = {}
    if config_file.exists():
        try:
            config = cast(dict[str, Any], json.loads(config_file.read_text()))
        except json.JSONDecodeError:
            print(f"⚠️  Invalid JSON in {config_file}")

    if args.json:
        return _update_from_json(config_file, config, args.json)

    if args.enable:
        return _enable_gate(config_file, config, args.enable)

    if args.disable:
        return _disable_gate(config_file, config, args.disable)

    if args.include_dir:
        return _add_include_dir(config_file, config, args.include_dir)

    if args.exclude_dir:
        return _add_exclude_dir(config_file, config, args.exclude_dir)

    # Default: show config
    return _show_config(project_root, config_file, config)
