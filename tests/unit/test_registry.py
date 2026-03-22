"""Tests for check registry."""

from slopmop.checks.base import BaseCheck, Flaw, GateCategory, GateLevel
from slopmop.core.registry import CheckRegistry, get_registry
from slopmop.core.result import CheckDefinition, CheckResult, CheckStatus


class MockCheck(BaseCheck):
    """Mock check for testing."""

    _mock_name = "mock-check"
    _mock_display_name = "Mock Check"
    _mock_depends_on = []
    _mock_applicable = True

    @property
    def name(self) -> str:
        return self._mock_name

    @property
    def display_name(self) -> str:
        return self._mock_display_name

    @property
    def category(self) -> GateCategory:
        return GateCategory.OVERCONFIDENCE

    @property
    def flaw(self) -> Flaw:
        return Flaw.OVERCONFIDENCE

    @property
    def depends_on(self) -> list:
        return self._mock_depends_on

    def is_applicable(self, project_root: str) -> bool:
        return self._mock_applicable

    def run(self, project_root: str) -> CheckResult:
        return CheckResult(
            name=self.name,
            status=CheckStatus.PASSED,
            duration=0.1,
            output="Mock output",
        )


def make_mock_check_class(name: str, depends_on: list = None):  # noqa: ambiguity-mine
    """Factory to create mock check classes with specific names."""

    class DynamicMockCheck(MockCheck):
        _mock_name = name
        _mock_display_name = f"Mock: {name}"
        _mock_depends_on = depends_on or []

    return DynamicMockCheck


