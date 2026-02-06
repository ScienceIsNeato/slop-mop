"""Config command for slop-mop CLI."""

import argparse
import json
from pathlib import Path
from typing import Any, cast

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

    # Default: show config
    return _show_config(project_root, config_file, config)
