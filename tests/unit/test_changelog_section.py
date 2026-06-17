"""Tests for scripts/changelog_section.py (release-notes extraction)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "changelog_section",
    Path(__file__).resolve().parents[2] / "scripts" / "changelog_section.py",
)
assert _SPEC and _SPEC.loader
changelog_section = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(changelog_section)

extract_section = changelog_section.extract_section
main = changelog_section.main

SAMPLE = """# Changelog

## 2.6.0

### New gates
- thing one
- thing two

## 2.5.0

- older stuff
"""


class TestExtractSection:
    def test_extracts_named_version(self):
        body = extract_section(SAMPLE, "2.6.0")
        assert body is not None
        assert "thing one" in body and "thing two" in body
        assert "older stuff" not in body  # stops at the next ## heading

    def test_extracts_bracketed_version(self):
        body = extract_section("## [1.2.3]\n\n- notes\n", "1.2.3")
        assert body == "- notes"

    def test_missing_version_returns_none(self):
        assert extract_section(SAMPLE, "9.9.9") is None

    def test_empty_section_counts_as_missing(self):
        text = "## 2.6.0\n\n## 2.5.0\n- x\n"
        assert extract_section(text, "2.6.0") is None

    def test_partial_version_does_not_match(self):
        # "2.6" must not match the "2.6.0" heading
        assert extract_section(SAMPLE, "2.6") is None


class TestCli:
    def test_exit_zero_and_prints_section(self, tmp_path, capsys):
        cl = tmp_path / "CHANGELOG.md"
        cl.write_text(SAMPLE)
        rc = main(["2.6.0", "--changelog", str(cl)])
        assert rc == 0
        assert "thing one" in capsys.readouterr().out

    def test_exit_nonzero_when_missing(self, tmp_path, capsys):
        cl = tmp_path / "CHANGELOG.md"
        cl.write_text(SAMPLE)
        rc = main(["9.9.9", "--changelog", str(cl)])
        assert rc == 1
        assert "No release notes for 9.9.9" in capsys.readouterr().err

    def test_exit_nonzero_when_changelog_absent(self, tmp_path, capsys):
        rc = main(["2.6.0", "--changelog", str(tmp_path / "nope.md")])
        assert rc == 1
        assert "not found" in capsys.readouterr().err

    def test_real_changelog_has_current_release_section(self):
        # the committed CHANGELOG.md must carry notes for 2.6.0
        repo_changelog = Path(__file__).resolve().parents[2] / "CHANGELOG.md"
        rc = main(["2.6.0", "--changelog", str(repo_changelog)])
        assert rc == 0
