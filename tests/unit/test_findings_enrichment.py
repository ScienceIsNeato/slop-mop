"""Tests for the structured-findings enrichment layer.

These cover the glue between gate-internal data and SARIF output:
the ``_create_result`` auto-output rail, the extracted finding-builder
helpers in individual gates, and the JSON output builder that the
SARIF dispatch path shares.  All the targets here are pure functions
or static methods — no subprocess mocking required.
"""

import json
from typing import List, Optional, Tuple

import pytest

from slopmop.checks.quality.duplicate_strings import (
    StringDuplicationCheck,
    _first_relpath,
)
from slopmop.checks.quality.loc_lock import LocLockCheck
from slopmop.cli.validate import _build_json_output
from slopmop.core.result import (
    CheckResult,
    CheckStatus,
    ExecutionSummary,
    Finding,
)
from tests.unit.test_base_check import ConcreteCheck

# ─── _create_result auto-output rail ────────────────────────────────────


class TestCreateResultRail:
    """The rail: findings → output string when output not supplied.

    This is the mechanism that makes SARIF enrichment the *default*
    path rather than extra work.  A gate that supplies findings and
    nothing else gets a sensible console output for free.
    """

    def test_findings_populate_output_when_absent(self):
        """No output kwarg → output auto-built from Finding.__str__."""
        check = ConcreteCheck({})
        result = check._create_result(
            status=CheckStatus.FAILED,
            duration=0.0,
            findings=[
                Finding(message="unused import", file="src/a.py", line=5),
                Finding(message="shadowed builtin", file="src/b.py", line=12),
            ],
        )
        assert result.output == (
            "src/a.py:5: unused import\n" "src/b.py:12: shadowed builtin"
        )
        assert len(result.findings) == 2

    def test_explicit_output_wins_over_findings(self):
        """If a gate has a bespoke multi-section output, keep it."""
        check = ConcreteCheck({})
        result = check._create_result(
            status=CheckStatus.FAILED,
            duration=0.0,
            output="custom report with headers",
            findings=[Finding(message="x", file="y.py")],
        )
        assert result.output == "custom report with headers"

    def test_no_findings_leaves_output_empty(self):
        """The rail doesn't invent output from nothing."""
        check = ConcreteCheck({})
        result = check._create_result(status=CheckStatus.PASSED, duration=0.0)
        assert result.output == ""
        assert result.findings == []

    def test_findings_none_treated_as_empty(self):
        """`findings=None` is the default and must not crash the rail."""
        check = ConcreteCheck({})
        result = check._create_result(
            status=CheckStatus.PASSED, duration=0.0, findings=None
        )
        assert result.findings == []


# ─── duplicate_strings helpers ──────────────────────────────────────────


class TestFirstRelpath:
    """Path normalisation for the find-duplicate-strings anchor file."""

    def test_empty_list_returns_none(self):
        """No occurrences → no SARIF location, but still a valid Finding."""
        assert _first_relpath([]) is None

    def test_picks_first_and_relativises(self, tmp_path, monkeypatch):
        """Absolute path from the vendored tool → repo-relative."""
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "src" / "a.py"
        # No need to create the file — relpath is pure arithmetic.
        out = _first_relpath([str(target), str(tmp_path / "other.py")])
        assert out == str(target.relative_to(tmp_path))


