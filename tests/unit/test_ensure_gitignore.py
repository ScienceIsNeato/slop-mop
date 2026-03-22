"""Tests for slopmop.utils.ensure_slopmop_gitignored."""

from pathlib import Path

from slopmop.utils import ensure_slopmop_gitignored


def test_creates_gitignore_when_missing(tmp_path: Path) -> None:
    assert ensure_slopmop_gitignored(tmp_path) is True
    content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".slopmop/" in content


def test_appends_to_existing_gitignore(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("node_modules/\n", encoding="utf-8")
    assert ensure_slopmop_gitignored(tmp_path) is True
    content = gitignore.read_text(encoding="utf-8")
    assert "node_modules/" in content
    assert ".slopmop/" in content


def test_idempotent_when_already_present(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(".slopmop/\n", encoding="utf-8")
    assert ensure_slopmop_gitignored(tmp_path) is False
    # Content unchanged — no duplicate entry
    content = gitignore.read_text(encoding="utf-8")
    assert content.count(".slopmop/") == 1


def test_handles_entry_with_surrounding_whitespace(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("  .slopmop/  \n", encoding="utf-8")
    assert ensure_slopmop_gitignored(tmp_path) is False


def test_does_not_match_partial_entry(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("not-.slopmop/\n", encoding="utf-8")
    assert ensure_slopmop_gitignored(tmp_path) is True
    content = gitignore.read_text(encoding="utf-8")
    # Should have both the original and the new entry
    assert "not-.slopmop/" in content
    assert content.count(".slopmop/") == 2  # partial + real


def test_appends_newline_when_file_lacks_trailing_newline(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("*.pyc", encoding="utf-8")  # no trailing newline
    assert ensure_slopmop_gitignored(tmp_path) is True
    content = gitignore.read_text(encoding="utf-8")
    assert "*.pyc\n" in content
    assert ".slopmop/" in content


def test_includes_comment_in_new_gitignore(tmp_path: Path) -> None:
    ensure_slopmop_gitignored(tmp_path)
    content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "# slop-mop working directory" in content
