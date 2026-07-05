"""Tests for the canonical gate naming + enablement module.

``gate_config`` exists to end the era of five divergent "is this gate
enabled" implementations and 25+ ad-hoc ``split(":", 1)`` sites (tech-debt
audit #4). These tests pin the canonical semantics, guard against a rival
enablement API reappearing on the structured config classes (the old one
had zero consumers and opposite defaults, so it was deleted, not
reconciled), and cover the divergence the unification fixed:
category-level disables that preflight/cli previously ignored.
"""

from __future__ import annotations

from slopmop.core.config import SlopmopConfig
from slopmop.core.gate_config import GateRef, gate_enablement, is_gate_enabled


class TestGateRef:
    def test_qualified_roundtrip(self):
        ref = GateRef.parse("myopia:dependency-risk.py")
        assert ref.category == "myopia"
        assert ref.gate == "dependency-risk.py"
        assert ref.is_qualified
        assert ref.full_name == "myopia:dependency-risk.py"

    def test_bare_name_roundtrip(self):
        ref = GateRef.parse("dependency-risk.py")
        assert ref.category == ""
        assert ref.gate == "dependency-risk.py"
        assert not ref.is_qualified
        assert ref.full_name == "dependency-risk.py"

    def test_only_first_colon_splits(self):
        # Gate names may themselves contain colons someday; the category is
        # everything before the FIRST colon, matching split(":", 1).
        ref = GateRef.parse("a:b:c")
        assert (ref.category, ref.gate) == ("a", "b:c")
        assert ref.full_name == "a:b:c"


class TestGateEnablement:
    def test_default_is_enabled(self):
        assert gate_enablement({}, "myopia:g") == (True, "")

    def test_disabled_gates_list(self):
        enabled, reason = gate_enablement({"disabled_gates": ["myopia:g"]}, "myopia:g")
        assert enabled is False
        assert "disabled_gates" in reason

    def test_category_level_disable(self):
        # The divergence the unification fixed: preflight/cli ignored this
        # while the executor honored it.
        enabled, reason = gate_enablement({"myopia": {"enabled": False}}, "myopia:g")
        assert enabled is False
        assert "myopia" in reason

    def test_gate_level_disable(self):
        cfg = {"myopia": {"gates": {"g": {"enabled": False}}}}
        enabled, reason = gate_enablement(cfg, "myopia:g")
        assert enabled is False
        assert "myopia:g" in reason

    def test_only_explicit_false_disables(self):
        # Executor semantics: absent or null "enabled" leaves the gate on.
        assert is_gate_enabled({"myopia": {"gates": {"g": {}}}}, "myopia:g")
        assert is_gate_enabled(
            {"myopia": {"gates": {"g": {"enabled": None}}}}, "myopia:g"
        )

    def test_bare_names_are_always_enabled(self):
        assert is_gate_enabled({"disabled_gates": []}, "custom-gate")

    def test_malformed_config_shapes_are_safe(self):
        # Wrong types anywhere in the walk must not raise.
        assert is_gate_enabled({"disabled_gates": "not-a-list"}, "a:b")
        assert is_gate_enabled({"a": "not-a-dict"}, "a:b")
        assert is_gate_enabled({"a": {"gates": "not-a-dict"}}, "a:b")
        assert is_gate_enabled({"a": {"gates": {"b": "not-a-dict"}}}, "a:b")


class TestCanonicalIsTheOnlyImplementation:
    """The structured config classes must NOT grow a rival enablement API.

    ``SlopmopConfig.is_gate_enabled``/``CategoryConfig.is_gate_enabled`` were
    deleted during the unification: they had zero production consumers and
    silently used the OPPOSITE default (enabled=False) from the executor. If
    someone reintroduces an enablement method on the structured classes, this
    test forces the conversation back to the canonical module.
    """

    def test_structured_classes_have_no_enablement_api(self):
        from slopmop.core.config import CategoryConfig

        assert not hasattr(SlopmopConfig, "is_gate_enabled")
        assert not hasattr(CategoryConfig, "is_gate_enabled")


class TestPreflightUsesCanonicalSemantics:
    def test_category_disable_reaches_preflight(self):
        # Regression: _gate_enabled previously ignored category-level
        # disables, so doctor/refit readiness disagreed with the executor.
        from slopmop.doctor.gate_preflight import _gate_enabled

        assert _gate_enabled({"myopia": {"enabled": False}}, "myopia:g") is False

    def test_category_disable_reaches_cli_config(self):
        from slopmop.cli.config import _is_gate_enabled

        assert _is_gate_enabled({"myopia": {"enabled": False}}, "myopia:g") is False
