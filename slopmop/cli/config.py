"""Config command for slop-mop CLI."""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, cast

from slopmop.checks import ensure_checks_registered
from slopmop.checks.base import GateCategory
from slopmop.core.registry import get_registry


def _normalize_flat_keys(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize flat 'category:gate' keys into hierarchical config.

    Converts flat keys like ``{"laziness:dead-code.py": {"whitelist_file": "w.py"}}``
    into the nested structure the runtime expects::

        {"laziness": {"gates": {"dead-code.py": {"whitelist_file": "w.py"}}}}

    Keys that are NOT in ``category:gate`` format are passed through unchanged.
    If a key matches a GateCategory but has no colon, it's also passed through
    (it's already a category-level dict).
    """
    category_keys = {cat.key for cat in GateCategory}
    normalized: Dict[str, Any] = {}

    for key, value in data.items():
        if ":" in key:
            parts = key.split(":", 1)
            category, gate_name = parts[0], parts[1]
            if category in category_keys and isinstance(value, dict):
                # Merge into hierarchical structure
                if category not in normalized:
                    normalized[category] = {}
                cat_dict = normalized[category]
                if "gates" not in cat_dict:
                    cat_dict["gates"] = {}
                cat_dict["gates"][gate_name] = value
                continue
        # Pass through non-flat keys — deep-merge if both sides are dicts
        # (avoids overwriting flat-key data already accumulated for the
        # same category, e.g. "laziness:dead-code.py" followed by "laziness")
        if (
            key in normalized
            and isinstance(normalized[key], dict)
            and isinstance(value, dict)
        ):
            normalized[key] = _deep_merge(
                cast(Dict[str, Any], normalized[key]),
                cast(Dict[str, Any], value),
            )
        else:
            normalized[key] = value

    return normalized


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Deep-merge overlay into base, returning the merged result.

    For nested dicts, merge recursively. For all other types, overlay wins.
    """
    merged = base.copy()
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(
                cast(Dict[str, Any], merged[key]),
                cast(Dict[str, Any], value),
            )
        else:
            merged[key] = value
    return merged


def _update_from_json(config_file: Path, config: dict[str, Any], json_path: str) -> int:
    """Update config from a JSON file.

    Accepts both flat (``"category:gate"``) and hierarchical formats.
    Flat keys are normalized to hierarchical before merging so the
    runtime can always find them at ``config[category]["gates"][gate]``.
    """
    json_file = Path(json_path)
    if not json_file.exists():
        print(f"❌ Config file not found: {json_path}")
        return 1
    try:
        new_config = json.loads(json_file.read_text())
        normalized = _normalize_flat_keys(new_config)
        merged = _deep_merge(config, normalized)
        config.clear()
        config.update(merged)
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

    # Show swabbing-time setting
    swabbing_time = config.get("swabbing_time")
    if isinstance(swabbing_time, (int, float)) and swabbing_time > 0:
        print(f"⏱️  Swabbing-time budget: {int(swabbing_time)}s")
    else:
        print("⏱️  Swabbing-time budget: no limit")
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
    print("📦 Aliases:")
    print("-" * 40)
    for alias, gates in sorted(registry.list_aliases().items()):
        print(f"  {alias}: {', '.join(gates)}")

    print()
    return 0


def _set_swabbing_time(config_file: Path, config: dict[str, Any], seconds: int) -> int:
    """Set or disable the swabbing-time budget."""
    if seconds <= 0:
        config.pop("swabbing_time", None)
        config_file.write_text(json.dumps(config, indent=2))
        print("✅ Swabbing-time budget disabled (no limit)")
    else:
        config["swabbing_time"] = seconds
        config_file.write_text(json.dumps(config, indent=2))
        print(f"✅ Swabbing-time budget set to {seconds}s")
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

    if getattr(args, "swabbing_time", None) is not None:
        return _set_swabbing_time(config_file, config, args.swabbing_time)

    # Default: show config
    return _show_config(project_root, config_file, config)
