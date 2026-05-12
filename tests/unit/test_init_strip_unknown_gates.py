"""Unit tests for _strip_unknown_gates in the init command."""

from __future__ import annotations

from unittest.mock import Mock, patch

from slopmop.cli.init import _strip_unknown_gates


def _make_registry(gate_names: list[str]):
    """Return a mock registry whose list_checks() returns gate name strings."""
    registry = Mock()
    registry.list_checks.return_value = list(gate_names)
    return registry


class TestStripUnknownGates:
    def _patch_registry(self, gate_names: list[str]):
        registry = _make_registry(gate_names)
        return (
            patch("slopmop.checks.ensure_checks_registered"),
            patch("slopmop.core.registry.get_registry", return_value=registry),
        )

    def test_known_gates_are_kept(self):
        p1, p2 = self._patch_registry(["overconfidence:untested-code.py"])
        with p1, p2:
            config = {
                "overconfidence": {"gates": {"untested-code.py": {"enabled": True}}}
            }
            result = _strip_unknown_gates(config)
        assert "untested-code.py" in result["overconfidence"]["gates"]

    def test_unknown_gates_are_removed(self):
        p1, p2 = self._patch_registry([])
        with p1, p2:
            config = {"overconfidence": {"gates": {"py-tests": {"enabled": True}}}}
            result = _strip_unknown_gates(config)
        assert result["overconfidence"]["gates"] == {}

    def test_mix_of_known_and_unknown(self):
        p1, p2 = self._patch_registry(["overconfidence:untested-code.py"])
        with p1, p2:
            config = {
                "overconfidence": {
                    "gates": {
                        "untested-code.py": {"enabled": True},
                        "py-tests": {"enabled": False},
                    }
                }
            }
            result = _strip_unknown_gates(config)
        gates = result["overconfidence"]["gates"]
        assert "untested-code.py" in gates
        assert "py-tests" not in gates

    def test_non_gate_sections_are_preserved(self):
        p1, p2 = self._patch_registry([])
        with p1, p2:
            config = {
                "slopmop_version": "1.0.0",
                "custom_gates": [{"name": "foo"}],
                "overconfidence": {"gates": {}},
            }
            result = _strip_unknown_gates(config)
        assert result["slopmop_version"] == "1.0.0"
        assert result["custom_gates"] == [{"name": "foo"}]

    def test_section_without_gates_key_is_preserved(self):
        p1, p2 = self._patch_registry([])
        with p1, p2:
            config = {
                "overconfidence": {"description": "no gates here"},
            }
            result = _strip_unknown_gates(config)
        assert result["overconfidence"] == {"description": "no gates here"}

    def test_non_dict_gates_value_preserved_unchanged(self):
        p1, p2 = self._patch_registry([])
        with p1, p2:
            config = {
                "overconfidence": {"gates": "not-a-dict"},
            }
            result = _strip_unknown_gates(config)
        assert result["overconfidence"]["gates"] == "not-a-dict"

    def test_other_section_fields_are_preserved_alongside_filtered_gates(self):
        p1, p2 = self._patch_registry(["laziness:js-lint.js"])
        with p1, p2:
            config = {
                "laziness": {
                    "description": "laziness checks",
                    "gates": {
                        "js-lint.js": {"enabled": True},
                        "js-lint": {"enabled": True},
                    },
                }
            }
            result = _strip_unknown_gates(config)
        assert result["laziness"]["description"] == "laziness checks"
        assert "js-lint.js" in result["laziness"]["gates"]
        assert "js-lint" not in result["laziness"]["gates"]
