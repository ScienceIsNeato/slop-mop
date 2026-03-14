"""README gate table generation utilities.

Generates Markdown tables from registered check class metadata.
Used by the ``scripts/generate_readme_tables.py`` CLI tool, which is
invoked by the ``stale-docs`` custom gate to verify table freshness.

The registry is accepted as a parameter to avoid circular imports —
this module does **not** call ``ensure_checks_registered()`` itself.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, NamedTuple, Tuple

from slopmop.checks.base import GateCategory

if TYPE_CHECKING:
    from slopmop.core.registry import CheckRegistry

# ── Markers (shared with scripts/generate_readme_tables.py) ──────────
BEGIN_MARKER = "<!-- BEGIN GATE TABLES -->"
END_MARKER = "<!-- END GATE TABLES -->"

# ── Category presentation order and descriptions ─────────────────────


class CategoryInfo(NamedTuple):
    heading_emoji: str
    heading_color: str
    quote: str


CATEGORY_INFO: Dict[GateCategory, CategoryInfo] = {
    GateCategory.OVERCONFIDENCE: CategoryInfo(
        heading_emoji="🔴",
        heading_color="Overconfidence",
        quote=(
            "*\"It compiles, therefore it's correct and will work "
            'perfectly in production"*\n\n'
            "The LLM generates code that looks right, passes a syntax check, "
            "and silently breaks at runtime. These gates verify that the code "
            "actually works."
        ),
    ),
    GateCategory.DECEPTIVENESS: CategoryInfo(
        heading_emoji="🟡",
        heading_color="Deceptiveness",
        quote=(
            '*"These tests are in the way of closing the ticket - '
            'how can I get around them?"*\n\n'
            "The LLM writes tests that assert nothing, mock everything, "
            "or cover the happy path and call it done. Coverage numbers "
            "look great. The code is still broken."
        ),
    ),
    GateCategory.LAZINESS: CategoryInfo(
        heading_emoji="🟠",
        heading_color="Laziness",
        quote=(
            '*"When I ran mypy, it returned errors unrelated to my '
            'code changes..."*\n\n'
            "The LLM solves the immediate problem and moves on. "
            "Formatting is inconsistent, dead code accumulates, complexity "
            "creeps upward, and nobody notices until the codebase is "
            "incomprehensible."
        ),
    ),
    GateCategory.MYOPIA: CategoryInfo(
        heading_emoji="🔵",
        heading_color="Myopia",
        quote=(
            "*\"This file is fine in isolation — I don't need to see "
            'what it duplicates three directories away"*\n\n'
            "The LLM has a 200k-token context window and still manages "
            "tunnel vision. It duplicates code across files, ignores "
            "security implications, and lets functions grow unbounded "
            "because it can't see the pattern."
        ),
    ),
}

CATEGORY_ORDER = [
    GateCategory.OVERCONFIDENCE,
    GateCategory.DECEPTIVENESS,
    GateCategory.LAZINESS,
    GateCategory.MYOPIA,
]


class GateRow(NamedTuple):
    full_name: str
    description: str
    why: str


class RemediationRow(NamedTuple):
    order: int
    full_name: str
    priority: int
    source: str
    churn: str


def generate_tables(registry: "CheckRegistry") -> str:
    """Generate the complete markdown for all gate tables.

    Args:
        registry: A fully-populated ``CheckRegistry`` instance.

    Returns:
        Markdown string with category headings, blockquotes, and tables.
    """
    # Discover and group gates by category
    gates: Dict[GateCategory, List[GateRow]] = defaultdict(list)
    for _name, check_class in sorted(registry._check_classes.items()):
        instance = check_class({})
        gates[instance.category].append(
            GateRow(
                full_name=instance.full_name,
                description=instance.gate_description,
                why=instance.why_it_matters or "",
            )
        )

    # Sort each category's gates alphabetically
    for cat in gates:
        gates[cat].sort(key=lambda row: row.full_name)

    # Build markdown sections
    sections: List[str] = []
    for cat in CATEGORY_ORDER:
        info = CATEGORY_INFO.get(cat)
        if info is None:
            continue

        rows = gates.get(cat, [])
        if not rows:
            continue

        # Section header
        sections.append(f"### {info.heading_emoji} {info.heading_color}")

        # Blockquote
        if info.quote:
            sections.append("")
            for line in info.quote.split("\n"):
                sections.append(f"> {line}" if line else ">")

        # Table
        sections.append("")
        sections.append("| Gate | What It Does | Why It Matters |")
        sections.append("|------|--------------|----------------|")
        for row in rows:
            sections.append(f"| `{row.full_name}` | {row.description} | {row.why} |")

        sections.append("")

    sections.extend(_generate_remediation_order_section(registry))

    return "\n".join(sections).rstrip() + "\n"


def _generate_remediation_order_section(registry: "CheckRegistry") -> List[str]:
    """Generate the remediation-order table from registry metadata."""
    checks = [check_class({}) for _name, check_class in registry._check_classes.items()]
    ordered_checks = registry.sort_checks_for_remediation(checks)
    rows: List[RemediationRow] = []
    for index, check in enumerate(ordered_checks, start=1):
        rows.append(
            RemediationRow(
                order=index,
                full_name=check.full_name,
                priority=registry.remediation_priority_for_check(check),
                source=registry.remediation_priority_source_for_check(check),
                churn=check.remediation_churn.name.replace("DOWNSTREAM_CHANGES_", "")
                .lower()
                .replace("_", "-"),
            )
        )

    sections: List[str] = []
    sections.append("### 🧭 Remediation Order")
    sections.append("")
    sections.append(
        "Execution order is not remediation order. In remediation mode, slop-mop "
        "validates finished gates using this registry-derived order to minimize "
        "overall remediation time. In maintenance mode, it evaluates results as "
        "soon as they come in to minimize dev-cycle time."
    )
    sections.append("")
    sections.append(
        "Reasoning: fix the dragons before polishing the armor. The order tries "
        "to clear dangerous or high-churn changes first, then repair deceptive "
        "tests, then rebuild confidence in correctness signals, and only then "
        "spend time on low-churn cleanup like formatting and artifacts."
    )
    sections.append("")
    sections.append(
        "`curated` means the registry intentionally pins that gate's place in the "
        "sequence. `explicit` means the gate class set its own numeric priority. "
        "`churn-default` means no exact order was provided, so slop-mop falls back "
        "to the broad churn band."
    )
    sections.append("")
    sections.append("| # | Gate | Priority | Source | Churn Band |")
    sections.append("|---|------|----------|--------|------------|")
    for row in rows:
        sections.append(
            f"| {row.order} | `{row.full_name}` | {row.priority} | {row.source} | {row.churn} |"
        )
    sections.append("")
    return sections


def splice_tables(readme_text: str, tables: str) -> str:
    """Replace content between markers with generated tables.

    Args:
        readme_text: Full README contents.
        tables: Generated markdown from :func:`generate_tables`.

    Returns:
        Updated README text with tables replaced.

    Raises:
        ValueError: If markers are missing from the README.
    """
    begin_idx = readme_text.find(BEGIN_MARKER)
    end_idx = readme_text.find(END_MARKER)

    if begin_idx == -1 or end_idx == -1:
        raise ValueError(
            f"README markers not found. Expected:\n" f"  {BEGIN_MARKER}\n  {END_MARKER}"
        )

    before = readme_text[: begin_idx + len(BEGIN_MARKER)]
    after = readme_text[end_idx:]  # includes END_MARKER

    return before + "\n\n" + tables + "\n" + after


def check_readme(readme_path: Path, registry: "CheckRegistry") -> Tuple[bool, str]:
    """Check whether the README gate tables match the source of truth.

    Args:
        readme_path: Path to README.md.
        registry: Fully-populated ``CheckRegistry``.

    Returns:
        ``(True, message)`` if up to date, ``(False, message)`` if stale.
    """
    if not readme_path.exists():
        return True, "No README.md found — nothing to check"

    readme_text = readme_path.read_text()

    if BEGIN_MARKER not in readme_text or END_MARKER not in readme_text:
        return True, "No gate table markers in README — nothing to check"

    tables = generate_tables(registry)
    new_readme = splice_tables(readme_text, tables)

    if readme_text == new_readme:
        return True, "README gate tables are up to date"

    return (
        False,
        "README gate tables are stale. Run:\n"
        "  python scripts/generate_readme_tables.py --update",
    )
