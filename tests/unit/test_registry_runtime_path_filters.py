"""Tests for repo-wide and gate-local runtime path filter merging."""

from slopmop.checks import ensure_checks_registered
from slopmop.core.registry import get_registry


class TestRuntimePathFilters:
    """Shared exclude/include filters should merge into gate configs once."""

    def test_repeated_code_merges_global_and_gate_local_excludes(self):
        ensure_checks_registered()
        config = {
            "_global_exclude_paths": ["vendor", "build-output", "*.snap"],
            "laziness": {
                "gates": {
                    "repeated-code": {
                        "exclude_dirs": ["coverage"],
                        "extra_exclude_paths": ["docs"],
                        "include_paths": ["vendor"],
                    }
                }
            },
        }

        check = get_registry().get_check("laziness:repeated-code", config)

        assert check is not None
        assert check.config["exclude_dirs"] == [
            "coverage",
            "build-output",
            "docs",
        ]

    def test_string_duplication_receives_runtime_ignore_patterns(self):
        ensure_checks_registered()
        config = {
            "_global_exclude_paths": ["docs", "coverage/*.json"],
            "myopia": {
                "gates": {
                    "string-duplication.py": {
                        "include_paths": ["docs"],
                    }
                }
            },
        }

        check = get_registry().get_check("myopia:string-duplication.py", config)

        assert check is not None
        ignore_patterns = check.config["ignore_patterns"]
        assert "coverage/*.json" in ignore_patterns
        assert not any(
            pattern == "docs" or "docs/" in pattern for pattern in ignore_patterns
        )

    def test_security_gate_keeps_default_excludes_when_global_paths_merge(self):
        ensure_checks_registered()
        config = {
            "_global_exclude_paths": ["vendor", ".tmp"],
        }

        check = get_registry().get_check("myopia:vulnerability-blindness.py", config)

        assert check is not None
        assert "tests" in check.config["exclude_dirs"]
        assert "vendor" in check.config["exclude_dirs"]
        assert ".tmp" in check.config["exclude_dirs"]
