"""Config command for slop-mop CLI."""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, cast

from slopmop.checks import ensure_checks_registered
from slopmop.checks.base import GateCategory, GateLevel
from slopmop.constants import ROLE_BADGES
from slopmop.core.config import clear_current_pr_number as clear_current_pr_selection
from slopmop.core.config import (
    get_current_pr_number,
)
from slopmop.core.config import set_current_pr_number as set_current_pr_selection
from slopmop.core.registry import get_registry

_UNKNOWN_GATE_MSG = "❌ Unknown gate: {gate_name}"


def _as_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    return None


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items = cast(list[Any], value)
    result: list[str] = []
    for item in items:
        if isinstance(item, str):
            result.append(item)
    return result


def _is_gate_enabled(cfg: dict[str, Any], full_name: str) -> bool:
    """Return whether a gate is enabled across both config representations."""
    disabled = _as_str_list(cfg.get("disabled_gates", []))
    if full_name in disabled:
        return False
    if ":" not in full_name:
        return True

    category, gate = full_name.split(":", 1)
    category_cfg = _as_dict(cfg.get(category))
    gates_cfg = _as_dict(category_cfg.get("gates") if category_cfg else None)
    gate_cfg = _as_dict(gates_cfg.get(gate) if gates_cfg else None)
    if isinstance(gate_cfg, dict) and "enabled" in gate_cfg:
        return bool(gate_cfg.get("enabled"))
    return True


def _set_gate_enabled(cfg: dict[str, Any], full_name: str, enabled: bool) -> None:
    """Set gate enabled state in both nested and legacy config forms."""
    if ":" in full_name:
        category, gate = full_name.split(":", 1)
        cat_any = _as_dict(cfg.get(category))
        cat: dict[str, Any]
        if cat_any is not None:
            cat = cat_any
        else:
            cat = {}
            cfg[category] = cat

        gates_any = _as_dict(cat.get("gates"))
        gates: dict[str, Any]
        if gates_any is not None:
            gates = gates_any
        else:
            gates = {}
            cat["gates"] = gates

        gate_cfg_any = _as_dict(gates.get(gate))
        gate_cfg: dict[str, Any]
        if gate_cfg_any is not None:
            gate_cfg = gate_cfg_any
        else:
            gate_cfg = {}
            gates[gate] = gate_cfg
        gate_cfg["enabled"] = enabled

    disabled = _as_str_list(cfg.get("disabled_gates", []))
    if enabled:
        disabled = [g for g in disabled if g != full_name]
    elif full_name not in disabled:
        disabled.append(full_name)
    cfg["disabled_gates"] = disabled


def _gate_cfg_dict(cfg: dict[str, Any], full_name: str) -> dict[str, Any] | None:
    """Return the nested gate config dict, creating parents as needed."""
    if ":" not in full_name:
        return None
    category, gate = full_name.split(":", 1)
    category_cfg = _as_dict(cfg.get(category))
    if category_cfg is None:
        category_cfg = {}
        cfg[category] = category_cfg
    gates_cfg = _as_dict(category_cfg.get("gates"))
    if gates_cfg is None:
        gates_cfg = {}
        category_cfg["gates"] = gates_cfg
    gate_cfg = _as_dict(gates_cfg.get(gate))
    if gate_cfg is None:
        gate_cfg = {}
        gates_cfg[gate] = gate_cfg
    return gate_cfg


def _gate_field_definition(
    config: dict[str, Any], full_name: str, field_name: str
) -> Any:
    """Return the ConfigField definition for a gate field, if it exists."""
    registry = get_registry()
    check = registry.get_check(full_name, config)
    if check is None:
        return None
    for field in check.get_full_config_schema():
        if field.name == field_name:
            return field
    return None


def _parse_field_value(field: Any, raw_value: str) -> Any:
    """Parse a CLI string into the field's configured type."""
    field_type = getattr(field, "field_type", "string")
    if field_type == "integer":
        return int(raw_value)
    if field_type == "boolean":
        normalized = raw_value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
        raise ValueError("expected boolean true/false")
    if field_type == "string[]":
        value = raw_value.strip()
        if value.startswith("["):
            parsed: list[Any] = json.loads(value)
            if not isinstance(parsed, list) or not all(
                isinstance(item, str) for item in parsed
            ):
                raise ValueError("expected JSON array of strings")
            return parsed
        if not value:
            return []
        return [item.strip() for item in value.split(",") if item.strip()]
    return raw_value


