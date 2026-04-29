"""Built-in upgrade migrations for slop-mop installs.

Each migration is a deterministic Python function keyed by a version range.
When ``sm upgrade`` runs, applicable migrations execute in stepwise order
between the old and new package versions.

See ``DOCS/MIGRATIONS.md`` for the authoring process.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Sequence, cast

from packaging.version import Version

# ---------------------------------------------------------------------------
# Config file constant (matches slopmop.core.config.CONFIG_FILE)
# ---------------------------------------------------------------------------
_CONFIG_FILE = ".sb_config.json"


@dataclass(frozen=True)
class UpgradeMigration:
    """A deterministic built-in migration keyed by version range."""

    key: str
    min_version: str
    max_version: str
    apply: Callable[[Path], None]

    @property
    def sort_key(self) -> tuple[Version, Version, str]:
        """Deterministic ordering for stepwise upgrade execution."""
        return (Version(self.max_version), Version(self.min_version), self.key)

    def applies(self, from_version: str, to_version: str) -> bool:
        from_v = Version(from_version)
        to_v = Version(to_version)
        return from_v < Version(self.max_version) <= to_v and from_v >= Version(
            self.min_version
        )


@dataclass(frozen=True)
class StaleGateReference:
    """A config reference to a gate that is no longer registered."""

    reference: str
    location: str
    replacements: tuple[str, ...] = ()


_CONFIG_CATEGORY_KEYS = {
    "deceptiveness",
    "laziness",
    "myopia",
    "overconfidence",
    "quality",
}


# ===================================================================
# Migration: rename-source-duplication-gates (0.11.0 → 0.11.1)
# ===================================================================

# jscpd-specific config keys → laziness:repeated-code
_JSCPD_KEYS = {"threshold", "min_tokens", "min_lines"}
# Keys inherited by both successor gates
_SHARED_KEYS = {"include_dirs", "exclude_dirs", "enabled"}


def _split_duplication_config(
    old_cfg: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Split a source-duplication config dict into repeated-code + ambiguity-mines."""
    repeated: Dict[str, Any] = {}
    ambiguity: Dict[str, Any] = {}
    for key, value in old_cfg.items():
        if key in _JSCPD_KEYS:
            repeated[key] = value
        elif key in _SHARED_KEYS:
            repeated[key] = value
            ambiguity[key] = value
        else:
            # Unknown keys preserved on both sides as a safety measure
            repeated[key] = value
            ambiguity[key] = value
    return repeated, ambiguity


def _rename_source_duplication(project_root: Path) -> None:
    """Rename myopia:source-duplication → laziness:repeated-code + myopia:ambiguity-mines.py."""
    config_path = project_root / _CONFIG_FILE
    if not config_path.exists():
        return

    try:
        raw = config_path.read_text(encoding="utf-8")
        data: Dict[str, Any] = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return

    changed = False

    # --- Hierarchical format: myopia → gates → source-duplication -----------
    myopia_raw = data.get("myopia")
    if isinstance(myopia_raw, dict):
        myopia_dict: Dict[str, Any] = cast(Dict[str, Any], myopia_raw)
        gates_raw = myopia_dict.get("gates")
        if isinstance(gates_raw, dict) and "source-duplication" in gates_raw:
            gates_dict: Dict[str, Any] = cast(Dict[str, Any], gates_raw)
            old_cfg = cast(Dict[str, Any], gates_dict.pop("source-duplication"))
            repeated_cfg, ambiguity_cfg = _split_duplication_config(old_cfg)

            gates_dict["ambiguity-mines.py"] = ambiguity_cfg

            laziness_raw = data.setdefault("laziness", {})
            if not isinstance(laziness_raw, dict):
                laziness_raw = {}
                data["laziness"] = laziness_raw
            laziness_dict: Dict[str, Any] = cast(Dict[str, Any], laziness_raw)
            laziness_dict.setdefault("enabled", True)
            laz_gates: Dict[str, Any] = laziness_dict.setdefault("gates", {})
            laz_gates["repeated-code"] = repeated_cfg
            changed = True

    # --- Flat format: "myopia:source-duplication" ---------------------------
    flat_key = "myopia:source-duplication"
    if flat_key in data:
        old_cfg = cast(Dict[str, Any], data.pop(flat_key))
        repeated_cfg, ambiguity_cfg = _split_duplication_config(old_cfg)
        data["myopia:ambiguity-mines.py"] = ambiguity_cfg
        data["laziness:repeated-code"] = repeated_cfg
        changed = True

    # --- disabled_gates list ------------------------------------------------
    disabled_raw = data.get("disabled_gates")
    if isinstance(disabled_raw, list):
        disabled_list: List[Any] = cast(List[Any], disabled_raw)
        new_disabled: List[str] = []
        for entry in disabled_list:
            gate_name: str = str(entry)
            if gate_name == "myopia:source-duplication":
                new_disabled.append("myopia:ambiguity-mines.py")
                new_disabled.append("laziness:repeated-code")
                changed = True
            else:
                new_disabled.append(gate_name)
        if changed:
            data["disabled_gates"] = new_disabled

    if changed:
        config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ===================================================================
