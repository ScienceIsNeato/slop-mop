"""Help command for slop-mop CLI."""

import argparse
from typing import List

from slopmop.checks import ensure_checks_registered
from slopmop.core.registry import get_registry


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
        print("   Run 'sm help' to see all available gates")
        return 1

    # Get the check class for more details
    check = registry.get_check(gate_name, {})
    if not check:
        print(f"❌ Could not instantiate: {gate_name}")
        return 1

    print(f"\n🔍 Quality Gate: {definition.name}")
    print("=" * 60)
    print(f"Flag: --quality-gates {definition.flag}")
    print(f"Auto-fix: {'Yes' if definition.auto_fix else 'No'}")
    if definition.depends_on:
        print(f"Depends on: {', '.join(definition.depends_on)}")
    print()
    print("Description:")
    print(f"  {check.__doc__ or 'No description available.'}")
    print()
    print("When to use:")
    print("  Run as part of 'commit' or 'pr' profiles, or individually")
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

    print("\n🧹 Slop-Mop Quality Gates")
    print("=" * 60)
    print()

    # Group by category
    python_gates = []
    js_gates = []
    general_gates = []

    for name in sorted(registry.list_checks()):
        if name.startswith("python-"):
            python_gates.append(name)
        elif name.startswith("js-") or name == "frontend-check":
            js_gates.append(name)
        else:
            general_gates.append(name)

    _print_gate_group("🐍 Python", python_gates)
    _print_gate_group("📜 JavaScript", js_gates)
    _print_gate_group("📋 General", general_gates)

    print("📦 Profiles:")
    for alias, gates in sorted(registry.list_aliases().items()):
        print(f"    {alias:<30} {len(gates)} gates")

    print()
    print("Legend: 🔧 = supports auto-fix")
    print()
    print("For detailed help on a gate: sm help <gate-name>")
    print()
    return 0


def cmd_help(args: argparse.Namespace) -> int:
    """Handle the help command."""
    ensure_checks_registered()

    if args.gate:
        return _show_gate_help(args.gate)

    return _show_all_gates()
