"""Comprehensive tests for custom gate parsing and registration.

Custom gates accept user-defined JSON configuration, making thorough
input validation testing essential.  This module covers:

- ``_resolve_category`` — category key → GateCategory mapping
- ``_resolve_level`` — level key → GateLevel mapping
- ``make_custom_check_class`` — dynamic BaseCheck subclass construction
- ``register_custom_gates`` — full config parsing and registry integration

Edge cases: missing fields, wrong types, empty strings, invalid values,
very large inputs, special characters, and more.
"""

import logging
from typing import Any, Dict
from unittest.mock import patch

import pytest

from slopmop.checks.base import BaseCheck, GateCategory, GateLevel
from slopmop.checks.custom import (
    DEFAULT_CUSTOM_TIMEOUT,
    _resolve_category,
    _resolve_level,
    make_custom_check_class,
    register_custom_gates,
)
from slopmop.core.result import CheckStatus

# ── _resolve_category ────────────────────────────────────────────────


class TestResolveCategory:
    """Tests for _resolve_category() — maps key strings to GateCategory."""

    def test_valid_overconfidence(self) -> None:
        assert _resolve_category("overconfidence") == GateCategory.OVERCONFIDENCE

    def test_valid_deceptiveness(self) -> None:
        assert _resolve_category("deceptiveness") == GateCategory.DECEPTIVENESS

    def test_valid_laziness(self) -> None:
        assert _resolve_category("laziness") == GateCategory.LAZINESS

    def test_valid_myopia(self) -> None:
        assert _resolve_category("myopia") == GateCategory.MYOPIA

    def test_valid_general(self) -> None:
        assert _resolve_category("general") == GateCategory.GENERAL

    def test_unknown_key_defaults_to_general(self) -> None:
        assert _resolve_category("invalid") == GateCategory.GENERAL

    def test_empty_string_defaults_to_general(self) -> None:
        assert _resolve_category("") == GateCategory.GENERAL

    def test_case_sensitive_rejects_uppercase(self) -> None:
        """Category keys are case-sensitive — 'Laziness' is not 'laziness'."""
        assert _resolve_category("Laziness") == GateCategory.GENERAL

    def test_case_sensitive_rejects_mixed_case(self) -> None:
        assert _resolve_category("MyOpia") == GateCategory.GENERAL

    def test_whitespace_not_stripped(self) -> None:
        assert _resolve_category(" laziness ") == GateCategory.GENERAL

    def test_unknown_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            _resolve_category("bogus")
        assert "Unknown custom gate category" in caplog.text
        assert "'bogus'" in caplog.text

    def test_valid_key_does_not_log_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            _resolve_category("laziness")
        assert caplog.text == ""

    def test_removed_pr_category_defaults_to_general(self) -> None:
        """The 'pr' category was removed — should fall back to general."""
        assert _resolve_category("pr") == GateCategory.GENERAL


# ── _resolve_level ───────────────────────────────────────────────────


class TestResolveLevel:
    """Tests for _resolve_level() — maps key strings to GateLevel."""

    def test_swab(self) -> None:
        assert _resolve_level("swab") == GateLevel.SWAB

    def test_scour(self) -> None:
        assert _resolve_level("scour") == GateLevel.SCOUR

    def test_swab_uppercase(self) -> None:
        """Level resolution is case-insensitive."""
        assert _resolve_level("SWAB") == GateLevel.SWAB

    def test_scour_mixed_case(self) -> None:
        assert _resolve_level("Scour") == GateLevel.SCOUR

    def test_unknown_defaults_to_swab(self) -> None:
        assert _resolve_level("deep") == GateLevel.SWAB

    def test_empty_string_defaults_to_swab(self) -> None:
        assert _resolve_level("") == GateLevel.SWAB


# ── make_custom_check_class ──────────────────────────────────────────