# Migration: rename-dart-gates (0.11.1 → 0.12.0)
# ===================================================================

# Old dart gate names → new category:gate names
_DART_GATE_RENAMES: dict[str, str] = {
    "overconfidence:flutter-analyze": "overconfidence:missing-annotations.dart",
    "overconfidence:flutter-test": "overconfidence:untested-code.dart",
    "laziness:dart-format-check": "laziness:sloppy-formatting.dart",
    # Also handle bare names that may appear in disabled_gates
    "flutter-analyze": "overconfidence:missing-annotations.dart",
    "flutter-test": "overconfidence:untested-code.dart",
    "dart-format-check": "laziness:sloppy-formatting.dart",
}

_KNOWN_GATE_REPLACEMENTS: dict[str, tuple[str, ...]] = {
    "myopia:source-duplication": (
        "myopia:ambiguity-mines.py",
        "laziness:repeated-code",
    ),
    **{old_name: (new_name,) for old_name, new_name in _DART_GATE_RENAMES.items()},
}


def _replacement_for(reference: str) -> tuple[str, ...]:
    return _KNOWN_GATE_REPLACEMENTS.get(reference, ())


def _dedupe_stale_references(
    references: list[StaleGateReference],
) -> list[StaleGateReference]:
    seen: set[tuple[str, str]] = set()
    deduped: list[StaleGateReference] = []
    for reference in references:
        key = (reference.location, reference.reference)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(reference)
    return deduped


def find_stale_gate_references(
    config: dict[str, Any], registry_names: Sequence[str]
) -> list[StaleGateReference]:
    """Return stale gate references from both legacy and nested config forms."""
    registry_set = set(registry_names)
    stale: list[StaleGateReference] = []

    def _record(reference: str, location: str) -> None:
        if reference in registry_set:
            return
        replacements = _replacement_for(reference)
        if replacements or ":" in reference:
            stale.append(
                StaleGateReference(
                    reference=reference,
                    location=location,
                    replacements=replacements,
                )
            )

    disabled_raw = config.get("disabled_gates")
    if isinstance(disabled_raw, list):
        disabled_entries = cast(list[Any], disabled_raw)
        for entry in disabled_entries:
            if isinstance(entry, str):
                _record(entry, "disabled_gates")

    for key, value in config.items():
        if ":" in key and isinstance(value, dict):
            category = key.split(":", 1)[0]
            if category in _CONFIG_CATEGORY_KEYS:
                _record(key, "flat gate config")
            continue
        if key not in _CONFIG_CATEGORY_KEYS or not isinstance(value, dict):
            continue
        section = cast(dict[str, Any], value)
        gates_raw: object = section.get("gates")
        if not isinstance(gates_raw, dict):
            continue
        gates = cast(dict[str, Any], gates_raw)
        for gate_name_raw in gates:
            if isinstance(gate_name_raw, str):
                _record(f"{key}:{gate_name_raw}", f"{key}.gates")

    return _dedupe_stale_references(stale)


def stale_gate_reference_warnings(
    config: dict[str, Any], registry_names: Sequence[str]
) -> list[str]:
    """Format stale gate references as concise user-facing warnings."""
    warnings: list[str] = []
    for issue in find_stale_gate_references(config, registry_names):
        if issue.replacements:
            replacement = ", ".join(issue.replacements)
            warnings.append(
                "Stale slop-mop gate reference in "
                f"{issue.location}: {issue.reference} -> {replacement}. "
                "Run `sm init --non-interactive` or `sm upgrade` to migrate config."
            )
        else:
            warnings.append(
                "Unknown slop-mop gate reference in "
                f"{issue.location}: {issue.reference}. "
                "Run `sm config --show` to inspect available gates."
            )
    return warnings


