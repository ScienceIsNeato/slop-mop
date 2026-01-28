"""
Tests for check_discovery.py — dynamic class loading.
"""

import pytest

from slopbucket.check_discovery import load_check, load_checks, validate_all_registered
from slopbucket.config import CHECK_REGISTRY, CheckDef


class TestLoadCheck:
    """Tests for single check loading."""

    def test_load_valid_check(self) -> None:
        check_def = CHECK_REGISTRY["python-format"]
        check = load_check(check_def)
        assert check.name == "python-format"

    def test_load_invalid_module_raises(self) -> None:
        from slopbucket.check_discovery import DiscoveryError

        bad_def = CheckDef(
            name="bad",
            module_path="slopbucket.checks.does_not_exist",
            class_name="FakeCheck",
        )
        with pytest.raises(DiscoveryError, match="Cannot import"):
            load_check(bad_def)

    def test_load_missing_class_raises(self) -> None:
        from slopbucket.check_discovery import DiscoveryError

        bad_def = CheckDef(
            name="bad",
            module_path="slopbucket.checks.python_format",
            class_name="NonExistentClass",
        )
        with pytest.raises(DiscoveryError, match="has no class"):
            load_check(bad_def)


class TestLoadChecks:
    """Tests for batch check loading."""

    def test_load_multiple_valid_checks(self) -> None:
        defs = [CHECK_REGISTRY["python-format"], CHECK_REGISTRY["python-lint"]]
        checks = load_checks(defs)
        assert len(checks) == 2
        names = {c.name for c in checks}
        assert "python-format" in names
        assert "python-lint" in names

    def test_load_with_invalid_raises(self) -> None:
        from slopbucket.check_discovery import DiscoveryError

        defs = [
            CHECK_REGISTRY["python-format"],
            CheckDef(
                name="bad",
                module_path="nonexistent.module",
                class_name="Fake",
            ),
        ]
        with pytest.raises(DiscoveryError):
            load_checks(defs)


class TestValidateAllRegistered:
    """Tests that all registered checks can be loaded."""

    def test_all_registered_checks_loadable(self) -> None:
        """This is the key self-check: every check in the registry must load."""
        errors = validate_all_registered()
        assert errors == {}, f"Failed to load checks: {errors}"