class TestMakeCustomCheckClass:
    """Tests for make_custom_check_class() — dynamic BaseCheck factory."""

    def test_returns_basecheck_subclass(self) -> None:
        cls = make_custom_check_class(
            gate_name="my-gate",
            description="My gate",
            category_key="laziness",
            command="echo ok",
        )
        assert issubclass(cls, BaseCheck)

    def test_instance_name(self) -> None:
        cls = make_custom_check_class(
            gate_name="my-gate",
            description="My gate",
            category_key="laziness",
            command="echo ok",
        )
        inst = cls({})
        assert inst.name == "my-gate"

    def test_instance_display_name(self) -> None:
        cls = make_custom_check_class(
            gate_name="my-gate",
            description="Check for bad things",
            category_key="laziness",
            command="echo ok",
        )
        inst = cls({})
        assert inst.display_name == "🔧 Check for bad things"

    def test_instance_category(self) -> None:
        cls = make_custom_check_class(
            gate_name="my-gate",
            description="desc",
            category_key="deceptiveness",
            command="echo ok",
        )
        inst = cls({})
        assert inst.category == GateCategory.DECEPTIVENESS

    def test_instance_full_name(self) -> None:
        cls = make_custom_check_class(
            gate_name="my-gate",
            description="desc",
            category_key="laziness",
            command="echo ok",
        )
        inst = cls({})
        assert inst.full_name == "laziness:my-gate"

    def test_unknown_category_falls_to_general(self) -> None:
        cls = make_custom_check_class(
            gate_name="x",
            description="d",
            category_key="nonsense",
            command="echo ok",
        )
        inst = cls({})
        assert inst.category == GateCategory.GENERAL

    def test_level_default_is_swab(self) -> None:
        cls = make_custom_check_class(
            gate_name="x",
            description="d",
            category_key="general",
            command="echo ok",
        )
        assert cls.level == GateLevel.SWAB

    def test_level_scour(self) -> None:
        cls = make_custom_check_class(
            gate_name="x",
            description="d",
            category_key="general",
            command="echo ok",
            level_str="scour",
        )
        assert cls.level == GateLevel.SCOUR

    def test_timeout_stored(self) -> None:
        cls = make_custom_check_class(
            gate_name="x",
            description="d",
            category_key="laziness",
            command="echo ok",
            timeout=42,
        )
        inst = cls({})
        assert inst._timeout == 42

    def test_default_timeout(self) -> None:
        cls = make_custom_check_class(
            gate_name="x",
            description="d",
            category_key="laziness",
            command="echo ok",
        )
        inst = cls({})
        assert inst._timeout == DEFAULT_CUSTOM_TIMEOUT

    def test_is_custom_gate_flag(self) -> None:
        cls = make_custom_check_class(
            gate_name="x",
            description="d",
            category_key="laziness",
            command="echo ok",
        )
        assert cls.is_custom_gate is True

    def test_is_always_applicable(self, tmp_path: Any) -> None:
        cls = make_custom_check_class(
            gate_name="x",
            description="d",
            category_key="laziness",
            command="echo ok",
        )
        inst = cls({})
        assert inst.is_applicable(str(tmp_path)) is True

    def test_gate_description(self) -> None:
        cls = make_custom_check_class(
            gate_name="my-gate",
            description="Finds bad patterns",
            category_key="laziness",
            command="echo ok",
        )
        inst = cls({})
        assert inst.gate_description == "Finds bad patterns"

    def test_class_name_reflects_gate(self) -> None:
        cls = make_custom_check_class(
            gate_name="no-debugger-imports",
            description="d",
            category_key="laziness",
            command="echo ok",
        )
        assert cls.__name__ == "CustomCheck_no_debugger_imports"

    def test_flaw_maps_from_category(self) -> None:
        """Flaw property derives from category for flaw-based categories."""
        from slopmop.checks.base import Flaw

        for cat_key, expected_flaw in [
            ("overconfidence", Flaw.OVERCONFIDENCE),
            ("deceptiveness", Flaw.DECEPTIVENESS),
            ("laziness", Flaw.LAZINESS),
            ("myopia", Flaw.MYOPIA),
        ]:
            cls = make_custom_check_class(
                gate_name=f"test-{cat_key}",
                description="d",
                category_key=cat_key,
                command="echo ok",
            )
            inst = cls({})
            assert inst.flaw == expected_flaw, f"failed for {cat_key}"

    def test_general_flaw_defaults_to_laziness(self) -> None:
        """Non-flaw categories (general) get Flaw.LAZINESS as fallback."""
        from slopmop.checks.base import Flaw

        cls = make_custom_check_class(
            gate_name="x",
            description="d",
            category_key="general",
            command="echo ok",
        )
        inst = cls({})
        assert inst.flaw == Flaw.LAZINESS

    def test_special_characters_in_name(self) -> None:
        """Gate names can contain dots, underscores, etc."""
        cls = make_custom_check_class(
            gate_name="my_gate.v2",
            description="d",
            category_key="laziness",
            command="echo ok",
        )
        inst = cls({})
        assert inst.name == "my_gate.v2"

    def test_empty_description(self) -> None:
        cls = make_custom_check_class(
            gate_name="x",
            description="",
            category_key="laziness",
            command="echo ok",
        )
        inst = cls({})
        assert inst.gate_description == ""

    def test_each_call_returns_unique_class(self) -> None:
        """Multiple calls produce distinct classes that don't share state."""
        cls_a = make_custom_check_class(
            gate_name="a", description="A", category_key="laziness", command="echo a"
        )
        cls_b = make_custom_check_class(
            gate_name="b", description="B", category_key="myopia", command="echo b"
        )
        assert cls_a is not cls_b
        assert cls_a({}).name == "a"
        assert cls_b({}).name == "b"
        assert cls_a({}).category != cls_b({}).category


