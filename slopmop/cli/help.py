"""Help command for slop-mop CLI."""

import argparse
import textwrap
from typing import Dict, List

from slopmop.checks import ensure_checks_registered
from slopmop.checks.base import GateCategory
from slopmop.core.registry import get_registry


def _format_docstring(doc: str) -> str:
    """Clean and format a class docstring for terminal display.

    Strips leading/trailing whitespace, dedents, and adds consistent
    indentation so the help output looks clean regardless of how the
    docstring was indented in source.
    """
    cleaned = textwrap.dedent(doc).strip()
    lines = cleaned.splitlines()
    formatted: List[str] = []
    for line in lines:
        if line.strip():
            formatted.append(f"  {line}")
        else:
            formatted.append("")
    return "\n".join(formatted)


def _show_gate_help(gate_name: str) -> int:
    """Show help for a specific gate."""
    registry = get_registry()

    definition = registry.get_definition(gate_name)
    if not definition:
        # Check if it's an alias
        if registry.is_alias(gate_name):
            print(f"\n📦 Profile: {gate_name}")
            print("=" * 60)
            print(f"Expands to: {', '.join(registry.expand_alias(gate_name))}")
            print()
            return 0
        print(f"❌ Unknown quality gate: {gate_name}")
        print("   Run './sm help' to see all available gates")
        return 1

    # Get the check class for more details
    check = registry.get_check(gate_name, {})
    if not check:
        print(f"❌ Could not instantiate: {gate_name}")
        return 1

    print(f"\n🔍 Quality Gate: {definition.name}")
    print("=" * 60)
    print(f"  Flag:     {definition.flag}")
    print(f"  Auto-fix: {'Yes' if definition.auto_fix else 'No'}")
    if definition.depends_on:
        print(f"  Depends:  {', '.join(definition.depends_on)}")
    print()

    doc = check.__doc__ or "No description available."
    print(_format_docstring(doc))
    print()
    return 0


def _print_gate_group(title: str, gates: List[str]) -> None:
    """Print a group of gates with formatting."""
    if not gates:
        return

    registry = get_registry()

    print(f"  {title}:")
    for name in gates:
        definition = registry.get_definition(name)
        display = definition.name if definition else name
        auto_fix = "🔧" if definition and definition.auto_fix else "  "
        print(f"    {auto_fix} {name:<30} {display}")
    print()


def _show_all_gates() -> int:
    """Show help for all gates."""
    registry = get_registry()

    print("\n🪣 Slop-Mop Quality Gates")
    print("=" * 60)
    print()

    # Group by flaw category using the check's category property
    gates_by_category: Dict[GateCategory, List[str]] = {cat: [] for cat in GateCategory}

    for name in sorted(registry.list_checks()):
        check = registry.get_check(name, {})
        if check:
            gates_by_category[check.category].append(name)
        else:
            # Fallback: parse category from gate name prefix (e.g. "laziness:py-lint")
            cat_key = name.split(":")[0] if ":" in name else "general"
            cat = GateCategory.from_key(cat_key)
            if cat:
                gates_by_category[cat].append(name)

    for category in GateCategory:
        gates = gates_by_category.get(category, [])
        _print_gate_group(f"{category.emoji} {category.display_name}", gates)

    print("📦 Profiles:")
    for alias, gates in sorted(registry.list_aliases().items()):
        print(f"    {alias:<30} {len(gates)} gates")

    print()
    print("Legend: 🔧 = supports auto-fix")
    print()
    print("For detailed help on a gate: ./sm help <gate-name>")
    print()
    return 0


def cmd_help(args: argparse.Namespace) -> int:
    """Handle the help command."""
    ensure_checks_registered()

    if args.gate:
        return _show_gate_help(args.gate)

    return _show_all_gates()
