"""Config command for slop-mop CLI."""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, cast

from slopmop.checks import ensure_checks_registered
from slopmop.checks.base import GateCategory
from slopmop.core.registry import get_registry


def _normalize_flat_keys(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize flat 'category:gate' keys into hierarchical config.

    Converts flat keys like ``{"laziness:dead-code": {"whitelist_file": "w.py"}}``
    into the nested structure the runtime expects::

        {"laziness": {"gates": {"dead-code": {"whitelist_file": "w.py"}}}}

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
        # Pass through non-flat keys unchanged
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


VALID_CATEGORIES = {cat.key for cat in GateCategory}


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
        print(f"   Expected: CATEGORY:DIR (e.g., overconfidence:src, laziness:lib)")
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
