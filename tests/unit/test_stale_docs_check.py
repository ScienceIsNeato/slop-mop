"""Tests for stale-docs detection via readme_tables utilities.

The stale-docs gate was migrated from a built-in BaseCheck subclass to a
custom gate (see .sb_config.json ``custom_gates``).  The underlying utility
functions in ``slopmop.utils.readme_tables`` are still used by the
``scripts/generate_readme_tables.py`` script that the custom gate invokes.

These tests verify the utility layer independently of the custom gate
execution path.
"""

from pathlib import Path

import pytest

from slopmop.utils.readme_tables import BEGIN_MARKER, END_MARKER

# ── Helpers ───────────────────────────────────────────────────────────


def _write_readme(root: Path, content: str) -> Path:
    """Write content to README.md and return the path."""
    readme = root / "README.md"
    readme.write_text(content)
    return readme


def _readme_with_markers(tables_content: str = "") -> str:
    """Build a minimal README with gate table markers."""
    return (
        "# My Project\n\n"
        "Some intro text.\n\n"
        f"{BEGIN_MARKER}\n\n"
        f"{tables_content}\n"
        f"{END_MARKER}\n\n"
        "More text below.\n"
    )


# ── readme_tables utility tests ───────────────────────────────────────


class TestCheckReadme:
    """Tests for check_readme() utility function."""

    def _ensure_fresh_registry(self) -> None:
        """Force re-registration to handle test isolation issues."""
        import slopmop.checks as checks_mod

        checks_mod._checks_registered = False
        checks_mod.ensure_checks_registered()

    def test_no_readme_passes(self, tmp_path: Path) -> None:
        """check_readme returns True when no README exists."""
        from slopmop.core.registry import get_registry
        from slopmop.utils.readme_tables import check_readme

        registry = get_registry()
        is_ok, msg = check_readme(tmp_path / "README.md", registry)
        assert is_ok is True

    def test_readme_without_markers_passes(self, tmp_path: Path) -> None:
        """check_readme returns True when README has no markers."""
        from slopmop.core.registry import get_registry
        from slopmop.utils.readme_tables import check_readme

        _write_readme(tmp_path, "# Just a README\nNo markers.\n")
        registry = get_registry()
        is_ok, msg = check_readme(tmp_path / "README.md", registry)
        assert is_ok is True

    def test_stale_content_detected(self, tmp_path: Path) -> None:
        """check_readme returns False when marker content doesn't match."""
        from slopmop.core.registry import get_registry
        from slopmop.utils.readme_tables import check_readme

        self._ensure_fresh_registry()
        registry = get_registry()

        # Write README with wrong content between markers
        _write_readme(tmp_path, _readme_with_markers("| wrong | content |\n"))
        is_ok, msg = check_readme(tmp_path / "README.md", registry)
        assert is_ok is False
        assert "stale" in msg.lower()

    def test_matching_content_passes(self, tmp_path: Path) -> None:
        """check_readme returns True when content matches generated output."""
        from slopmop.core.registry import get_registry
        from slopmop.utils.readme_tables import (
            check_readme,
            generate_tables,
            splice_tables,
        )

        self._ensure_fresh_registry()
        registry = get_registry()

        # Generate correct tables, write them, then check
        tables = generate_tables(registry)
        readme_text = _readme_with_markers()
        correct_readme = splice_tables(readme_text, tables)
        _write_readme(tmp_path, correct_readme)

        is_ok, msg = check_readme(tmp_path / "README.md", registry)
        assert is_ok is True


class TestGenerateTables:
    """Tests for generate_tables() utility function."""

    def _ensure_fresh_registry(self) -> None:
        """Force re-registration to handle test isolation issues."""
        import slopmop.checks as checks_mod

        checks_mod._checks_registered = False
        checks_mod.ensure_checks_registered()

    def test_generates_nonempty_output(self) -> None:
        """generate_tables produces non-empty markdown."""
        from slopmop.core.registry import get_registry
        from slopmop.utils.readme_tables import generate_tables

        self._ensure_fresh_registry()
        registry = get_registry()
        tables = generate_tables(registry)
        assert len(tables) > 0
        assert "| Gate |" in tables

    def test_tables_contain_known_gates(self) -> None:
        """Generated tables include well-known built-in gates."""
        from slopmop.core.registry import get_registry
        from slopmop.utils.readme_tables import generate_tables

        self._ensure_fresh_registry()
        registry = get_registry()
        tables = generate_tables(registry)
        # These should always be present as built-in gates
        assert "coverage-gaps" in tables
        assert "complexity-creep" in tables
        assert "sloppy-formatting" in tables

    def test_stale_docs_not_in_generated_tables(self) -> None:
        """stale-docs is a custom gate and should NOT appear in built-in tables."""
        from slopmop.core.registry import get_registry
        from slopmop.utils.readme_tables import generate_tables

        self._ensure_fresh_registry()
        registry = get_registry()
        tables = generate_tables(registry)
        assert "stale-docs" not in tables


class TestSpliceTables:
    """Tests for splice_tables() utility function."""

    def test_splice_replaces_content_between_markers(self) -> None:
        from slopmop.utils.readme_tables import splice_tables

        readme = _readme_with_markers("old content")
        result = splice_tables(readme, "new tables\n")
        assert "new tables" in result
        assert "old content" not in result
        assert BEGIN_MARKER in result
        assert END_MARKER in result

    def test_splice_preserves_surrounding_content(self) -> None:
        from slopmop.utils.readme_tables import splice_tables

        readme = _readme_with_markers("old")
        result = splice_tables(readme, "new\n")
        assert "# My Project" in result
        assert "More text below." in result

    def test_splice_raises_without_markers(self) -> None:
        from slopmop.utils.readme_tables import splice_tables

        with pytest.raises(ValueError, match="markers not found"):
            splice_tables("No markers here", "tables\n")


# ── Custom gate registration ─────────────────────────────────────────


class TestCustomGateRegistration:
    """Verify stale-docs is no longer a built-in and can register as custom."""

    def test_stale_docs_not_in_builtin_registry(self) -> None:
        """StaleDocsCheck is no longer registered as a built-in gate."""
        import slopmop.checks as checks_mod
        from slopmop.core.registry import get_registry

        checks_mod._checks_registered = False
        checks_mod.ensure_checks_registered()
        registry = get_registry()
        assert "laziness:stale-docs" not in registry._check_classes

    def test_stale_docs_registers_as_custom_gate(self) -> None:
        """The custom gate definition from config registers correctly."""
        from slopmop.checks.custom import make_custom_check_class

        check_class = make_custom_check_class(
            gate_name="stale-docs",
            description="Detects stale README gate tables",
            category_key="laziness",
            command="python scripts/generate_readme_tables.py --check",
            level_str="swab",
            timeout=30,
        )
        instance = check_class({})
        assert instance.name == "stale-docs"
        assert instance.full_name == "laziness:stale-docs"
        assert instance.is_applicable("/any/path") is True