# ── make_custom_check_class — run() ──────────────────────────────────


class TestCustomCheckRun:
    """Tests for the run() method of dynamically created checks."""

    def test_passing_command(self, tmp_path: Any) -> None:
        cls = make_custom_check_class(
            gate_name="pass", description="d", category_key="laziness", command="true"
        )
        result = cls({}).run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_failing_command(self, tmp_path: Any) -> None:
        cls = make_custom_check_class(
            gate_name="fail", description="d", category_key="laziness", command="false"
        )
        result = cls({}).run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "exit code" in (result.error or "")

    def test_output_captured(self, tmp_path: Any) -> None:
        cls = make_custom_check_class(
            gate_name="echo",
            description="d",
            category_key="laziness",
            command="echo hello-world",
        )
        result = cls({}).run(str(tmp_path))
        assert result.status == CheckStatus.PASSED
        assert "hello-world" in (result.output or "")

    def test_stderr_captured_on_failure(self, tmp_path: Any) -> None:
        cls = make_custom_check_class(
            gate_name="err",
            description="d",
            category_key="laziness",
            command="echo error-info >&2; false",
        )
        result = cls({}).run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "error-info" in (result.output or "")

    def test_timeout_produces_failure(self, tmp_path: Any) -> None:
        cls = make_custom_check_class(
            gate_name="slow",
            description="d",
            category_key="laziness",
            command="sleep 60",
            timeout=1,
        )
        result = cls({}).run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "timed out" in (result.error or "")

    def test_shell_pipes_work(self, tmp_path: Any) -> None:
        """Custom gates support shell features like pipes."""
        cls = make_custom_check_class(
            gate_name="pipe",
            description="d",
            category_key="laziness",
            command="echo 'line1\nline2\nline3' | wc -l",
        )
        result = cls({}).run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_fix_suggestion_on_failure(self, tmp_path: Any) -> None:
        cls = make_custom_check_class(
            gate_name="x",
            description="d",
            category_key="laziness",
            command="false",
        )
        result = cls({}).run(str(tmp_path))
        assert result.fix_suggestion is not None
        assert "false" in result.fix_suggestion

    def test_duration_recorded(self, tmp_path: Any) -> None:
        cls = make_custom_check_class(
            gate_name="x",
            description="d",
            category_key="laziness",
            command="true",
        )
        result = cls({}).run(str(tmp_path))
        assert result.duration is not None
        assert result.duration >= 0


# ── register_custom_gates — happy path ───────────────────────────────