def stamp_config_version(project_root: str | Path, version: str) -> None:
    """Persist the slop-mop package version that last wrote local config."""
    config_path = Path(project_root) / _CONFIG_FILE
    if not config_path.exists():
        return
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(data, dict):
        return
    config = cast(dict[str, Any], data)
    if config.get("slopmop_version") == version:
        return
    config["slopmop_version"] = version
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def migrate_known_config_references(project_root: str | Path) -> list[str]:
    """Apply known gate-reference migrations without needing version metadata."""
    root = Path(project_root)
    config_path = root / _CONFIG_FILE
    before = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    _rename_source_duplication(root)
    _rename_dart_gates(root)
    _rename_swabbing_time(root)
    after = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    return ["known-gate-reference-migrations"] if before != after else []


def _rename_dart_gates(project_root: Path) -> None:
    """Rename old flutter-analyze/flutter-test/dart-format-check gate references."""
    config_path = project_root / _CONFIG_FILE
    if not config_path.exists():
        return

    try:
        raw = config_path.read_text(encoding="utf-8")
        data: Dict[str, Any] = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return

    if not isinstance(data, dict):
        return

    changed = False

    # --- hierarchical format: {category: {gates: {old_name: cfg}}} ----------
    _DART_HIER_RENAMES: Dict[str, Dict[str, str]] = {
        "overconfidence": {
            "flutter-analyze": "missing-annotations.dart",
            "flutter-test": "untested-code.dart",
        },
        "laziness": {
            "dart-format-check": "sloppy-formatting.dart",
        },
    }
    for category, gate_map in _DART_HIER_RENAMES.items():
        cat_raw = data.get(category)
        if not isinstance(cat_raw, dict):
            continue
        gates_raw = cast(Dict[str, Any], cat_raw).get("gates")
        if not isinstance(gates_raw, dict):
            continue
        gates_dict: Dict[str, Any] = cast(Dict[str, Any], gates_raw)
        for old_name, new_name in gate_map.items():
            if old_name in gates_dict:
                gates_dict[new_name] = gates_dict.pop(old_name)
                changed = True

    # --- disabled_gates list ------------------------------------------------
    disabled_raw = data.get("disabled_gates")
    if isinstance(disabled_raw, list):
        disabled_list: List[Any] = cast(List[Any], disabled_raw)
        new_disabled: List[str] = []
        for entry in disabled_list:
            name: str = str(entry)
            mapped = _DART_GATE_RENAMES.get(name, name)
            if mapped != name:
                changed = True
            new_disabled.append(mapped)
        if changed:
            data["disabled_gates"] = new_disabled

    # --- flat colon-keyed gate config ---------------------------------------
    for old_key, new_key in list(_DART_GATE_RENAMES.items()):
        if ":" in old_key and old_key in data:
            data[new_key] = data.pop(old_key)
            changed = True

    if changed:
        config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ===================================================================
# Migration: rename-swabbing-time-to-timeout (0.14.1 → 0.15.0)
# ===================================================================


def _rename_swabbing_time(project_root: Path) -> None:
    """Rename config key swabbing_time → swabbing_timeout."""
    config_path = project_root / _CONFIG_FILE
    if not config_path.exists():
        return

    try:
        raw = config_path.read_text(encoding="utf-8")
        data: Dict[str, Any] = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return

    if not isinstance(data, dict):
        return

    if "swabbing_time" not in data:
        return

    if "swabbing_timeout" not in data:
        # Rename: no new key present yet — safe to migrate.
        data["swabbing_timeout"] = data.pop("swabbing_time")
    else:
        # New key already set — just drop the stale legacy key.
        del data["swabbing_time"]
    config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ===================================================================
# Migration: sync-built-in-gate-applicability (0.15.0 → 0.15.1)
# ===================================================================


