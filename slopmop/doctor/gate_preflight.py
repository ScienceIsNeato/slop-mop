"""Gate-oriented doctor helpers for pre-refit validation.

These helpers answer a narrower question than ``sm doctor --gates``:
"for this repo and its current config, which applicable gates are enabled,
disabled, or obviously blocked before we even attempt a refit?"

The public surface is intentionally reusable from both ``sm doctor`` and
``sm refit --start`` so the operator sees the same gate inventory in both
places.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple, cast

from slopmop.checks import ensure_checks_registered
from slopmop.checks.base import BaseCheck, find_tool
from slopmop.checks.custom import register_custom_gates
from slopmop.core.registry import get_registry


@dataclass(frozen=True)
class GatePreflightRecord:
    """Doctor-facing snapshot of one gate under the current repo config."""

    gate: str
    display_name: str
    enabled: bool
    applicable: bool
    skip_reason: str
    config_fingerprint: str
    missing_tools: Tuple[str, ...]

    @property
    def runnability_status(self) -> str:
        if not self.applicable:
            return "not_applicable"
        if not self.enabled:
            return "disabled"
        if self.missing_tools:
            return "blocked"
        return "runnable"


def _load_gate_preflight_config(project_root: Path) -> Dict[str, Any]:
    path = project_root / ".sb_config.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return cast(Dict[str, Any], raw) if isinstance(raw, dict) else {}


def _as_dict_or_empty(value: Any) -> Dict[str, Any]:
    return cast(Dict[str, Any], value) if isinstance(value, dict) else {}


def _gate_enabled(config: Dict[str, Any], gate_name: str) -> bool:
    disabled: list[Any] = config.get("disabled_gates", [])
    if isinstance(disabled, list) and gate_name in [
        v for v in disabled if isinstance(v, str)
    ]:
        return False
    if ":" not in gate_name:
        return True
    category, gate = gate_name.split(":", 1)
    category_cfg = _as_dict_or_empty(config.get(category))
    gates_cfg = _as_dict_or_empty(category_cfg.get("gates"))
    gate_cfg = _as_dict_or_empty(gates_cfg.get(gate))
    if "enabled" not in gate_cfg:
        return True
    return bool(gate_cfg.get("enabled"))


def _gate_config_fingerprint(config: Dict[str, Any], gate_name: str) -> str:
    payload: Dict[str, Any] = {
        "gate": gate_name,
        "enabled": _gate_enabled(config, gate_name),
    }
    if ":" in gate_name:
        category, gate = gate_name.split(":", 1)
        category_cfg = _as_dict_or_empty(config.get(category))
        gates_cfg = _as_dict_or_empty(category_cfg.get("gates"))
        gate_cfg = _as_dict_or_empty(gates_cfg.get(gate))
        payload["gate_config"] = gate_cfg
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _missing_required_tools(check: BaseCheck, project_root: Path) -> Tuple[str, ...]:
    missing: List[str] = []
    root = str(project_root)
    for tool in check.required_tools:
        if find_tool(tool, root) is None:
            missing.append(tool)
    return tuple(sorted(missing))


def gather_gate_preflight_records(
    project_root: str | Path,
) -> List[GatePreflightRecord]:
    """Return gate-preflight records for every applicable or enabled gate.

    Disabled-but-applicable gates are intentionally included. Refit needs to
    force an explicit decision for them rather than silently forgetting they
    exist.
    """

    root = Path(project_root)
    config = _load_gate_preflight_config(root)
    ensure_checks_registered()
    register_custom_gates(config)
    registry = get_registry()

    records: List[GatePreflightRecord] = []
    for gate_name_any in registry.list_checks():
        if not isinstance(gate_name_any, str):
            continue
        gate_name = gate_name_any
        check = registry.get_check(gate_name, config)
        if check is None:
            continue
        enabled = _gate_enabled(config, gate_name)
        applicable = check.is_applicable(str(root))
        if not applicable and not enabled:
            continue
        skip_reason = "" if applicable else check.skip_reason(str(root))
        records.append(
            GatePreflightRecord(
                gate=gate_name,
                display_name=check.display_name,
                enabled=enabled,
                applicable=applicable,
                skip_reason=skip_reason,
                config_fingerprint=_gate_config_fingerprint(config, gate_name),
                missing_tools=(
                    _missing_required_tools(check, root) if applicable else ()
                ),
            )
        )

    return sorted(records, key=lambda item: item.gate)


def summarize_gate_preflight(
    records: Sequence[GatePreflightRecord],
) -> Dict[str, object]:
    """Collapse preflight records into stable summary counts."""

    runnable = [r.gate for r in records if r.runnability_status == "runnable"]
    blocked = [r.gate for r in records if r.runnability_status == "blocked"]
    disabled = [r.gate for r in records if r.runnability_status == "disabled"]
    not_applicable = [
        r.gate for r in records if r.runnability_status == "not_applicable"
    ]
    return {
        "total": len(records),
        "runnable": runnable,
        "blocked": blocked,
        "disabled": disabled,
        "not_applicable": not_applicable,
    }
