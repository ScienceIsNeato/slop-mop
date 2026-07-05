"""Canonical gate naming and gate-enablement semantics.

Two things every layer of slop-mop needs and, historically, each re-derived
for itself (tech-debt audit #4):

- **``GateRef``** — the one parser for the stringly-typed ``category:gate``
  format. Before this module, ``split(":", 1)`` appeared at 25+ call sites;
  any change to the naming scheme meant hunting all of them.
- **``gate_enablement()``** — the one answer to "is this gate enabled in
  this raw config dict?". Before this module there were three raw-dict
  implementations (executor, doctor preflight, cli config) with *divergent*
  semantics: only the executor honored a category-level ``enabled: false``,
  so doctor/preflight reported gates enabled that the executor would skip.

The semantics here are the executor's — the implementation that decides
what actually runs — and every other caller now delegates:

1. ``disabled_gates`` list membership disables (``sm config --disable``).
2. Category-level ``{"<category>": {"enabled": false}}`` disables the
   whole category.
3. Gate-level ``{"<category>": {"gates": {"<gate>": {"enabled": false}}}}``
   disables the gate. Only an explicit ``false`` disables — an absent or
   null ``enabled`` leaves the gate on.
4. Everything else is enabled.

This module is deliberately dependency-free (stdlib only) so any layer can
import it without joining slop-mop's deferred-import circularity dance.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any, cast


@dataclass(frozen=True)
class GateRef:
    """A parsed ``category:gate`` gate name.

    ``parse`` accepts both qualified (``"myopia:dependency-risk.py"``) and
    bare (``"dependency-risk.py"``) names; bare names round-trip with an
    empty category and ``is_qualified`` False.
    """

    category: str
    gate: str

    @classmethod
    def parse(cls, name: str) -> GateRef:
        category, sep, gate = name.partition(":")
        if not sep:
            return cls(category="", gate=name)
        return cls(category=category, gate=gate)

    @property
    def is_qualified(self) -> bool:
        return bool(self.category)

    @property
    def full_name(self) -> str:
        if not self.category:
            return self.gate
        return f"{self.category}:{self.gate}"


def _mapping_or_empty(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def gate_enablement(config: Mapping[str, Any], full_name: str) -> tuple[bool, str]:
    """Return ``(enabled, reason_if_disabled)`` for a gate in a raw config.

    ``reason`` is ``""`` when the gate is enabled. See the module docstring
    for the precedence rules; the reason strings match what the executor has
    always reported so skip explanations stay stable.
    """
    disabled_val: object = config.get("disabled_gates", [])
    if isinstance(disabled_val, list) and full_name in cast(list[object], disabled_val):
        return False, f"{full_name} is in disabled_gates list"

    ref = GateRef.parse(full_name)
    if not ref.is_qualified:
        return True, ""

    category_cfg = _mapping_or_empty(config.get(ref.category))
    if category_cfg.get("enabled") is False:
        return False, f"{ref.category} language is disabled in config"

    gate_cfg = _mapping_or_empty(
        _mapping_or_empty(category_cfg.get("gates")).get(ref.gate)
    )
    if gate_cfg.get("enabled") is False:
        return False, f"{full_name} is disabled in config"

    return True, ""


def is_gate_enabled(config: Mapping[str, Any], full_name: str) -> bool:
    """Boolean convenience wrapper over :func:`gate_enablement`."""
    enabled, _reason = gate_enablement(config, full_name)
    return enabled
