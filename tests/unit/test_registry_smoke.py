"""Real-registry smoke tests — no mocks, the actual registration path.

The refit/executor unit suites exercise their logic against ``_FakeRegistry``
stand-ins, which means a regression in real gate registration, instantiation,
or remediation-priority resolution would sail through them. These tests run
the genuine ``ensure_checks_registered`` + ``CheckRegistry`` end to end so
that class of break is caught in the unit tier (tech-debt audit finding #9).
"""

from __future__ import annotations

from slopmop.checks import ensure_checks_registered
from slopmop.checks.base import BaseCheck
from slopmop.core.registry import curated_remediation_order_names, get_registry


def _registry():
    ensure_checks_registered()
    return get_registry()


class TestRealRegistrySmoke:
    def test_all_gates_register_and_instantiate(self):
        registry = _registry()
        names = registry.list_checks()
        # A registration regression usually shows up as a silently shorter
        # list, not an exception — anchor a floor well below the real count
        # (38 at time of writing) but far above any partial-import failure.
        assert len(names) >= 30

        for name in names:
            check = registry.get_check(name, {})
            assert isinstance(check, BaseCheck), f"{name} failed to instantiate"
            assert check.full_name == name
            # The stringly-typed contract every consumer split()s on.
            category, _, gate = name.partition(":")
            assert category and gate, f"malformed gate name: {name!r}"

    def test_remediation_priorities_resolve_for_every_gate(self):
        registry = _registry()
        checks = [registry.get_check(name, {}) for name in registry.list_checks()]
        instantiated = [c for c in checks if c is not None]
        assert instantiated

        for check in instantiated:
            priority = registry.remediation_priority_for_check(check)
            assert isinstance(priority, int)
            source = registry.remediation_priority_source_for_check(check)
            assert isinstance(source, str) and source

    def test_remediation_sort_is_total_and_stable(self):
        registry = _registry()
        checks = [registry.get_check(name, {}) for name in registry.list_checks()]
        instantiated = [c for c in checks if c is not None]

        ordered = registry.sort_checks_for_remediation(instantiated)
        # Total: nothing dropped or duplicated by sorting.
        assert sorted(c.full_name for c in ordered) == sorted(
            c.full_name for c in instantiated
        )
        # Stable/deterministic: sorting twice yields the same order.
        again = registry.sort_checks_for_remediation(instantiated)
        assert [c.full_name for c in ordered] == [c.full_name for c in again]

    def test_curated_remediation_order_names_are_real_gates(self):
        # The curated ordering is maintained by hand — every entry must still
        # correspond to a registered gate, or the priority table silently
        # stops applying to the gate it meant to rank.
        registry = _registry()
        registered = set(registry.list_checks())
        for name in curated_remediation_order_names():
            assert name in registered, f"curated order references unknown gate {name!r}"