def _set_gate_field(
    config_file: Path,
    config: dict[str, Any],
    gate_name: str,
    field_name: str,
    raw_value: str,
) -> int:
    """Set a gate-specific config field from the CLI."""
    if field_name == "enabled":
        print("❌ Use --enable/--disable for the enabled field")
        return 1
    if field_name == "run_on":
        print("❌ Use --swab-on/--swab-off for the run_on field")
        return 1

    field = _gate_field_definition(config, gate_name, field_name)
    if field is None:
        print(f"❌ Unknown config field for {gate_name}: {field_name}")
        return 1

    try:
        parsed_value = _parse_field_value(field, raw_value)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"❌ Invalid value for {gate_name}.{field_name}: {exc}")
        return 1

    gate_cfg = _gate_cfg_dict(config, gate_name)
    if gate_cfg is None:
        print(_UNKNOWN_GATE_MSG.format(gate_name=gate_name))
        return 1
    gate_cfg[field_name] = parsed_value
    config_file.write_text(json.dumps(config, indent=2))
    print(f"✅ Set {gate_name}.{field_name} = {parsed_value!r}")
    return 0


def _unset_gate_field(
    config_file: Path,
    config: dict[str, Any],
    gate_name: str,
    field_name: str,
) -> int:
    """Remove a gate-specific config field override from the CLI."""
    if field_name == "enabled":
        print("❌ Use --enable/--disable for the enabled field")
        return 1
    if field_name == "run_on":
        print("❌ Use --swab-on/--swab-off for the run_on field")
        return 1

    field = _gate_field_definition(config, gate_name, field_name)
    if field is None:
        print(f"❌ Unknown config field for {gate_name}: {field_name}")
        return 1

    gate_cfg = _gate_cfg_dict(config, gate_name)
    if gate_cfg is None:
        print(_UNKNOWN_GATE_MSG.format(gate_name=gate_name))
        return 1
    if field_name in gate_cfg:
        gate_cfg.pop(field_name, None)
        config_file.write_text(json.dumps(config, indent=2))
        print(f"✅ Unset {gate_name}.{field_name}")
    else:
        print(
            f"ℹ️  {gate_name}.{field_name} is already using its default/discovered value"
        )
    return 0


def _set_gate_run_on(cfg: dict[str, Any], full_name: str, level: GateLevel) -> None:
    """Set the configured swab/scour membership for a gate."""
    gate_cfg = _gate_cfg_dict(cfg, full_name)
    if gate_cfg is not None:
        gate_cfg["run_on"] = level.value


def _configured_run_on(check: Any) -> str:
    """Human-readable swab/scour membership for a check instance."""
    level = getattr(check, "effective_level", getattr(check, "level", GateLevel.SWAB))
    return "scour only" if level == GateLevel.SCOUR else "swab + scour"


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
        print(_UNKNOWN_GATE_MSG.format(gate_name=gate_name))
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

    # Run doctor readiness check for the gate so the user sees what's
    # missing before their first run.  Informational only — never
    # blocks enable, and a bug in doctor must not break config.
    try:
        from slopmop.checks.base import find_tool

        ensure_checks_registered()
        registry = get_registry()
        check = registry.get_check(gate_name, config)
        if check is not None:
            missing = [
                t
                for t in check.required_tools
                if find_tool(t, str(project_root)) is None
            ]
            if missing:
                hint = check.install_hint
                print(f"\n  ⚠️  Missing tools: {', '.join(missing)}")
                if hint == "pip":
                    print(f"     → pip install {' '.join(missing)}")
                else:
                    for t in missing:
                        print(f"     → Install {t} and ensure it is on PATH")
    except (ImportError, KeyError, ValueError, OSError) as exc:
        import logging

        logging.getLogger("slopmop.cli.config").debug(
            "Doctor readiness check failed for %s: %s", gate_name, exc
        )

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
    current_pr_number = get_current_pr_number(project_root)
    if isinstance(current_pr_number, int):
        print(f"🔀 Current PR number: {current_pr_number}")
    else:
        print("🔀 Current PR number: none selected")
    print()

    registry = get_registry()

    def _gate_cfg_view(full_name: str) -> dict[str, Any]:
        if ":" not in full_name:
            return {}
        category, gate = full_name.split(":", 1)
        category_cfg = _as_dict(config.get(category))
        gates_cfg = _as_dict(category_cfg.get("gates") if category_cfg else None)
        gate_cfg = _as_dict(gates_cfg.get(gate) if gates_cfg else None)
        if gate_cfg is None:
            return {}
        return dict(gate_cfg)

    def _format_explicit_fields(full_name: str, check: Any) -> list[str]:
        gate_cfg = _gate_cfg_view(full_name)
        items: list[str] = []
        for key, value in gate_cfg.items():
            if key in {"enabled", "run_on"}:
                continue
            default = None
            for field in check.get_full_config_schema():
                if field.name == key:
                    default = field.default
                    break
            if value == default:
                continue
            items.append(f"{key}={value!r}")
        return items

    # Show all available gates
    print("🔍 Available Quality Gates:")
    print("-" * 40)
    checks: list[str] = []
    check_names: list[str] = []
    for name_any in registry.list_checks():
        if isinstance(name_any, str):
            check_names.append(name_any)
    for name in check_names:
        check = registry.get_check(name, config)
        if check is None:
            continue
        if check.is_applicable(str(project_root)):
            checks.append(name)

    for name in sorted(checks):
        status = "❌ DISABLED" if not _is_gate_enabled(config, name) else "✅ ENABLED"
        definition = registry.get_definition(name)
        display = str(getattr(definition, "name", name))
        check = registry.get_check(name, config)
        badge = ROLE_BADGES.get(
            str(getattr(getattr(check, "role", None), "value", "")), ""
        )
        if check is None:
            badge = ""
        print(f"  {status}  {badge}{display}")
        print(f"             gate: {name}")
        if check is not None:
            print(f"             runs: {_configured_run_on(check)}")
            explicit_fields = _format_explicit_fields(name, check)
            if explicit_fields:
                print(f"             config: {', '.join(explicit_fields)}")

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


