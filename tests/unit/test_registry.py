"""Tests for check registry."""

from slopbucket.checks.base import BaseCheck, GateCategory
from slopbucket.core.registry import CheckRegistry, get_registry
from slopbucket.core.result import CheckDefinition, CheckResult, CheckStatus


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
        return GateCategory.PYTHON

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


def make_mock_check_class(name: str, depends_on: list = None):
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
        assert "python:test-check" in registry.list_checks()

    def test_register_check_with_definition(self):
        """Test registering a check creates definition."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("test-check")

        registry.register(check_class)
        definition = registry.get_definition("python:test-check")

        assert definition is not None
        assert definition.flag == "python:test-check"
        assert definition.name == "Mock: test-check"

    def test_register_duplicate_check_overwrites(self):
        """Test registering duplicate check overwrites (with warning)."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("test-check")
        check_class2 = make_mock_check_class("test-check")

        registry.register(check_class1)
        # Should not raise, just warn and overwrite
        registry.register(check_class2)

        assert "python:test-check" in registry.list_checks()

    def test_register_alias(self):
        """Test registering an alias."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("check1")
        check_class2 = make_mock_check_class("check2")

        registry.register(check_class1)
        registry.register(check_class2)
        registry.register_alias("both", ["python:check1", "python:check2"])

        aliases = registry.list_aliases()
        assert "both" in aliases
        assert aliases["both"] == ["python:check1", "python:check2"]

    def test_get_checks_by_name(self):
        """Test getting checks by name."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("check1")
        check_class2 = make_mock_check_class("check2")

        registry.register(check_class1)
        registry.register(check_class2)

        checks = registry.get_checks(["python:check1"], {})
        assert len(checks) == 1
        assert checks[0].name == "check1"

    def test_get_checks_expands_alias(self):
        """Test getting checks expands aliases."""
        registry = CheckRegistry()
        check_class1 = make_mock_check_class("check1")
        check_class2 = make_mock_check_class("check2")

        registry.register(check_class1)
        registry.register(check_class2)
        registry.register_alias("both", ["python:check1", "python:check2"])

        checks = registry.get_checks(["both"], {})
        assert len(checks) == 2
        names = [c.name for c in checks]
        assert "check1" in names
        assert "check2" in names

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
        full_config = {"python": {"gates": {"check1": {"threshold": 90}}}}
        checks = registry.get_checks(["python:check1"], full_config)

        assert len(checks) == 1
        assert checks[0].config == {"threshold": 90}

    def test_extract_gate_config(self):
        """Test _extract_gate_config extracts correct nested config."""
        registry = CheckRegistry()

        full_config = {
            "python": {
                "enabled": True,
                "gates": {"coverage": {"threshold": 80}, "tests": {"timeout": 300}},
            },
            "javascript": {"gates": {"lint": {"auto_fix": True}}},
        }

        # Extract python:coverage config
        config = registry._extract_gate_config("python:coverage", full_config)
        assert config == {"threshold": 80}

        # Extract javascript:lint config
        config = registry._extract_gate_config("javascript:lint", full_config)
        assert config == {"auto_fix": True}

        # Extract nonexistent gate returns empty dict
        config = registry._extract_gate_config("python:nonexistent", full_config)
        assert config == {}

        # Invalid name format returns empty dict
        config = registry._extract_gate_config("invalid", full_config)
        assert config == {}

    def test_get_single_check(self):
        """Test getting a single check instance."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("check1")
        registry.register(check_class)

        check = registry.get_check("python:check1", {})
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

    def test_list_aliases_empty(self):
        """Test listing aliases on empty registry."""
        registry = CheckRegistry()
        assert registry.list_aliases() == {}

    def test_get_definition_nonexistent(self):
        """Test getting definition for nonexistent check."""
        registry = CheckRegistry()
        assert registry.get_definition("nonexistent") is None

    def test_is_alias(self):
        """Test checking if name is an alias."""
        registry = CheckRegistry()
        registry.register_alias("myalias", ["python:check1", "python:check2"])

        assert registry.is_alias("myalias") is True
        assert registry.is_alias("python:check1") is False

    def test_expand_alias(self):
        """Test expanding an alias."""
        registry = CheckRegistry()
        registry.register_alias("myalias", ["python:check1", "python:check2"])

        expanded = registry.expand_alias("myalias")
        assert expanded == ["python:check1", "python:check2"]

    def test_expand_alias_non_alias(self):
        """Test expanding a non-alias returns itself."""
        registry = CheckRegistry()
        expanded = registry.expand_alias("not-an-alias")
        assert expanded == ["not-an-alias"]

    def test_get_registry_singleton(self):
        """Test get_registry returns singleton."""
        # Reset global registry for this test
        import slopbucket.core.registry as registry_module

        registry_module._default_registry = None

        reg1 = get_registry()
        reg2 = get_registry()
        assert reg1 is reg2

    def test_get_checks_removes_duplicates(self):
        """Test that duplicate check names are deduplicated."""
        registry = CheckRegistry()
        check_class = make_mock_check_class("check1")
        registry.register(check_class)

        checks = registry.get_checks(["python:check1", "python:check1"], {})
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


class TestRegisterCheckDecorator:
    """Tests for @register_check decorator."""

    def test_register_check_decorator(self):
        """Test the register_check decorator adds check to registry."""
        # Reset the global registry
        import slopbucket.core.registry as registry_module
        from slopbucket.core.registry import get_registry, register_check

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
                return GateCategory.PYTHON

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
        assert "python:decorated-check" in reg.list_checks()


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
