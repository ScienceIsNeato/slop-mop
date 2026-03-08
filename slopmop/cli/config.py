"""Config command for slop-mop CLI."""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, cast

from slopmop.checks import ensure_checks_registered
from slopmop.checks.base import GateCategory
from slopmop.constants import ROLE_BADGES
from slopmop.core.registry import get_registry


def _is_gate_enabled(cfg: dict[str, Any], full_name: str) -> bool:
    """Return whether a gate is enabled across both config representations."""
    disabled = cfg.get("disabled_gates", [])
    if isinstance(disabled, list) and full_name in disabled:
        return False
    if ":" not in full_name:
        return True

    category, gate = full_name.split(":", 1)
    gate_cfg = (
        (cfg.get(category) or {}).get("gates", {}).get(gate)
        if isinstance(cfg.get(category), dict)
        else None
    )
    if isinstance(gate_cfg, dict) and "enabled" in gate_cfg:
        return bool(gate_cfg.get("enabled"))
    return True


def _set_gate_enabled(cfg: dict[str, Any], full_name: str, enabled: bool) -> None:
    """Set gate enabled state in both nested and legacy config forms."""
    if ":" in full_name:
        category, gate = full_name.split(":", 1)
        cat = cfg.setdefault(category, {})
        if isinstance(cat, dict):
            gates = cat.setdefault("gates", {})
            if isinstance(gates, dict):
                gate_cfg = gates.setdefault(gate, {})
                if isinstance(gate_cfg, dict):
                    gate_cfg["enabled"] = enabled

    disabled = cfg.get("disabled_gates", [])
    if not isinstance(disabled, list):
        disabled = []
    if enabled:
        disabled = [g for g in disabled if g != full_name]
    elif full_name not in disabled:
        disabled.append(full_name)
    cfg["disabled_gates"] = disabled


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


def _enable_gate(
    config_file: Path,
    config: dict[str, Any],
    gate_name: str,
    project_root: Path,
) -> int:
    """Enable a disabled gate."""

    registry = get_registry()
    check = registry.get_check(gate_name, config)
    if check is None:
        print(f"❌ Unknown gate: {gate_name}")
        return 1
    if not check.is_applicable(str(project_root)):
        reason = check.skip_reason(str(project_root))
        print(f"❌ Cannot enable {gate_name}: not applicable for this repo ({reason})")
        print("💡 If you've added a new language, re-run: sm init --non-interactive")
        return 1

    if not _is_gate_enabled(config, gate_name):
        _set_gate_enabled(config, gate_name, True)
        config_file.write_text(json.dumps(config, indent=2))
        print(f"✅ Enabled: {gate_name}")
    else:
        print(f"ℹ️  {gate_name} is already enabled")
    return 0


def _disable_gate(config_file: Path, config: dict[str, Any], gate_name: str) -> int:
    """Disable a gate."""
    currently_disabled = not _is_gate_enabled(config, gate_name)

    if not currently_disabled:
        _set_gate_enabled(config, gate_name, False)
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
    checks = []
    for name in registry.list_checks():
        check = registry.get_check(name, config)
        if check is None:
            continue
        if check.is_applicable(str(project_root)):
            checks.append(name)

    for name in sorted(checks):
        status = "❌ DISABLED" if not _is_gate_enabled(config, name) else "✅ ENABLED"
        definition = registry.get_definition(name)
        display = definition.name if definition else name
        check = registry.get_check(name, config)
        badge = ROLE_BADGES.get(check.role.value, "") if check else ""
        print(f"  {status}  {badge}{display}")
        print(f"             gate: {name}")

    if not checks:
        print("  (No applicable gates for this repository)")

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

    # Make custom gates visible/manageable in this command path too.
    from slopmop.checks.custom import register_custom_gates

    register_custom_gates(config)

    if args.json:
        return _update_from_json(config_file, config, args.json)

    if args.enable:
        return _enable_gate(config_file, config, args.enable, project_root)

    if args.disable:
        return _disable_gate(config_file, config, args.disable)

    if getattr(args, "swabbing_time", None) is not None:
        return _set_swabbing_time(config_file, config, args.swabbing_time)

    if args.show:
        return _show_config(project_root, config_file, config)

    # Default: show usage hints
    print("\n📋 Slop-Mop Configuration")
    print("=" * 60)
    from slopmop.reporting import print_project_header

    print_project_header(str(project_root))
    print()
    print("Usage:")
    print("  sm config --show                   Show full config")
    print("  sm config --enable  <gate>         Enable a gate")
    print("  sm config --disable <gate>         Disable a gate")
    print("  sm config --swabbing-time <secs>   Set time budget")
    print("  sm config --json <file>            Merge config JSON")
    print()

    registry = get_registry()
    checks = []
    for name in sorted(registry.list_checks()):
        check = registry.get_check(name, config)
        if check is None:
            continue
        if check.is_applicable(str(project_root)):
            checks.append(name)
    n_disabled = sum(1 for c in checks if not _is_gate_enabled(config, c))

    print(
        f"  {len(checks)} applicable gates"
        f" ({len(checks) - n_disabled} enabled,"
        f" {n_disabled} disabled)"
    )
    print()
    print("Examples:")
    if checks:
        example = checks[0]
        print(f"  sm config --disable {example}")
        print(f"  sm config --enable  {example}")
    print()
    print("Run 'sm config --show' to see all gates.")
    print()
    return 0
