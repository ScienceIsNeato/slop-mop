"""Tests for collapsing findings across byte-identical file copies.

Repos that distribute templates or vendor a tool contain identical copies of
the same source file, so every gate reports the same defect once per copy.
botingw/rulebook-ai ships 7 identical copies of tool_starters/llm_api.py,
which turned 1 unused import into 5 findings and 1 oversized function into 7.
"""

from __future__ import annotations

from slopmop.checks.duplicate_files import collapse_duplicate_file_findings
from slopmop.core.result import Finding, FindingLevel


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return str(rel)


class TestCollapseDuplicateFileFindings:
    def test_identical_copies_collapse_to_one(self, tmp_path):
        body = "import os\nfrom typing import Union\n"
        a = _write(tmp_path, "tools/llm_api.py", body)
        b = _write(tmp_path, "packs/light/tools/llm_api.py", body)
        c = _write(tmp_path, "vendor/x/tools/llm_api.py", body)
        findings = [
            Finding(message="unused import 'Union'", file=f, line=2) for f in (a, b, c)
        ]

        out, collapsed = collapse_duplicate_file_findings(findings, str(tmp_path))

        assert collapsed == 2
        assert len(out) == 1
        # Survivor is the shortest (most canonical) path.
        assert out[0].file == "tools/llm_api.py"
        assert "2 identical copies" in out[0].message
        assert "unused import 'Union'" in out[0].message

    def test_diverged_copies_are_not_merged(self, tmp_path):
        a = _write(tmp_path, "a/mod.py", "x = 1\n")
        b = _write(tmp_path, "b/mod.py", "x = 2\n")  # one byte different
        findings = [
            Finding(message="same message", file=a, line=1),
            Finding(message="same message", file=b, line=1),
        ]

        out, collapsed = collapse_duplicate_file_findings(findings, str(tmp_path))

        assert collapsed == 0
        assert len(out) == 2

    def test_different_issues_in_same_copies_stay_separate(self, tmp_path):
        body = "import os\nimport sys\n"
        a = _write(tmp_path, "a/mod.py", body)
        b = _write(tmp_path, "b/mod.py", body)
        findings = [
            Finding(message="unused 'os'", file=a, line=1),
            Finding(message="unused 'sys'", file=a, line=2),
            Finding(message="unused 'os'", file=b, line=1),
            Finding(message="unused 'sys'", file=b, line=2),
        ]

        out, collapsed = collapse_duplicate_file_findings(findings, str(tmp_path))

        assert collapsed == 2
        assert {f.line for f in out} == {1, 2}
        assert len(out) == 2

    def test_same_line_different_message_not_merged(self, tmp_path):
        body = "x = 1\n"
        a = _write(tmp_path, "a/mod.py", body)
        b = _write(tmp_path, "b/mod.py", body)
        findings = [
            Finding(message="issue A", file=a, line=1),
            Finding(message="issue B", file=b, line=1),
        ]

        out, collapsed = collapse_duplicate_file_findings(findings, str(tmp_path))

        assert collapsed == 0
        assert len(out) == 2

    def test_findings_without_files_pass_through(self, tmp_path):
        findings = [
            Finding(message="no location", level=FindingLevel.ERROR),
            Finding(message="also none", level=FindingLevel.WARNING),
        ]

        out, collapsed = collapse_duplicate_file_findings(findings, str(tmp_path))

        assert collapsed == 0
        assert len(out) == 2

    def test_missing_file_is_never_merged(self, tmp_path):
        findings = [
            Finding(message="gone", file="does/not/exist.py", line=1),
            Finding(message="gone", file="also/missing.py", line=1),
        ]

        out, collapsed = collapse_duplicate_file_findings(findings, str(tmp_path))

        assert collapsed == 0
        assert len(out) == 2

    def test_survivor_preserves_metadata(self, tmp_path):
        body = "x = 1\n"
        a = _write(tmp_path, "a/mod.py", body)
        b = _write(tmp_path, "bb/mod.py", body)
        findings = [
            Finding(
                message="boom",
                file=a,
                line=1,
                column=3,
                rule_id="R123",
                fix_strategy="do the thing",
                level=FindingLevel.WARNING,
            ),
            Finding(message="boom", file=b, line=1, level=FindingLevel.WARNING),
        ]

        out, collapsed = collapse_duplicate_file_findings(findings, str(tmp_path))

        assert collapsed == 1
        (survivor,) = out
        assert survivor.rule_id == "R123"
        assert survivor.fix_strategy == "do the thing"
        assert survivor.column == 3
        assert survivor.level is FindingLevel.WARNING

    def test_single_finding_is_untouched(self, tmp_path):
        a = _write(tmp_path, "a/mod.py", "x = 1\n")
        findings = [Finding(message="solo", file=a, line=1)]

        out, collapsed = collapse_duplicate_file_findings(findings, str(tmp_path))

        assert collapsed == 0
        assert out[0].message == "solo"  # no "[also in ...]" suffix

    def test_oversized_files_are_never_hashed(self, tmp_path, monkeypatch):
        """A huge duplicate asset isn't what this is for — skip, don't merge."""
        import slopmop.checks.duplicate_files as mod

        monkeypatch.setattr(mod, "_MAX_HASH_BYTES", 4)
        body = "this is longer than four bytes\n"
        a = _write(tmp_path, "a/big.py", body)
        b = _write(tmp_path, "b/big.py", body)
        findings = [
            Finding(message="same", file=a, line=1),
            Finding(message="same", file=b, line=1),
        ]

        out, collapsed = collapse_duplicate_file_findings(findings, str(tmp_path))

        assert collapsed == 0
        assert len(out) == 2

    def test_absolute_paths_resolve(self, tmp_path):
        body = "x = 1\n"
        _write(tmp_path, "a/mod.py", body)
        _write(tmp_path, "b/mod.py", body)
        findings = [
            Finding(message="same", file=str(tmp_path / "a" / "mod.py"), line=1),
            Finding(message="same", file=str(tmp_path / "b" / "mod.py"), line=1),
        ]

        out, collapsed = collapse_duplicate_file_findings(findings, str(tmp_path))

        assert collapsed == 1
        assert len(out) == 1
