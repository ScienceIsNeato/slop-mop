"""Tests for laziness:stale-docs check."""

from pathlib import Path
from unittest.mock import patch

from slopmop.checks.base import Flaw, GateCategory, ToolContext
from slopmop.checks.quality.stale_docs import StaleDocsCheck
from slopmop.core.result import CheckStatus
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


# ── Metadata / properties ────────────────────────────────────────────


class TestStaleDocsProperties:
    """Tests for StaleDocsCheck metadata."""

    def test_name(self) -> None:
        check = StaleDocsCheck({})
        assert check.name == "stale-docs"

    def test_full_name(self) -> None:
        check = StaleDocsCheck({})
        assert check.full_name == "laziness:stale-docs"

    def test_display_name(self) -> None:
        check = StaleDocsCheck({})
        assert "Stale Docs" in check.display_name

    def test_gate_description(self) -> None:
        check = StaleDocsCheck({})
        assert "stale" in check.gate_description.lower()

    def test_category(self) -> None:
        check = StaleDocsCheck({})
        assert check.category == GateCategory.LAZINESS

    def test_flaw(self) -> None:
        check = StaleDocsCheck({})
        assert check.flaw == Flaw.LAZINESS

    def test_tool_context(self) -> None:
        check = StaleDocsCheck({})
        assert check.tool_context == ToolContext.PURE

    def test_docstring_present(self) -> None:
        assert StaleDocsCheck.__doc__ is not None
        assert len(StaleDocsCheck.__doc__) > 0


# ── is_applicable / skip_reason ───────────────────────────────────────


class TestApplicability:
    def test_applicable_when_readme_has_markers(self, tmp_path: Path) -> None:
        _write_readme(tmp_path, _readme_with_markers("placeholder"))
        check = StaleDocsCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_not_applicable_no_readme(self, tmp_path: Path) -> None:
        check = StaleDocsCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_not_applicable_readme_without_markers(self, tmp_path: Path) -> None:
        _write_readme(tmp_path, "# Just a plain README\n\nNo markers here.\n")
        check = StaleDocsCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_not_applicable_readme_with_only_begin_marker(self, tmp_path: Path) -> None:
        _write_readme(tmp_path, f"# README\n\n{BEGIN_MARKER}\n\nSome text.\n")
        check = StaleDocsCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_skip_reason_no_readme(self, tmp_path: Path) -> None:
        check = StaleDocsCheck({})
        reason = check.skip_reason(str(tmp_path))
        assert "No README.md" in reason

    def test_skip_reason_no_markers(self, tmp_path: Path) -> None:
        _write_readme(tmp_path, "# Plain README\n")
        check = StaleDocsCheck({})
        reason = check.skip_reason(str(tmp_path))
        assert "marker" in reason.lower()


# ── run() — passes and failures ───────────────────────────────────────


class TestRun:
    def test_passes_when_tables_match(self, tmp_path: Path) -> None:
        """When check_readme returns up-to-date, result is PASSED."""
        _write_readme(tmp_path, _readme_with_markers())
        check = StaleDocsCheck({})

        with patch(
            "slopmop.utils.readme_tables.check_readme",
            return_value=(True, "README gate tables are up to date"),
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert "up to date" in result.output

    def test_fails_when_tables_stale(self, tmp_path: Path) -> None:
        """When check_readme detects staleness, result is FAILED."""
        _write_readme(tmp_path, _readme_with_markers("outdated content"))
        check = StaleDocsCheck({})

        with patch(
            "slopmop.utils.readme_tables.check_readme",
            return_value=(
                False,
                "README gate tables are stale. Run:\n"
                "  python scripts/generate_readme_tables.py --update",
            ),
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert result.error is not None
        assert "stale" in result.error.lower()
        assert result.fix_suggestion is not None
        assert "generate_readme_tables" in result.fix_suggestion

    def test_result_has_duration(self, tmp_path: Path) -> None:
        """Result always includes a non-negative duration."""
        _write_readme(tmp_path, _readme_with_markers())
        check = StaleDocsCheck({})

        with patch(
            "slopmop.utils.readme_tables.check_readme",
            return_value=(True, "OK"),
        ):
            result = check.run(str(tmp_path))

        assert result.duration >= 0

    def test_result_name_matches_full_name(self, tmp_path: Path) -> None:
        """CheckResult.name should be the check's full_name."""
        _write_readme(tmp_path, _readme_with_markers())
        check = StaleDocsCheck({})

        with patch(
            "slopmop.utils.readme_tables.check_readme",
            return_value=(True, "OK"),
        ):
            result = check.run(str(tmp_path))

        assert result.name == "laziness:stale-docs"


# ── Integration with readme_tables utility ────────────────────────────


class TestReadmeTablesIntegration:
    """Tests that exercise the real check_readme path (no mocks)."""

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
        from slopmop.checks import ensure_checks_registered
        from slopmop.core.registry import get_registry
        from slopmop.utils.readme_tables import check_readme

        ensure_checks_registered()
        registry = get_registry()

        # Write README with wrong content between markers
        _write_readme(tmp_path, _readme_with_markers("| wrong | content |\n"))
        is_ok, msg = check_readme(tmp_path / "README.md", registry)
        assert is_ok is False
        assert "stale" in msg.lower()

    def test_matching_content_passes(self, tmp_path: Path) -> None:
        """check_readme returns True when content matches generated output."""
        from slopmop.checks import ensure_checks_registered
        from slopmop.core.registry import get_registry
        from slopmop.utils.readme_tables import (
            check_readme,
            generate_tables,
            splice_tables,
        )

        ensure_checks_registered()
        registry = get_registry()

        # Generate correct tables, write them, then check
        tables = generate_tables(registry)
        readme_text = _readme_with_markers()
        correct_readme = splice_tables(readme_text, tables)
        _write_readme(tmp_path, correct_readme)

        is_ok, msg = check_readme(tmp_path / "README.md", registry)
        assert is_ok is True


# ── Registration ──────────────────────────────────────────────────────


class TestRegistration:
    def test_registered_in_registry(self) -> None:
        """StaleDocsCheck should be discoverable via the registry."""
        import slopmop.checks as checks_mod
        from slopmop.core.registry import get_registry

        # Reset registration flag in case a prior test replaced the
        # global registry (e.g. test_registry.py).
        checks_mod._checks_registered = False
        checks_mod.ensure_checks_registered()
        registry = get_registry()
        assert "laziness:stale-docs" in registry._check_classes
