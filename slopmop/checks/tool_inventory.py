"""Registry-derived external-tool inventory.

Single source of truth for "what external tools do slop-mop's gates need, and
how does a user install them" — derived from each gate's ``requirements()``
instead of a hand-maintained list. Replaces the former hardcoded
``REQUIRED_TOOLS`` in ``slopmop.cli.detection``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from slopmop.checks.base import Requirements


def gate_tool_inventory(
    config: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, str, str]]:
    """Return ``(tool_name, gate_name, install_hint)`` for every declared tool.

    Walks every registered gate's ``requirements()`` and emits one row per
    ``(tool, gate)``. ``install_hint`` is the user-facing remediation command
    (``pipx install slopmop[security]``, an SDK URL, …). Sorted for stable
    output. Only ``system``/``python``/``npm`` tools are listed — ``env``
    requirements aren't "installable tools".

    ``requirements()`` is config-dependent (configured scanners, run_actionlint
    …), so pass the repo's resolved config to report exactly what THIS repo's
    gates need; the default (``{}``) reports the full default tool set.
    """
    from slopmop.checks import ensure_checks_registered
    from slopmop.core.registry import get_registry

    config = config or {}
    ensure_checks_registered()
    registry = get_registry()

    rows: List[Tuple[str, str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for gate_name in registry.list_checks():
        if not isinstance(gate_name, str):
            continue
        check = registry.get_check(gate_name, config)
        if check is None:
            continue
        for req in check.requirements().items:
            if req.kind == "env":
                continue
            key = (req.name, gate_name)
            if key in seen:
                continue
            seen.add(key)
            rows.append((req.name, gate_name, req.resolved_install_hint()))
    return sorted(rows)


def aggregate_requirements(config: Optional[Dict[str, Any]] = None) -> "Requirements":
    """Union of every gate's requirements(), deduped by tool name.

    This is what ``sm doctor --required-deps`` serializes into the manifest the
    GitHub Action installs from: one entry per distinct tool, carrying its kind
    (install channel), exact pin, and probe. Config-dependent like the
    inventory — pass the repo config to reflect only the tools THIS repo's gates
    need. Deterministic: the Requirements manifest sorts by (kind, name).
    """
    from slopmop.checks import ensure_checks_registered
    from slopmop.checks.base import Requirements
    from slopmop.core.registry import get_registry

    config = config or {}
    ensure_checks_registered()
    registry = get_registry()

    by_name: Dict[str, Any] = {}
    for gate_name in registry.list_checks():
        if not isinstance(gate_name, str):
            continue
        check = registry.get_check(gate_name, config)
        if check is None:
            continue
        for req in check.requirements().items:
            # Dedup by tool name — a tool has one pin/kind regardless of how
            # many gates use it. Identical re-declarations collapse, but a
            # genuine DISAGREEMENT (different kind/version/probe/import_name)
            # is a bug: the manifest would otherwise silently install whichever
            # gate happened to register first. Fail loudly instead.
            existing = by_name.get(req.name)
            if existing is None:
                by_name[req.name] = req
                continue
            existing_id = (
                existing.kind,
                existing.version,
                existing.probe,
                existing.import_name,
            )
            incoming_id = (req.kind, req.version, req.probe, req.import_name)
            if existing_id != incoming_id:
                raise ValueError(
                    f"Conflicting requirements for tool {req.name!r}: "
                    f"{existing_id} vs {incoming_id}. Two gates declare the "
                    "same tool with different kind/version/probe — reconcile "
                    "them so the dependency manifest is unambiguous."
                )
    return Requirements(items=tuple(by_name.values()))