class TestCheckRegistry:
    """Tests for CheckRegistry class."""

    def test_register_check(self):
        """Test registering a check class."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("test-check")

        registry.register(check_class)

        # Registry now uses full_name (category:name)
        assert "overconfidence:test-check" in registry.list_checks()

    def test_register_check_with_definition(self):
        """Test registering a check creates definition."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("test-check")

        registry.register(check_class)
        definition = registry.get_definition("overconfidence:test-check")

        assert definition is not None
        assert definition.flag == "overconfidence:test-check"
        assert definition.name == "Mock: test-check"

    def test_register_duplicate_check_overwrites(self):
        """Test registering duplicate check overwrites (with warning)."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("test-check")
        check_class2 = make_mock_check_class("test-check")

        registry.register(check_class1)
        # Should not raise, just warn and overwrite
        registry.register(check_class2)

        assert "overconfidence:test-check" in registry.list_checks()

    def test_get_checks_by_name(self):
        """Test getting checks by name."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("check1")
        check_class2 = make_mock_check_class("check2")

        registry.register(check_class1)
        registry.register(check_class2)

        checks = registry.get_checks(["overconfidence:check1"], {})
        assert len(checks) == 1
        assert checks[0].name == "check1"

    def test_get_checks_unknown_name_returns_empty(self):
        """Test getting unknown check name returns empty list."""
        registry = CheckRegistry()
        checks = registry.get_checks(["nonexistent"], {})
        assert len(checks) == 0

    def test_get_checks_passes_config(self):
        """Test getting checks extracts gate-specific config."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("check1")
        registry.register(check_class)

        # Config structure: { "category": { "gates": { "check-name": {...} } } }
        full_config = {"overconfidence": {"gates": {"check1": {"threshold": 90}}}}
        checks = registry.get_checks(["overconfidence:check1"], full_config)

        assert len(checks) == 1
        assert checks[0].config == {"threshold": 90}

    def test_extract_gate_config(self):
        """Test _extract_gate_config extracts correct nested config."""
        registry = CheckRegistry()

        full_config = {
            "overconfidence": {
                "enabled": True,
                "gates": {
                    "untested-code.py": {"timeout": 300},
                    "coverage-gaps.py": {"threshold": 80},
                },
            },
            "laziness": {"gates": {"sloppy-formatting.js": {"auto_fix": True}}},
        }

        # Extract overconfidence:coverage-gaps.py config
        config = registry._extract_gate_config(
            "overconfidence:coverage-gaps.py", full_config
        )
        assert config == {"threshold": 80}

        # Extract laziness:sloppy-formatting.js config
        config = registry._extract_gate_config(
            "laziness:sloppy-formatting.js", full_config
        )
        assert config == {"auto_fix": True}

        # Extract nonexistent gate returns empty dict
        config = registry._extract_gate_config(
            "overconfidence:nonexistent", full_config
        )
        assert config == {}

        # Invalid name format returns empty dict
        config = registry._extract_gate_config("invalid", full_config)
        assert config == {}

    def test_get_single_check(self):
        """Test getting a single check instance."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("check1")
        registry.register(check_class)

        check = registry.get_check("overconfidence:check1", {})
        assert check is not None
        assert check.name == "check1"

    def test_get_single_check_nonexistent(self):
        """Test getting nonexistent check returns None."""
        registry = CheckRegistry()
        check = registry.get_check("nonexistent", {})
        assert check is None

    def test_list_checks_empty(self):
        """Test listing checks on empty registry."""
        registry = CheckRegistry()
        assert registry.list_checks() == []

    def test_get_definition_nonexistent(self):
        """Test getting definition for nonexistent check."""
        registry = CheckRegistry()
        assert registry.get_definition("nonexistent") is None

    def test_get_registry_singleton(self):
        """Test get_registry returns singleton."""
        import slopmop.checks as checks_module
        import slopmop.core.registry as registry_module

        old_registry = registry_module._default_registry
        old_checks_registered = checks_module._checks_registered
        try:
            registry_module._default_registry = None

            reg1 = get_registry()
            reg2 = get_registry()
            assert reg1 is reg2
        finally:
            registry_module._default_registry = old_registry
            checks_module._checks_registered = old_checks_registered

    def test_get_checks_removes_duplicates(self):
        """Test that duplicate check names are deduplicated."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("check1")
        registry.register(check_class)

        checks = registry.get_checks(
            ["overconfidence:check1", "overconfidence:check1"], {}
        )
        assert len(checks) == 1

    def test_get_applicable_checks(self, tmp_path):
        """Test get_applicable_checks returns only applicable checks."""
        registry = CheckRegistry()

        class ApplicableCheck(MockCheck):
            _mock_name = "applicable"
            _mock_applicable = True

        class NotApplicableCheck(MockCheck):
            _mock_name = "not-applicable"
            _mock_applicable = False

        registry.register(ApplicableCheck)
        registry.register(NotApplicableCheck)

        applicable = registry.get_applicable_checks(str(tmp_path), {})

        # Only one check should be applicable
        assert len(applicable) == 1
        assert applicable[0].name == "applicable"

    def test_get_applicable_checks_empty(self, tmp_path):
        """Test get_applicable_checks with no registered checks."""
        registry = CheckRegistry()
        applicable = registry.get_applicable_checks(str(tmp_path), {})
        assert applicable == []

    def test_get_gate_names_for_level_respects_run_on_override(self):
        """Config can move a gate from swab membership to scour-only."""
        registry = CheckRegistry()

        class SwabCheck(MockCheck):
            _mock_name = "swab-check"

        class ScourCheck(MockCheck):
            _mock_name = "scour-check"
            level = GateLevel.SCOUR

        registry.register(SwabCheck)
        registry.register(ScourCheck)

        config = {
            "overconfidence": {
                "gates": {
                    "swab-check": {"run_on": "scour"},
                    "scour-check": {"run_on": "swab"},
                }
            }
        }

        swab = registry.get_gate_names_for_level(GateLevel.SWAB, config)
        scour = registry.get_gate_names_for_level(GateLevel.SCOUR, config)

        assert "overconfidence:swab-check" not in swab
        assert "overconfidence:scour-check" in swab
        assert "overconfidence:swab-check" in scour
        assert "overconfidence:scour-check" in scour

    def test_curated_remediation_priority_beats_fallbacks(self):
        """Built-in curated order should be the primary remediation source."""
        from slopmop.checks import ensure_checks_registered
        from slopmop.core.registry import (
            curated_remediation_order_names,
            get_registry,
        )

        ensure_checks_registered()
        registry = get_registry()
        check = registry.get_check("myopia:source-duplication", {})
        expected_priority = (
            curated_remediation_order_names().index("myopia:source-duplication") + 1
        ) * 10

        assert check is not None
        assert registry.remediation_priority_for_check(check) == expected_priority
        assert registry.remediation_priority_source_for_check(check) == "curated"

    def test_explicit_remediation_priority_used_when_not_curated(self):
        """Non-curated checks can still provide explicit priority."""
        registry = CheckRegistry()

        class ExplicitPriorityCheck(MockCheck):
            _mock_name = "explicit-priority"
            remediation_priority = 17

        registry.register(ExplicitPriorityCheck)
        check = registry.get_check("overconfidence:explicit-priority", {})

        assert check is not None
        assert registry.remediation_priority_for_check(check) == 17
        assert registry.remediation_priority_source_for_check(check) == "explicit"


class TestRegisterCheckDecorator:
    """Tests for @register_check decorator."""

    def test_register_check_decorator(self):
        """Test the register_check decorator adds check to registry."""
        import slopmop.checks as checks_module
        import slopmop.core.registry as registry_module
        from slopmop.core.registry import get_registry, register_check

        old_registry = registry_module._default_registry
        old_checks_registered = checks_module._checks_registered
        try:
            registry_module._default_registry = None

            @register_check
            class DecoratedCheck(BaseCheck):
                @property
                def name(self) -> str:
                    return "decorated-check"

                @property
                def display_name(self) -> str:
                    return "Decorated Check"

                @property
                def category(self) -> GateCategory:
                    return GateCategory.OVERCONFIDENCE

                @property
                def flaw(self) -> Flaw:
                    return Flaw.OVERCONFIDENCE

                def is_applicable(self, project_root: str) -> bool:
                    return True

                def run(self, project_root: str) -> CheckResult:
                    return CheckResult(
                        name=self.name,
                        status=CheckStatus.PASSED,
                        duration=0.01,
                        output="Success",
                    )

            reg = get_registry()
            assert "overconfidence:decorated-check" in reg.list_checks()
        finally:
            registry_module._default_registry = old_registry
            checks_module._checks_registered = old_checks_registered


class TestCheckDefinition:
    """Tests for CheckDefinition."""

    def test_definition_equality(self):
        """Test definitions are equal by flag."""
        def1 = CheckDefinition("test", "Test 1")
        def2 = CheckDefinition("test", "Test 2")
        def3 = CheckDefinition("other", "Other")

        assert def1 == def2
        assert def1 != def3

    def test_definition_hash(self):
        """Test definitions hash by flag."""
        def1 = CheckDefinition("test", "Test")
        def2 = CheckDefinition("test", "Test")

        assert hash(def1) == hash(def2)
        # Can be used in sets
        s = {def1, def2}
        assert len(s) == 1