def _set_gate_swab_membership(
    config_file: Path,
    config: dict[str, Any],
    gate_name: str,
    level: GateLevel,
    project_root: Path,
) -> int:
    """Keep a gate in swab+scour or move it to scour-only."""
    registry = get_registry()
    check = registry.get_check(gate_name, config)
    if check is None:
        print(_UNKNOWN_GATE_MSG.format(gate_name=gate_name))
        return 1
    if not check.is_applicable(str(project_root)):
        reason = check.skip_reason(str(project_root))
        print(f"❌ Cannot update {gate_name}: not applicable for this repo ({reason})")
        return 1
    _set_gate_run_on(config, gate_name, level)
    config_file.write_text(json.dumps(config, indent=2))
    if level == GateLevel.SCOUR:
        print(f"✅ {gate_name} will now skip swab and still run during scour")
    else:
        print(f"✅ {gate_name} will now run during both swab and scour")
    return 0


def _set_current_pr_number(
    config_file: Path,
    config: dict[str, Any],
    pr_number: int,
) -> int:
    """Set the repo's working PR number."""

    if pr_number <= 0:
        print("❌ Current PR number must be a positive integer")
        return 1
    set_current_pr_selection(config_file.parent, pr_number)
    if "current_pr_number" in config:
        config.pop("current_pr_number", None)
        config_file.write_text(json.dumps(config, indent=2))
    print(f"✅ Current PR number set to {pr_number}")
    return 0


def _clear_current_pr_number(config_file: Path, config: dict[str, Any]) -> int:
    """Clear the repo's working PR number."""

    clear_current_pr_selection(config_file.parent)
    if "current_pr_number" in config:
        config.pop("current_pr_number", None)
        config_file.write_text(json.dumps(config, indent=2))
    print("✅ Current PR number cleared")
    return 0


def _show_usage_hints(project_root: Path, config: dict[str, Any]) -> int:
    """Print the compact no-args config help screen."""
    print("\n📋 Slop-Mop Configuration")
    print("=" * 60)
    from slopmop.reporting import print_project_header

    print_project_header(str(project_root))
    print()
    print("Usage:")
    print("  sm config --show                   Show full config")
    print("  sm config --enable  <gate>         Enable a gate")
    print("  sm config --disable <gate>         Disable a gate")
    print("  sm config --swab-off <gate>        Keep gate out of swab")
    print("  sm config --swab-on  <gate>        Run gate in swab + scour")
    print("  sm config --set <gate> <field> <value>    Set a gate field")
    print("  sm config --unset <gate> <field>          Remove a gate field override")
    print("  sm config --swabbing-time <secs>   Set time budget")
    print("  sm config --current-pr-number <n>  Select working PR")
    print("  sm config --clear-current-pr       Clear selected PR")
    print("  sm config --json <file>            Merge config JSON")
    print()

    registry = get_registry()
    checks = [
        name
        for name_any in registry.list_checks()
        if isinstance(name_any, str)
        for name in [name_any]
        if (check := registry.get_check(name, config)) is not None
        and check.is_applicable(str(project_root))
    ]
    n_disabled = sum(
        1 for gate_name in checks if not _is_gate_enabled(config, gate_name)
    )

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

    if getattr(args, "swab_off", None):
        return _set_gate_swab_membership(
            config_file,
            config,
            args.swab_off,
            GateLevel.SCOUR,
            project_root,
        )

    if getattr(args, "swab_on", None):
        return _set_gate_swab_membership(
            config_file,
            config,
            args.swab_on,
            GateLevel.SWAB,
            project_root,
        )

    if getattr(args, "set_field", None):
        gate_name, field_name, raw_value = args.set_field
        return _set_gate_field(
            config_file,
            config,
            gate_name,
            field_name,
            raw_value,
        )

    if getattr(args, "unset_field", None):
        gate_name, field_name = args.unset_field
        return _unset_gate_field(
            config_file,
            config,
            gate_name,
            field_name,
        )

    if getattr(args, "current_pr_number", None) is not None:
        return _set_current_pr_number(config_file, config, args.current_pr_number)

    if getattr(args, "clear_current_pr", False):
        return _clear_current_pr_number(config_file, config)

    if args.show:
        return _show_config(project_root, config_file, config)

    return _show_usage_hints(project_root, config)