class TestToFinding:
    """Mapping one find-duplicate-strings JSON entry → Finding."""

    def test_full_entry(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        entry = {
            "key": "DELETE FROM users WHERE id = ?",
            "count": 4,
            "fileCount": 3,
            "files": [str(tmp_path / "db.py")],
        }
        f = StringDuplicationCheck._to_finding(entry)
        assert "DELETE FROM users" in f.message
        assert "4×" in f.message and "3 files" in f.message
        assert f.file == "db.py"

    def test_long_key_truncated(self):
        """Overlong literals get an ellipsis, not a wall of text."""
        entry = {"key": "x" * 200, "count": 2, "fileCount": 1, "files": []}
        f = StringDuplicationCheck._to_finding(entry)
        assert f.message.count("x") < 200
        assert "..." in f.message
        assert f.file is None  # no files → locationless

    def test_sparse_entry_is_robust(self):
        """Missing keys from the tool JSON must not crash the mapper."""
        f = StringDuplicationCheck._to_finding({})
        # Defaults kick in: empty key, zero counts, no file.
        assert '""' in f.message  # empty preview still quoted
        assert "0×" in f.message
        assert f.file is None


# ─── loc_lock helpers ───────────────────────────────────────────────────


_FILE_VIOL: List[Tuple[str, int]] = [("big.py", 1200), ("medium.py", 850)]
_FUNC_VIOL: List[Tuple[str, str, int, int]] = [
    ("utils.py", "parse_everything", 40, 150),
    ("main.py", "run", 10, 120),
]


class TestLocLockFormatReport:
    """Human-readable violation summary."""

    def test_sorts_worst_first(self):
        out = LocLockCheck._format_report(_FILE_VIOL, _FUNC_VIOL, 500, 100)
        lines = out.splitlines()
        # big.py (1200) should precede medium.py (850)
        assert lines.index("  big.py: 1200 lines") < lines.index(
            "  medium.py: 850 lines"
        )
        # parse_everything (150) should precede run (120)
        func_lines = [ln for ln in lines if "()" in ln]
        assert "parse_everything" in func_lines[0]

    def test_both_sections_separated(self):
        out = LocLockCheck._format_report(_FILE_VIOL, _FUNC_VIOL, 500, 100)
        # Blank line between file section and func section
        assert "\n\n" in out

    def test_only_func_violations_no_leading_blank(self):
        out = LocLockCheck._format_report([], _FUNC_VIOL, 500, 100)
        assert not out.startswith("\n")
        assert "📁" not in out

    def test_caps_at_ten_with_ellipsis(self):
        many = [("f{}.py".format(i), 600 + i) for i in range(15)]
        out = LocLockCheck._format_report(many, [], 500, 100)
        assert "... and 5 more" in out


class TestLocLockToFindings:
    """Structured Finding mapping."""

    def test_file_violations_have_no_line_anchor(self):
        """The whole file is the problem — no line to point at."""
        findings = LocLockCheck._to_findings(_FILE_VIOL, [], 500, 100)
        assert all(f.line is None for f in findings)
        assert all(f.file is not None for f in findings)

    def test_func_violations_anchor_at_def_line(self):
        """GitHub's inline annotation lands on the signature."""
        findings = LocLockCheck._to_findings([], _FUNC_VIOL, 500, 100)
        anchors = {f.file: f.line for f in findings}
        assert anchors["utils.py"] == 40
        assert anchors["main.py"] == 10

    def test_mixed_violations_concatenated(self):
        findings = LocLockCheck._to_findings(_FILE_VIOL, _FUNC_VIOL, 500, 100)
        # 2 file-level + 2 func-level, file-level first
        assert len(findings) == 4
        assert findings[0].line is None
        assert findings[2].line is not None


# ─── _build_json_output ─────────────────────────────────────────────────


class _StubReporter:
    """Minimal ConsoleReporter stand-in.

    ``_build_json_output`` only touches ``.write_failure_log()``; the
    full reporter drags in terminal-width detection and colour codes
    we don't want in a unit test.
    """

    def __init__(self, log_path: Optional[str] = ".slopmop/logs/x.log"):
        self._log_path = log_path
        self.calls: List[CheckResult] = []

    def write_failure_log(self, result: CheckResult) -> Optional[str]:
        self.calls.append(result)
        return self._log_path


def _summary(*results: CheckResult) -> ExecutionSummary:
    return ExecutionSummary.from_results(list(results), 1.0)


class TestBuildJsonOutput:
    """The LLM-targeted JSON payload builder.

    Extracted from ``_run_validation`` so SARIF mode could share the
    output-dispatch branch.  Pure function of (summary, reporter, level).
    """

    def test_all_passed_has_no_next_steps(self):
        out = json.loads(
            _build_json_output(
                _summary(CheckResult("a:b", CheckStatus.PASSED, 1.0)),
                _StubReporter(),
                "swab",
            )
        )
        assert "next_steps" not in out
        assert out["schema"] == "slopmop/v1"
        assert out["level"] == "swab"

    def test_failed_gate_gets_log_file_attached(self):
        """Failures get a log path in the per-result dict."""
        fail = CheckResult(
            "laziness:x", CheckStatus.FAILED, 1.0, output="boom", error="e"
        )
        out = json.loads(_build_json_output(_summary(fail), _StubReporter(), "swab"))
        results = out["results"]
        assert len(results) == 1
        assert results[0]["log_file"] == ".slopmop/logs/x.log"

    def test_error_gate_also_gets_log_file(self):
        """ERROR status — same log treatment as FAILED."""
        err = CheckResult("a:b", CheckStatus.ERROR, 1.0, error="crashed")
        reporter = _StubReporter()
        json.loads(_build_json_output(_summary(err), reporter, None))
        assert len(reporter.calls) == 1
        assert reporter.calls[0].name == "a:b"

    def test_next_steps_point_at_first_failure(self):
        """The re-run hint targets the first failure, not all of them."""
        out = json.loads(
            _build_json_output(
                _summary(
                    CheckResult("a:pass", CheckStatus.PASSED, 1.0),
                    CheckResult("b:fail", CheckStatus.FAILED, 1.0, error="x"),
                    CheckResult("c:fail", CheckStatus.FAILED, 1.0, error="y"),
                ),
                _StubReporter(),
                "swab",
            )
        )
        assert out["next_steps"] == ["sm swab -g b:fail --verbose"]

    def test_error_is_next_step_fallback_when_no_failures(self):
        """No FAILED gates but an ERROR → still get a re-run hint."""
        out = json.loads(
            _build_json_output(
                _summary(CheckResult("a:err", CheckStatus.ERROR, 1.0, error="x")),
                _StubReporter(),
                "swab",
            )
        )
        assert "a:err" in out["next_steps"][0]

    def test_no_log_path_from_reporter_skips_attachment(self):
        """Reporter may return None (no project_root) — don't crash."""
        fail = CheckResult("a:b", CheckStatus.FAILED, 1.0, error="x")
        out = json.loads(
            _build_json_output(_summary(fail), _StubReporter(log_path=None), None)
        )
        # log_files dict stays empty → no attachment
        assert "log_file" not in out["results"][0]

    def test_no_level_name_omits_key(self):
        """Ad-hoc ``sm run -g ...`` invocations have no level."""
        out = json.loads(
            _build_json_output(
                _summary(CheckResult("a:b", CheckStatus.PASSED, 1.0)),
                _StubReporter(),
                None,
            )
        )
        assert "level" not in out

    def test_output_is_compact(self):
        """separators=(",", ":") — no whitespace padding, LLM-token-frugal."""
        raw = _build_json_output(
            _summary(CheckResult("a:b", CheckStatus.PASSED, 1.0)),
            _StubReporter(),
            "swab",
        )
        assert ": " not in raw
        assert ", " not in raw


# ─── smoke: SARIF CLI flags parse correctly ─────────────────────────────


class TestSarifCliFlags:
    """The ``--sarif`` and ``--output-file`` flags wire through argparse.

    This doesn't run validation — it just confirms the parser accepts
    the flags and they land on the namespace where ``_run_validation``
    expects them.  The actual dispatch is exercised end-to-end by the
    schema validation tests.
    """

    @pytest.fixture
    def parser(self):
        from slopmop.sm import create_parser

        return create_parser()

    def test_sarif_flag_defaults_off(self, parser):
        args = parser.parse_args(["scour"])
        assert getattr(args, "sarif_output", False) is False

    def test_sarif_flag_sets_true(self, parser):
        args = parser.parse_args(["scour", "--sarif"])
        assert args.sarif_output is True

    def test_output_file_captures_path(self, parser):
        args = parser.parse_args(["scour", "--sarif", "--output-file", "out.sarif"])
        assert args.output_file == "out.sarif"

    def test_output_file_works_with_json_too(self, parser):
        """``--output-file`` is format-agnostic — JSON gets it for free."""
        args = parser.parse_args(["swab", "--json", "--output-file", "out.json"])
        assert args.output_file == "out.json"

    def test_swab_also_has_sarif(self, parser):
        """Both validation levels support SARIF."""
        args = parser.parse_args(["swab", "--sarif"])
        assert args.sarif_output is True
