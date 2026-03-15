"""Generated docs for structured gate reasoning metadata."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, NamedTuple, Tuple

from slopmop.checks.base import GateCategory
from slopmop.checks.metadata import Reasoning
from slopmop.utils.readme_tables import CATEGORY_INFO, CATEGORY_ORDER

if TYPE_CHECKING:
    from slopmop.core.registry import CheckRegistry


class ReasoningRow(NamedTuple):
    full_name: str
    reasoning: Reasoning


def generate_reasoning_doc(registry: "CheckRegistry") -> str:
    """Generate the standalone gate-reasoning document."""
    gates: Dict[GateCategory, List[ReasoningRow]] = defaultdict(list)
    for _name, check_class in sorted(registry._check_classes.items()):
        instance = check_class({})
        reasoning = instance.reasoning
        if reasoning is None:
            continue
        gates[instance.category].append(
            ReasoningRow(full_name=instance.full_name, reasoning=reasoning)
        )

    for category in gates:
        gates[category].sort(key=lambda row: row.full_name)

    sections: List[str] = []
    sections.append("# Gate Reasoning")
    sections.append("")
    sections.append(
        "This file is generated from built-in gate metadata. Edit the gate reasoning "
        "source of truth in `slopmop/checks/metadata.py`, then regenerate it."
    )
    sections.append("")

    for category in CATEGORY_ORDER:
        rows = gates.get(category, [])
        if not rows:
            continue
        info = CATEGORY_INFO[category]
        sections.append(f"## {info.heading_emoji} {info.heading_color}")
        sections.append("")
        for row in rows:
            sections.append(f"### `{row.full_name}`")
            sections.append("")
            sections.append(f"- Rationale: {row.reasoning.rationale}")
            sections.append(f"- Tradeoffs: {row.reasoning.tradeoffs}")
            sections.append(f"- Override When: {row.reasoning.override_when}")
            sections.append("")

    return "\n".join(sections).rstrip() + "\n"


def check_reasoning_doc(
    doc_path: Path,
    registry: "CheckRegistry",
) -> Tuple[bool, str]:
    """Check whether the generated gate-reasoning doc is current."""
    generated = generate_reasoning_doc(registry)

    if not doc_path.exists():
        return False, (
            "Gate reasoning doc is missing. Run:\n"
            "  python scripts/generate_gate_reasoning.py --update"
        )

    if doc_path.read_text() == generated:
        return True, "Gate reasoning doc is up to date"

    return False, (
        "Gate reasoning doc is stale. Run:\n"
        "  python scripts/generate_gate_reasoning.py --update"
    )