class TestRegisterCustomGatesHappyPath:
    """Tests for register_custom_gates() with valid config inputs."""

    @pytest.fixture(autouse=True)
    def _fresh_registry(self) -> Any:
        """Provide a fresh registry for each test."""
        from slopmop.core.registry import CheckRegistry

        mock_registry = CheckRegistry()
        with patch("slopmop.core.registry.get_registry", return_value=mock_registry):
            self._registry = mock_registry
            yield

    def test_single_gate_registration(self) -> None:
        config: Dict[str, Any] = {
            "custom_gates": [
                {
                    "name": "my-check",
                    "description": "A simple check",
                    "category": "laziness",
                    "command": "echo ok",
                    "level": "swab",
                    "timeout": 30,
                }
            ]
        }
        registered = register_custom_gates(config)
        assert len(registered) == 1
        assert registered[0] == "laziness:my-check"

    def test_multiple_gates(self) -> None:
        config: Dict[str, Any] = {
            "custom_gates": [
                {"name": "gate-a", "command": "echo a"},
                {"name": "gate-b", "command": "echo b", "category": "myopia"},
            ]
        }
        registered = register_custom_gates(config)
        assert len(registered) == 2

    def test_default_category_is_general(self) -> None:
        config: Dict[str, Any] = {"custom_gates": [{"name": "x", "command": "echo ok"}]}
        registered = register_custom_gates(config)
        assert registered[0] == "general:x"

    def test_default_level_is_swab(self) -> None:
        config: Dict[str, Any] = {"custom_gates": [{"name": "x", "command": "echo ok"}]}
        register_custom_gates(config)
        # Verify by inspecting registry
        classes = list(self._registry._check_classes.values())
        assert len(classes) == 1
        assert classes[0].level == GateLevel.SWAB

    def test_default_timeout(self) -> None:
        config: Dict[str, Any] = {"custom_gates": [{"name": "x", "command": "echo ok"}]}
        register_custom_gates(config)
        classes = list(self._registry._check_classes.values())
        inst = classes[0]({})
        assert inst._timeout == DEFAULT_CUSTOM_TIMEOUT

    def test_description_defaults_to_name(self) -> None:
        config: Dict[str, Any] = {
            "custom_gates": [{"name": "my-check", "command": "echo ok"}]
        }
        register_custom_gates(config)
        classes = list(self._registry._check_classes.values())
        inst = classes[0]({})
        assert inst.gate_description == "my-check"

    def test_empty_custom_gates_list(self) -> None:
        config: Dict[str, Any] = {"custom_gates": []}
        registered = register_custom_gates(config)
        assert registered == []

    def test_no_custom_gates_key(self) -> None:
        config: Dict[str, Any] = {}
        registered = register_custom_gates(config)
        assert registered == []

    def test_scour_level(self) -> None:
        config: Dict[str, Any] = {
            "custom_gates": [{"name": "x", "command": "echo ok", "level": "scour"}]
        }
        register_custom_gates(config)
        classes = list(self._registry._check_classes.values())
        assert classes[0].level == GateLevel.SCOUR

    def test_float_timeout_truncated_to_int(self) -> None:
        config: Dict[str, Any] = {
            "custom_gates": [{"name": "x", "command": "echo ok", "timeout": 45.9}]
        }
        register_custom_gates(config)
        classes = list(self._registry._check_classes.values())
        inst = classes[0]({})
        assert inst._timeout == 45

    def test_all_categories(self) -> None:
        """All valid category keys produce corresponding GateCategory."""
        for cat_key in (
            "overconfidence",
            "deceptiveness",
            "laziness",
            "myopia",
            "general",
        ):
            config: Dict[str, Any] = {
                "custom_gates": [
                    {
                        "name": f"gate-{cat_key}",
                        "command": "echo ok",
                        "category": cat_key,
                    }
                ]
            }
            registered = register_custom_gates(config)
            assert registered[0] == f"{cat_key}:gate-{cat_key}"


# ── register_custom_gates — invalid inputs ───────────────────────────


