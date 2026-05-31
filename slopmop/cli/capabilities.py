"""`sm capabilities` — the discovery catalog.

One read teaches an agent the entire surface: the installed slop-mop
version, every verb with its output contract (group, accepted formats,
exit-code meanings, and the ``$id`` of its packaged data schema when it
has one), and every registered gate with its metadata and applicability
to *this* project.

Like ``sm schema``, this is self-description without execution — it runs
no gates. The payload itself rides the standard envelope, so an agent
that has read ``sm schema capabilities`` already knows this command's
exact shape before running it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional

from slopmop import __version__
from slopmop.reporting.envelope import (
    ENVELOPE_SCHEMA_VERSION,
    Status,
    available_data_schemas,
    build_envelope,
)

# Curated verb catalog. Order mirrors the workflow an agent walks, not
# the parser registration order. ``data_schema`` is resolved at runtime
# from the packaged schemas so this list never claims a contract that
# isn't shipped — see _verb_entries().
#
# Drift guards (tests/unit/test_capabilities.py): the verb *set* is
# pinned to the parser (test_catalog_lists_every_registered_verb),
# ``group`` to an enum, and ``formats`` to each verb's actual argparse
# output flags (test_catalog_formats_track_argparse_output_flags).
# ``summary`` and ``exit_codes`` are editorial with no second source, so
# this literal is their truth; exit_codes shape is structurally checked.
_VERB_CATALOG: List[Dict[str, object]] = [
    {
        "name": "swab",
        "summary": "Quick validation — runs every swab-level gate (every commit).",
        "group": "core",
        "formats": ["human", "json", "porcelain", "sarif"],
        "exit_codes": {
            "0": "all gates passed",
            "1": "one or more gates failed",
            "2": "could not run (bad args, missing dependency)",
        },
    },
    {
        "name": "scour",
        "summary": "Thorough validation — runs all gates (PR readiness, superset of swab).",
        "group": "core",
        "formats": ["human", "json", "porcelain", "sarif"],
        "exit_codes": {
            "0": "all gates passed",
            "1": "one or more gates failed",
            "2": "could not run (bad args, missing dependency)",
        },
    },
    {
        "name": "sail",
        "summary": "Auto-advance the workflow — read state and do the next obvious step.",
        "group": "workflow",
        "formats": ["human", "json"],
        "exit_codes": {
            "0": "step completed",
            "1": "step ran but found blocking problems",
            "2": "could not determine or run the next step",
        },
    },
    {
        "name": "buff",
        "summary": "Post-PR CI triage and next-step guidance.",
        "group": "workflow",
        "formats": ["human", "json"],
        "exit_codes": {
            "0": "CI green / nothing to do",
            "1": "CI failures need attention",
            "2": "could not query CI (no PR, gh missing)",
        },
    },
    {
        "name": "refit",
        "summary": "Structured remediation — plan and continue repository onboarding.",
        "group": "workflow",
        "formats": ["human", "json"],
        "exit_codes": {
            "0": "phase advanced / plan emitted",
            "1": "remediation work remains",
            "2": "could not run",
        },
    },
    {
        "name": "barnacle",
        "summary": "File upstream tool-friction issues against slop-mop.",
        "group": "feedback",
        "formats": ["human", "json"],
        "exit_codes": {
            "0": "filed (or dry-run preview)",
            "2": "could not file",
        },
    },
    {
        "name": "wake-angry-drunk-captain",
        "summary": "Escalate to the human — last resort when no verb can progress.",
        "group": "escalation",
        "formats": ["human", "json"],
        "exit_codes": {
            "1": "summons answered — orders received, loop paused",
            "2": "justification insufficient — standing order read back",
            "3": "no human at an interactive terminal — re-run where one can answer",
        },
    },
    {
        "name": "status",
        "summary": "Project dashboard — config, gate inventory, hooks. Runs no gates.",
        "group": "introspection",
        "formats": ["human", "json"],
        "exit_codes": {
            "0": "dashboard emitted",
            "1": "project root not found",
        },
    },
    {
        "name": "doctor",
        "summary": "Diagnose environment health; --fix repairs slop-mop-owned state.",
        "group": "introspection",
        "formats": ["human", "json"],
        "exit_codes": {
            "0": "no problems found",
            "1": "problems detected",
        },
    },
    {
        "name": "audit",
        "summary": "Read-only codebase health snapshot (git analytics + gate inventory).",
        "group": "introspection",
        "formats": ["human", "json"],
        "exit_codes": {
            "0": "report emitted",
            "1": "could not run (sm init required)",
        },
    },
    {
        "name": "schema",
        "summary": "Print the response-envelope JSON Schema, or a verb's full output schema.",
        "group": "introspection",
        "formats": ["json"],
        "exit_codes": {
            "0": "schema emitted",
            "1": "unknown verb requested",
        },
    },
    {
        "name": "capabilities",
        "summary": "This catalog — version, every verb's contract, every gate's metadata.",
        "group": "introspection",
        "formats": ["json"],
        "exit_codes": {
            "0": "catalog emitted",
        },
    },
    {
        "name": "config",
        "summary": "View or update quality-gate configuration.",
        "group": "config",
        "formats": ["human"],
        "exit_codes": {
            "0": "config shown / updated",
            "2": "invalid config command",
        },
    },
    {
        "name": "init",
        "summary": "Auto-detect project type and write initial configuration.",
        "group": "setup",
        "formats": ["human"],
        "exit_codes": {
            "0": "configured",
            "1": "setup failed",
        },
    },
    {
        "name": "upgrade",
        "summary": "Upgrade the installed slop-mop package and validate the result.",
        "group": "setup",
        "formats": ["human"],
        "exit_codes": {
            "0": "upgraded (or plan shown with --check)",
            "1": "upgrade or post-upgrade validation failed",
        },
    },
    {
        "name": "agent",
        "summary": "Install agent-integration templates.",
        "group": "setup",
        "formats": ["human"],
        "exit_codes": {
            "0": "installed",
            "1": "install failed",
        },
    },
    {
        "name": "commit-hooks",
        "summary": "Install, uninstall, or inspect sm-managed git hooks.",
        "group": "setup",
        "formats": ["human"],
        "exit_codes": {
            "0": "action completed",
            "1": "action failed",
        },
    },
    {
        "name": "gang",
        "summary": "Press-gang forbidden shell commands into the correct sm rail.",
        "group": "setup",
        "formats": ["human"],
        "exit_codes": {
            "0": "action completed",
            "1": "action failed",
        },
    },
    {
        "name": "help",
        "summary": "Show detailed help for quality gates.",
        "group": "introspection",
        "formats": ["human"],
        "exit_codes": {
            "0": "help emitted",
        },
    },
]


def _verb_data_schema_id(verb: str, declared: set[str]) -> Optional[str]:
    """Return the ``$id`` of a verb's packaged data schema, or None.

    None means the verb has not been migrated onto the envelope yet, so
    its ``data`` shape isn't guaranteed. Computed from what actually
    ships (``declared``) so the catalog can't advertise a missing schema.
    """
    if verb in declared:
        return f"https://slopmop.dev/schemas/v3/data/{verb}.json"
    return None


def _verb_entries() -> List[Dict[str, object]]:
    """Materialise the verb catalog with resolved data-schema references."""
    declared = set(available_data_schemas())
    entries: List[Dict[str, object]] = []
    for verb in _VERB_CATALOG:
        entry = dict(verb)
        name = entry["name"]
        assert isinstance(name, str)
        entry["data_schema"] = _verb_data_schema_id(name, declared)
        entries.append(entry)
    return entries


def _gate_entries(project_root: Path) -> List[Dict[str, object]]:
    """Enumerate every registered gate with metadata and applicability.

    Mirrors ``sm status``: instantiate each check once to read its
    metadata and probe ``is_applicable`` against this project. Runs no
    gates.
    """
    from slopmop.checks import ensure_checks_registered
    from slopmop.checks.custom import register_custom_gates
    from slopmop.core.registry import get_registry
    from slopmop.sm import load_config

    ensure_checks_registered()
    config = load_config(project_root)
    register_custom_gates(config)
    registry = get_registry()

    entries: List[Dict[str, object]] = []
    for gate_name in registry.list_checks():
        check = registry.get_check(gate_name, config)
        if check is None:
            continue
        is_applicable = check.is_applicable(str(project_root))
        entry: Dict[str, object] = {
            "name": check.full_name,
            "category": check.category.key,
            "category_label": check.category.display_name,
            "emoji": check.category.emoji,
            "level": check.effective_level.value,
            "role": check.role.value,
            "description": check.gate_description,
            "why_it_matters": check.why_it_matters,
            "applicable": is_applicable,
        }
        if not is_applicable:
            entry["skip_reason"] = check.skip_reason(str(project_root))
        entries.append(entry)

    entries.sort(key=lambda e: str(e["name"]))
    return entries


def cmd_capabilities(args: argparse.Namespace) -> int:
    """Emit the discovery catalog as a pretty-printed envelope."""
    project_root = Path(getattr(args, "project_root", ".")).resolve()

    data: Dict[str, object] = {
        "version": __version__,
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "verbs": _verb_entries(),
        "gates": _gate_entries(project_root),
    }

    envelope = build_envelope(
        command="capabilities",
        status=Status.INFO,
        exit_code=0,
        data=data,
    )
    # Pretty-printed: this is a discovery surface a human also reads.
    print(json.dumps(envelope, indent=2))
    return 0