def _sync_built_in_gate_applicability(project_root: Path) -> None:
    """Disable built-in gates that are no longer applicable for this repo.

    This is intentionally one-way: it turns stale enabled gates off when the
    current applicability rules say they should not run. It does NOT auto-enable
    newly applicable gates, which remains an intentional opt-in config action.
    """
    config_path = project_root / _CONFIG_FILE
    if not config_path.exists():
        return

    try:
        raw = config_path.read_text(encoding="utf-8")
        data: Dict[str, Any] = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return

    if not isinstance(data, dict):
        return

    from slopmop.checks import ensure_checks_registered
    from slopmop.core.registry import get_registry

    ensure_checks_registered()
    registry = get_registry()

    changed = False

    def _maybe_disable_gate(gate_cfg: Dict[str, Any]) -> bool:
        if gate_cfg.get("enabled") is False:
            return False
        gate_cfg["enabled"] = False
        return True

    for full_name_any in registry.list_checks():
        if not isinstance(full_name_any, str) or ":" not in full_name_any:
            continue
        full_name = full_name_any
        category, gate_name = full_name.split(":", 1)

        gate_configs: List[Dict[str, Any]] = []
        category_raw = data.get(category)
        if isinstance(category_raw, dict):
            category_dict = cast(Dict[str, Any], category_raw)
            gates_value: object = category_dict.get("gates")
            if isinstance(gates_value, dict) and gate_name in gates_value:
                gates_dict = cast(Dict[str, Any], gates_value)
                gate_cfg_value: object = gates_dict.get(gate_name)
                if isinstance(gate_cfg_value, dict):
                    gate_configs.append(cast(Dict[str, Any], gate_cfg_value))

        flat_gate_cfg = data.get(full_name)
        if isinstance(flat_gate_cfg, dict):
            gate_configs.append(cast(Dict[str, Any], flat_gate_cfg))

        if not gate_configs:
            continue

        check = registry.get_check(full_name, data)
        if check is None or check.is_applicable(str(project_root)):
            continue

        for gate_cfg in gate_configs:
            changed = _maybe_disable_gate(gate_cfg) or changed

    if changed:
        config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Migration registry
# ---------------------------------------------------------------------------

_MIGRATIONS: List[UpgradeMigration] = [
    UpgradeMigration(
        key="rename-source-duplication-gates",
        min_version="0.11.0",
        max_version="0.11.1",
        apply=_rename_source_duplication,
    ),
    UpgradeMigration(
        key="rename-dart-gates",
        min_version="0.11.1",
        max_version="0.12.0",
        apply=_rename_dart_gates,
    ),
    UpgradeMigration(
        key="rename-swabbing-time-to-timeout",
        min_version="0.14.1",
        max_version="0.15.0",
        apply=_rename_swabbing_time,
    ),
    UpgradeMigration(
        key="sync-built-in-gate-applicability",
        min_version="0.15.0",
        max_version="0.15.1",
        apply=_sync_built_in_gate_applicability,
    ),
    UpgradeMigration(
        key="stamp-config-version",
        min_version="0.15.1",
        max_version="0.15.2",
        apply=lambda root: stamp_config_version(root, "0.15.2"),
    ),
]


def _ordered_applicable_migrations(
    from_version: str, to_version: str
) -> Iterable[UpgradeMigration]:
    """Return applicable migrations in deterministic stepwise order."""
    current_version = Version(from_version)
    target_version = Version(to_version)
    applied: List[UpgradeMigration] = []

    for migration in sorted(_MIGRATIONS, key=lambda item: item.sort_key):
        migration_max = Version(migration.max_version)
        migration_min = Version(migration.min_version)
        if (
            current_version < migration_max <= target_version
            and current_version >= migration_min
        ):
            applied.append(migration)
            current_version = migration_max

    return applied


def planned_upgrade_migrations(from_version: str, to_version: str) -> List[str]:
    """Return the migration keys that would run for a version change."""
    return [m.key for m in _ordered_applicable_migrations(from_version, to_version)]


def run_upgrade_migrations(
    project_root: str | Path, from_version: str, to_version: str
) -> List[str]:
    """Run any built-in upgrade migrations and return the keys applied."""
    root = Path(project_root)
    applied: List[str] = []
    for migration in _ordered_applicable_migrations(from_version, to_version):
        migration.apply(root)
        applied.append(migration.key)
    return applied