class TestRegisterCustomGatesInvalidInputs:
    """Tests for register_custom_gates() with malformed/invalid config."""

    @pytest.fixture(autouse=True)
    def _fresh_registry(self) -> Any:
        """Provide a fresh registry for each test."""
        from slopmop.core.registry import CheckRegistry

        mock_registry = CheckRegistry()
        with patch("slopmop.core.registry.get_registry", return_value=mock_registry):
            self._registry = mock_registry
            yield

    # ── custom_gates is not a list ────────────────────────────────

    def test_custom_gates_is_string(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = register_custom_gates({"custom_gates": "not a list"})
        assert result == []
        assert "must be a list" in caplog.text

    def test_custom_gates_is_dict(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = register_custom_gates(
                {"custom_gates": {"name": "x", "command": "y"}}
            )
        assert result == []
        assert "must be a list" in caplog.text

    def test_custom_gates_is_number(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = register_custom_gates({"custom_gates": 42})
        assert result == []

    def test_custom_gates_is_none(self) -> None:
        result = register_custom_gates({"custom_gates": None})
        assert result == []

    def test_custom_gates_is_bool(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = register_custom_gates({"custom_gates": True})
        assert result == []

    # ── individual gate definition is not a dict ──────────────────

    def test_gate_entry_is_string(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = register_custom_gates({"custom_gates": ["not-a-dict"]})
        assert result == []
        assert "expected object" in caplog.text

    def test_gate_entry_is_list(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = register_custom_gates({"custom_gates": [["a", "b"]]})
        assert result == []
        assert "expected object" in caplog.text

    def test_gate_entry_is_number(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = register_custom_gates({"custom_gates": [123]})
        assert result == []

    def test_gate_entry_is_none(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = register_custom_gates({"custom_gates": [None]})
        assert result == []

    # ── missing required fields ───────────────────────────────────

    def test_missing_name(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = register_custom_gates({"custom_gates": [{"command": "echo ok"}]})
        assert result == []
        assert "'name' and 'command' are required" in caplog.text

    def test_missing_command(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = register_custom_gates({"custom_gates": [{"name": "my-gate"}]})
        assert result == []
        assert "'name' and 'command' are required" in caplog.text

    def test_missing_both_name_and_command(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            result = register_custom_gates(
                {"custom_gates": [{"description": "no name or command"}]}
            )
        assert result == []

    def test_empty_name(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = register_custom_gates(
                {"custom_gates": [{"name": "", "command": "echo ok"}]}
            )
        assert result == []
        assert "'name' and 'command' are required" in caplog.text

    def test_empty_command(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = register_custom_gates(
                {"custom_gates": [{"name": "x", "command": ""}]}
            )
        assert result == []

    # ── name/command coerced from non-string types ────────────────

    def test_name_is_number_coerced(self) -> None:
        """Non-string name is str()-coerced successfully."""
        result = register_custom_gates(
            {"custom_gates": [{"name": 42, "command": "echo ok"}]}
        )
        assert len(result) == 1
        assert "42" in result[0]

    def test_command_is_number_coerced(self) -> None:
        """Non-string command is str()-coerced."""
        result = register_custom_gates(
            {"custom_gates": [{"name": "x", "command": 123}]}
        )
        assert len(result) == 1

    def test_name_is_none(self, caplog: pytest.LogCaptureFixture) -> None:
        """None name coerces to 'None' string which is truthy — accepted."""
        result = register_custom_gates(
            {"custom_gates": [{"name": None, "command": "echo ok"}]}
        )
        # str(None) == "None" which is truthy, so it should pass
        assert len(result) == 1

    # ── invalid timeout values ────────────────────────────────────

    def test_timeout_zero(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = register_custom_gates(
                {"custom_gates": [{"name": "x", "command": "echo ok", "timeout": 0}]}
            )
        assert len(result) == 1
        assert "invalid timeout" in caplog.text

    def test_timeout_negative(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = register_custom_gates(
                {"custom_gates": [{"name": "x", "command": "echo ok", "timeout": -5}]}
            )
        assert len(result) == 1
        assert "invalid timeout" in caplog.text

    def test_timeout_string(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = register_custom_gates(
                {
                    "custom_gates": [
                        {"name": "x", "command": "echo ok", "timeout": "fast"}
                    ]
                }
            )
        assert len(result) == 1
        assert "invalid timeout" in caplog.text

    def test_timeout_none(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = register_custom_gates(
                {"custom_gates": [{"name": "x", "command": "echo ok", "timeout": None}]}
            )
        assert len(result) == 1
        assert "invalid timeout" in caplog.text

    def test_timeout_bool_true(self, caplog: pytest.LogCaptureFixture) -> None:
        """bool is a subclass of int: True=1 which is > 0, accepted."""
        result = register_custom_gates(
            {"custom_gates": [{"name": "x", "command": "echo ok", "timeout": True}]}
        )
        assert len(result) == 1

    def test_timeout_bool_false(self, caplog: pytest.LogCaptureFixture) -> None:
        """False=0 which fails the > 0 check."""
        with caplog.at_level(logging.WARNING):
            result = register_custom_gates(
                {
                    "custom_gates": [
                        {"name": "x", "command": "echo ok", "timeout": False}
                    ]
                }
            )
        assert len(result) == 1
        assert "invalid timeout" in caplog.text

    def test_invalid_timeout_gets_default(self) -> None:
        """Invalid timeout falls back to DEFAULT_CUSTOM_TIMEOUT."""
        register_custom_gates(
            {"custom_gates": [{"name": "x", "command": "echo ok", "timeout": "bad"}]}
        )
        classes = list(self._registry._check_classes.values())
        inst = classes[0]({})
        assert inst._timeout == DEFAULT_CUSTOM_TIMEOUT

    # ── invalid category values ───────────────────────────────────

    def test_unknown_category_accepted_as_general(self) -> None:
        result = register_custom_gates(
            {"custom_gates": [{"name": "x", "command": "echo ok", "category": "wat"}]}
        )
        assert len(result) == 1
        assert result[0] == "general:x"

    def test_category_is_number(self) -> None:
        """Non-string category is str()-coerced."""
        result = register_custom_gates(
            {"custom_gates": [{"name": "x", "command": "echo ok", "category": 99}]}
        )
        # str(99) = "99" → unknown → general
        assert result[0] == "general:x"

    def test_category_is_none(self) -> None:
        """None category → str(None)='None' → unknown → general."""
        result = register_custom_gates(
            {"custom_gates": [{"name": "x", "command": "echo ok", "category": None}]}
        )
        assert result[0] == "general:x"

    # ── invalid level values ──────────────────────────────────────

    def test_unknown_level_defaults_to_swab(self) -> None:
        register_custom_gates(
            {
                "custom_gates": [
                    {"name": "x", "command": "echo ok", "level": "deep-clean"}
                ]
            }
        )
        classes = list(self._registry._check_classes.values())
        assert classes[0].level == GateLevel.SWAB

    def test_level_is_number(self) -> None:
        """Level coerced to string, doesn't match → swab."""
        register_custom_gates(
            {"custom_gates": [{"name": "x", "command": "echo ok", "level": 1}]}
        )
        classes = list(self._registry._check_classes.values())
        assert classes[0].level == GateLevel.SWAB

    # ── mixed valid and invalid entries ───────────────────────────

    def test_valid_and_invalid_mixed(self, caplog: pytest.LogCaptureFixture) -> None:
        """Valid gates register; invalid ones are skipped with warnings."""
        config: Dict[str, Any] = {
            "custom_gates": [
                {"name": "good-gate", "command": "echo ok"},
                {"name": "bad-gate"},  # missing command
                "not-a-dict",
                {"name": "also-good", "command": "true"},
            ]
        }
        with caplog.at_level(logging.WARNING):
            result = register_custom_gates(config)

        assert len(result) == 2
        names = [r.split(":")[-1] for r in result]
        assert "good-gate" in names
        assert "also-good" in names

    def test_extra_fields_ignored(self) -> None:
        """Unknown fields in the gate definition don't cause failures."""
        config: Dict[str, Any] = {
            "custom_gates": [
                {
                    "name": "x",
                    "command": "echo ok",
                    "unknown_field": "value",
                    "another": 123,
                    "nested": {"a": "b"},
                }
            ]
        }
        result = register_custom_gates(config)
        assert len(result) == 1


# ── register_custom_gates — edge cases ───────────────────────────────


class TestRegisterCustomGatesEdgeCases:
    """Edge cases and boundary conditions for custom gate registration."""

    @pytest.fixture(autouse=True)
    def _fresh_registry(self) -> Any:
        from slopmop.core.registry import CheckRegistry

        mock_registry = CheckRegistry()
        with patch("slopmop.core.registry.get_registry", return_value=mock_registry):
            self._registry = mock_registry
            yield

    def test_description_with_unicode(self) -> None:
        config: Dict[str, Any] = {
            "custom_gates": [
                {
                    "name": "unicode-gate",
                    "description": "Check für Ünïcödë 🎉",
                    "command": "echo ok",
                }
            ]
        }
        result = register_custom_gates(config)
        assert len(result) == 1
        classes = list(self._registry._check_classes.values())
        inst = classes[0]({})
        assert "Ünïcödë" in inst.gate_description

    def test_command_with_shell_metacharacters(self) -> None:
        """Commands with pipes, redirects, and globs should be accepted."""
        config: Dict[str, Any] = {
            "custom_gates": [
                {
                    "name": "complex-cmd",
                    "command": "grep -rn 'import pdb' src/ | wc -l && echo done > /dev/null",
                }
            ]
        }
        result = register_custom_gates(config)
        assert len(result) == 1

    def test_name_with_dots_and_extensions(self) -> None:
        """Gate names can contain dots (e.g. 'stale-docs.py')."""
        config: Dict[str, Any] = {
            "custom_gates": [{"name": "stale-docs.py", "command": "echo ok"}]
        }
        result = register_custom_gates(config)
        assert len(result) == 1
        assert "stale-docs.py" in result[0]

    def test_fix_command_enables_auto_fix(self, tmp_path) -> None:
        """Custom gates with fix_command should support auto-fix."""
        from slopmop.checks.custom import make_custom_check_class

        check_class = make_custom_check_class(
            gate_name="docs-refresh",
            description="Refresh docs",
            category_key="laziness",
            command="exit 1",
            fix_command="touch fixed.txt",
        )
        check = check_class({})

        assert check.can_auto_fix() is True
        assert check.auto_fix(str(tmp_path)) is True
        assert (tmp_path / "fixed.txt").exists()

    def test_very_long_name(self) -> None:
        long_name = "x" * 500
        config: Dict[str, Any] = {
            "custom_gates": [{"name": long_name, "command": "echo ok"}]
        }
        result = register_custom_gates(config)
        assert len(result) == 1
        assert long_name in result[0]

    def test_very_long_command(self) -> None:
        long_cmd = "echo " + "a" * 1000
        config: Dict[str, Any] = {
            "custom_gates": [{"name": "long-cmd", "command": long_cmd}]
        }
        result = register_custom_gates(config)
        assert len(result) == 1

    def test_many_gates(self) -> None:
        """Register many gates at once."""
        gates = [{"name": f"gate-{i}", "command": f"echo {i}"} for i in range(50)]
        config: Dict[str, Any] = {"custom_gates": gates}
        result = register_custom_gates(config)
        assert len(result) == 50

    def test_whitespace_only_name_rejected(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Names that are only whitespace: str(name)='   ' is truthy → accepted.

        This is a known behavior — whitespace-only names pass the truthiness
        check.  The str() coercion means any non-empty value after str() is
        accepted.
        """
        config: Dict[str, Any] = {
            "custom_gates": [{"name": "   ", "command": "echo ok"}]
        }
        result = register_custom_gates(config)
        # Whitespace-only string is truthy, so it passes
        assert len(result) == 1

    def test_description_coerced_from_number(self) -> None:
        config: Dict[str, Any] = {
            "custom_gates": [{"name": "x", "command": "echo ok", "description": 42}]
        }
        result = register_custom_gates(config)
        assert len(result) == 1
        classes = list(self._registry._check_classes.values())
        inst = classes[0]({})
        assert inst.gate_description == "42"

    def test_large_timeout_accepted(self) -> None:
        config: Dict[str, Any] = {
            "custom_gates": [{"name": "x", "command": "echo ok", "timeout": 999999}]
        }
        result = register_custom_gates(config)
        assert len(result) == 1
        classes = list(self._registry._check_classes.values())
        inst = classes[0]({})
        assert inst._timeout == 999999
