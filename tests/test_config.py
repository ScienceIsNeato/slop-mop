"""
Tests for config.py — profile resolution and check lookup.
"""

from slopbucket.config import (
    CHECK_REGISTRY,
    PROFILES,
    resolve_checks,
)


class TestCheckRegistry:
    """Tests for the check registry."""

    def test_all_checks_have_required_fields(self) -> None:
        for name, check_def in CHECK_REGISTRY.items():
            assert check_def.name == name
            assert check_def.module_path
            assert check_def.class_name
            assert check_def.description

    def test_known_checks_exist(self) -> None:
        expected = [
            "python-format",
            "python-lint",
            "python-types",
            "python-tests",
            "python-coverage",
            "python-complexity",
            "python-security",
            "js-format",
            "js-tests",
        ]
        for name in expected:
            assert name in CHECK_REGISTRY, f"Missing check: {name}"


class TestProfileResolution:
    """Tests for profile → check expansion."""

    def test_commit_profile_expands(self) -> None:
        checks = resolve_checks(["commit"])
        names = [c.name for c in checks]
        assert "python-format" in names
        assert "python-lint" in names
        assert "python-tests" in names

    def test_pr_profile_is_superset_of_commit(self) -> None:
        commit_checks = {c.name for c in resolve_checks(["commit"])}
        pr_checks = {c.name for c in resolve_checks(["pr"])}
        assert commit_checks.issubset(pr_checks)

    def test_individual_check_resolution(self) -> None:
        checks = resolve_checks(["python-format"])
        assert len(checks) == 1
        assert checks[0].name == "python-format"

    def test_mixed_profile_and_individual(self) -> None:
        checks = resolve_checks(["format", "python-tests"])
        names = [c.name for c in checks]
        assert "python-format" in names
        assert "python-tests" in names

    def test_deduplication(self) -> None:
        # format profile includes python-format; listing it again shouldn't duplicate
        checks = resolve_checks(["format", "python-format"])
        names = [c.name for c in checks]
        assert names.count("python-format") == 1

    def test_unknown_check_returns_empty(self) -> None:
        checks = resolve_checks(["totally_nonexistent_check_xyz"])
        assert len(checks) == 0

    def test_legacy_aliases_resolve(self) -> None:
        """Legacy aliases from ship_it.py should still work."""
        checks = resolve_checks(["python-lint-format"])
        names = [c.name for c in checks]
        assert "python-format" in names
        assert "python-lint" in names

    def test_all_profiles_reference_valid_checks(self) -> None:
        for profile_name, check_names in PROFILES.items():
            for check_name in check_names:
                assert (
                    check_name in CHECK_REGISTRY
                ), f"Profile '{profile_name}' references unknown check '{check_name}'"
