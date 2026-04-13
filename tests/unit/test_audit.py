"""Tests for slopmop.cli.audit — focusing on count/reporting correctness.

Three mismatch bugs motivate these tests:

1. ``_format_gate_section`` derived "passing" count from ``results`` only,
   but the scour JSON puts passing gates in ``passed_gates`` (not in
   ``results``).  The PASSING GATES section was always 0.

2. ``sm status`` RECENT HISTORY read from ``last_swab.json`` which only
   covers swab-level gates, so scour-only failures (dependency-risk,
   just-this-once) showed "Failed gates: 0" even when they were failing.

3. Same summary line in ``_format_gate_section`` uses ``summary.failed``
   from the scour JSON — that is correct — but the displayed gate list
   must match: len(failing) == summary["failed"].
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from slopmop.cli.audit import _format_gate_section

# Real git repo root — used by git-analysis tests
_REPO_ROOT = str(Path(__file__).parent.parent.parent)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_gate_data(
    *,
    passed: int = 0,
    failed: int = 0,
    warned: int = 0,
    not_applicable: int = 0,
    skipped: int = 0,
    passed_gates: Optional[List[str]] = None,
    failing_results: Optional[List[Dict[str, Any]]] = None,
    warned_results: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build a minimal gate-data dict that mirrors the scour JSON structure."""
    total = passed + failed + warned + not_applicable + skipped
    results: List[Dict[str, Any]] = []
    if failing_results:
        results.extend(failing_results)
    if warned_results:
        results.extend(warned_results)
    return {
        "summary": {
            "total_checks": total,
            "passed": passed,
            "failed": failed,
            "warned": warned,
            "not_applicable": not_applicable,
            "skipped": skipped,
            "errors": 0,
            "all_passed": failed == 0 and warned == 0,
            "total_duration": 10.0,
        },
        # Passing names live here, NOT in results
        "passed_gates": passed_gates or [],
        # Only non-passing entries appear in results
        "results": results,
    }


def _failing(name: str, error: str = "some issue") -> Dict[str, Any]:
    return {"name": name, "status": "failed", "error": error, "findings": []}


def _warned(name: str) -> Dict[str, Any]:
    return {"name": name, "status": "warned", "error": ""}


# ── Bug 1: passing count was always 0 because it read the wrong field ────────


class TestFormatGateSectionPassingCount:
    """``_format_gate_section`` must show the right number of passing gates."""

    def test_passing_gates_shown_from_passed_gates_field(self) -> None:
        """Regression: previously PASSING GATES section was always empty (0)
        because it filtered ``results`` for status="passed", but passing gates
        only appear in the top-level ``passed_gates`` list."""
        gate_data = _make_gate_data(
            passed=3,
            failed=0,
            passed_gates=[
                "myopia:ambiguity-mines.py",
                "laziness:dead-code.py",
                "overconfidence:coverage-gaps.py",
            ],
        )
        lines = _format_gate_section(gate_data)
        text = "\n".join(lines)

        assert "PASSING GATES (3)" in text, "Section header should say 3, not 0"
        assert "myopia:ambiguity-mines.py" in text
        assert "laziness:dead-code.py" in text

    def test_passing_count_matches_summary_passed(self) -> None:
        """The PASSING GATES header count must equal summary['passed']."""
        passed_names = [f"cat:gate-{i}" for i in range(5)]
        gate_data = _make_gate_data(passed=5, passed_gates=passed_names)
        lines = _format_gate_section(gate_data)
        text = "\n".join(lines)

        assert "PASSING GATES (5)" in text

    def test_no_passing_gates_section_when_none_passed(self) -> None:
        """When nothing passed, the PASSING GATES section must be absent."""
        gate_data = _make_gate_data(
            passed=0,
            failed=1,
            failing_results=[_failing("myopia:x")],
        )
        lines = _format_gate_section(gate_data)
        text = "\n".join(lines)

        assert "PASSING GATES" not in text


# ── Bug 2: summary line "failing" count matches the list actually shown ──────


class TestFormatGateSectionFailingCount:
    """Summary line ``failed`` and the FAILING GATES section must agree."""

    def test_summary_line_matches_failing_list(self) -> None:
        failing = [
            _failing("myopia:dependency-risk.py"),
            _failing("myopia:just-this-once.py"),
        ]
        gate_data = _make_gate_data(
            passed=18,
            failed=2,
            not_applicable=14,
            passed_gates=[f"cat:g{i}" for i in range(18)],
            failing_results=failing,
        )
        lines = _format_gate_section(gate_data)
        text = "\n".join(lines)

        # Summary line
        assert "2 failing" in text
        # Section header
        assert "FAILING GATES (2)" in text
        # Both gates present
        assert "myopia:dependency-risk.py" in text
        assert "myopia:just-this-once.py" in text

    def test_zero_failing_shows_no_failing_section(self) -> None:
        gate_data = _make_gate_data(
            passed=5, passed_gates=[f"c:g{i}" for i in range(5)]
        )
        lines = _format_gate_section(gate_data)
        text = "\n".join(lines)

        assert "FAILING GATES" not in text
        assert "0 failing" in text

    def test_warned_gates_not_counted_as_failing(self) -> None:
        """``warned`` status must not inflate the failed count or appear in
        the FAILING GATES section."""
        gate_data = _make_gate_data(
            passed=2,
            failed=0,
            warned=1,
            passed_gates=["a:x", "b:y"],
            warned_results=[_warned("myopia:ignored-feedback")],
        )
        lines = _format_gate_section(gate_data)
        text = "\n".join(lines)

        assert "FAILING GATES" not in text
        # warned gate may appear in a separate section but not as failing
        assert "0 failing" in text


# ── Bug 3: gate_data=None renders a graceful fallback, not a crash ───────────


class TestFormatGateSectionNoneInput:
    def test_none_gate_data_renders_fallback(self) -> None:
        lines = _format_gate_section(None)
        text = "\n".join(lines)
        # Should not raise and should mention the issue
        assert "gate scan failed" in text.lower() or "check" in text.lower()


# ── Git helper unit tests ─────────────────────────────────────────────────────


class TestRunGitCmd:
    def test_returns_zero_and_output_for_valid_cmd(self) -> None:
        from slopmop.cli.audit import _run_git_cmd

        rc, output = _run_git_cmd(["rev-parse", "--is-inside-work-tree"], _REPO_ROOT)
        assert rc == 0
        assert "true" in output.lower()

    def test_returns_nonzero_for_bad_ref(self) -> None:
        from slopmop.cli.audit import _run_git_cmd

        rc, _ = _run_git_cmd(
            ["rev-parse", "nonexistent-ref-xyz-never-exists"], _REPO_ROOT
        )
        assert rc != 0

    def test_returns_one_and_empty_string_on_os_error(self) -> None:
        """When git is not installed, _run_git_cmd must not raise."""
        from slopmop.cli.audit import _run_git_cmd

        with patch("slopmop.cli.audit.subprocess.run", side_effect=OSError("no git")):
            rc, output = _run_git_cmd(["rev-parse", "HEAD"], _REPO_ROOT)
        assert rc == 1
        assert output == ""


class TestIsGitRepo:
    def test_git_repo_returns_true(self) -> None:
        from slopmop.cli.audit import _is_git_repo

        assert _is_git_repo(_REPO_ROOT)

    def test_non_git_dir_returns_false(self, tmp_path: Path) -> None:
        from slopmop.cli.audit import _is_git_repo

        assert not _is_git_repo(str(tmp_path))


class TestPureGitHelpers:
    """Tests for pure helper functions that do not need a real git repo."""

    def test_cross_reference_empty_inputs(self) -> None:
        from slopmop.cli.audit import _cross_reference

        assert _cross_reference([], []) == []

    def test_cross_reference_no_overlap(self) -> None:
        from slopmop.cli.audit import _cross_reference

        churn = [(10, "a.py"), (5, "b.py")]
        bugs = [(3, "c.py")]
        assert _cross_reference(churn, bugs) == []

    def test_cross_reference_with_overlap(self) -> None:
        from slopmop.cli.audit import _cross_reference

        churn = [(10, "a.py"), (5, "b.py")]
        bugs = [(3, "a.py"), (1, "b.py")]
        result = _cross_reference(churn, bugs)
        paths = [p for p, _, _ in result]
        assert "a.py" in paths
        assert "b.py" in paths

    def test_cross_reference_sorted_by_combined_count(self) -> None:
        from slopmop.cli.audit import _cross_reference

        # a.py: churn=10, bugs=1 → 11; b.py: churn=2, bugs=8 → 10
        churn = [(10, "a.py"), (2, "b.py")]
        bugs = [(1, "a.py"), (8, "b.py")]
        result = _cross_reference(churn, bugs)
        assert result[0][0] == "a.py"


class TestGitAnalysisHelpers:
    """Exercise the git helpers against the real slop-mop repository."""

    def test_churn_hotspots_returns_sorted_list(self) -> None:
        from slopmop.cli.audit import _churn_hotspots

        hotspots = _churn_hotspots(_REPO_ROOT, since="2 years ago", top_n=5)
        assert isinstance(hotspots, list)
        if len(hotspots) >= 2:
            assert hotspots[0][0] >= hotspots[1][0]

    def test_bug_commits_returns_list(self) -> None:
        from slopmop.cli.audit import _bug_commits

        result = _bug_commits(_REPO_ROOT, top_n=10)
        assert isinstance(result, list)

    def test_contributors_returns_sorted_by_count(self) -> None:
        from slopmop.cli.audit import _contributors

        result = _contributors(_REPO_ROOT)
        assert isinstance(result, list)
        # May be empty in some git environments (shallow clone, etc.)
        if len(result) >= 2:
            assert result[0][0] >= result[1][0]

    def test_contributors_recent_returns_list(self) -> None:
        from slopmop.cli.audit import _contributors_recent

        result = _contributors_recent(_REPO_ROOT, since="1 year ago")
        assert isinstance(result, list)

    def test_velocity_by_month_oldest_first(self) -> None:
        from slopmop.cli.audit import _velocity_by_month

        result = _velocity_by_month(_REPO_ROOT)
        assert isinstance(result, list)
        if len(result) >= 2:
            assert result[0][1] <= result[-1][1]

    def test_firefighting_returns_list(self) -> None:
        from slopmop.cli.audit import _firefighting

        result = _firefighting(_REPO_ROOT, since="1 year ago")
        assert isinstance(result, list)


class TestFormatGitSection:
    """_format_git_section against the real git repo covers most of the
    git-analytics code path."""

    def test_produces_expected_sections(self) -> None:
        from slopmop.cli.audit import _format_git_section

        lines = _format_git_section(_REPO_ROOT, since="2 years ago", top_n=5)
        text = "\n".join(lines)
        assert "WHO BUILT THIS" in text
        assert "MOST CHANGED" in text
        assert "COMMIT VELOCITY" in text
        assert "FIREFIGHTING" in text

    def test_non_git_dir_shows_skip_message(self, tmp_path: Path) -> None:
        from slopmop.cli.audit import _format_git_section

        lines = _format_git_section(str(tmp_path), since="1 year ago", top_n=5)
        text = "\n".join(lines)
        assert "not a git repository" in text


class TestRunGateInventory:
    """_run_gate_inventory with mocked subprocess."""

    def test_returns_parsed_json_when_artifact_created(self, tmp_path: Path) -> None:
        from slopmop.cli.audit import _run_gate_inventory

        fake_data: Dict[str, Any] = {"summary": {"total_checks": 3, "passed": 3}}
        artifact = tmp_path / ".slopmop" / "audit-gate-inventory.json"

        def _write_artifact(*_args: Any, **_kwargs: Any) -> None:
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(json.dumps(fake_data), encoding="utf-8")

        with patch("slopmop.cli.audit.subprocess.run", side_effect=_write_artifact):
            result = _run_gate_inventory(tmp_path, quiet=True)

        assert result == fake_data

    def test_returns_none_when_no_artifact(self, tmp_path: Path) -> None:
        from slopmop.cli.audit import _run_gate_inventory

        with patch("slopmop.cli.audit.subprocess.run"):
            result = _run_gate_inventory(tmp_path, quiet=True)
        assert result is None

    def test_quiet_adds_quiet_flag_to_command(self, tmp_path: Path) -> None:
        from slopmop.cli.audit import _run_gate_inventory

        calls: List[Any] = []

        def _capture(*args: Any, **kwargs: Any) -> None:
            calls.append(args[0])

        with patch("slopmop.cli.audit.subprocess.run", side_effect=_capture):
            _run_gate_inventory(tmp_path, quiet=True)

        assert calls and "--quiet" in calls[0]

    def test_non_quiet_omits_quiet_flag(self, tmp_path: Path) -> None:
        from slopmop.cli.audit import _run_gate_inventory

        calls: List[Any] = []

        def _capture(*args: Any, **kwargs: Any) -> None:
            calls.append(args[0])

        with patch("slopmop.cli.audit.subprocess.run", side_effect=_capture):
            _run_gate_inventory(tmp_path, quiet=False)

        assert calls and "--quiet" not in calls[0]

    def test_returns_none_on_invalid_json(self, tmp_path: Path) -> None:
        from slopmop.cli.audit import _run_gate_inventory

        artifact = tmp_path / ".slopmop" / "audit-gate-inventory.json"

        def _write_bad(*_args: Any, **_kwargs: Any) -> None:
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("not json!!", encoding="utf-8")

        with patch("slopmop.cli.audit.subprocess.run", side_effect=_write_bad):
            result = _run_gate_inventory(tmp_path, quiet=True)

        assert result is None


class TestBuildReport:
    def test_contains_header_and_informational_note(self) -> None:
        from slopmop.cli.audit import _build_report

        report = _build_report(
            project_root=_REPO_ROOT,
            since="1 year ago",
            top_n=5,
            include_git=False,
            include_gates=False,
            gate_data=None,
            timestamp="2026-04-12T00:00:00Z",
        )
        assert "slop-mop audit report" in report
        assert "informational" in report

    def test_with_gate_data(self) -> None:
        from slopmop.cli.audit import _build_report

        gate_data = _make_gate_data(passed=2, passed_gates=["a:x", "b:y"])
        report = _build_report(
            project_root=_REPO_ROOT,
            since="1 year ago",
            top_n=5,
            include_git=False,
            include_gates=True,
            gate_data=gate_data,
            timestamp="2026-04-12T00:00:00Z",
        )
        assert "GATE VIOLATION INVENTORY" in report
        assert "PASSING GATES (2)" in report

    def test_with_git_analytics(self) -> None:
        from slopmop.cli.audit import _build_report

        report = _build_report(
            project_root=_REPO_ROOT,
            since="1 year ago",
            top_n=5,
            include_git=True,
            include_gates=False,
            gate_data=None,
            timestamp="2026-04-12T00:00:00Z",
        )
        assert "GIT ANALYTICS" in report


class TestBuildJsonPayload:
    def test_schema_and_project_root_present(self) -> None:
        from slopmop.cli.audit import _build_json_payload

        payload = _build_json_payload(
            project_root=_REPO_ROOT,
            since="1 year ago",
            top_n=5,
            include_git=False,
            include_gates=False,
            gate_data=None,
            timestamp="2026-04-12T00:00:00Z",
        )
        assert payload["schema"] == "slopmop/audit/v1"
        assert "project_root" in payload

    def test_gates_key_present_when_include_gates(self) -> None:
        from slopmop.cli.audit import _build_json_payload

        gate_data = _make_gate_data(passed=1, passed_gates=["a:x"])
        payload = _build_json_payload(
            project_root=_REPO_ROOT,
            since="1 year ago",
            top_n=5,
            include_git=False,
            include_gates=True,
            gate_data=gate_data,
            timestamp="2026-04-12T00:00:00Z",
        )
        assert "gates" in payload

    def test_git_key_present_when_include_git(self) -> None:
        from slopmop.cli.audit import _build_json_payload

        payload = _build_json_payload(
            project_root=_REPO_ROOT,
            since="1 year ago",
            top_n=3,
            include_git=True,
            include_gates=False,
            gate_data=None,
            timestamp="2026-04-12T00:00:00Z",
        )
        assert "git" in payload
        assert "contributors_all_time" in payload["git"]


class TestCmdAudit:
    def test_json_mode_produces_valid_schema(self, tmp_path: Path) -> None:
        import io

        from slopmop.cli.audit import _DEFAULT_OUTPUT, cmd_audit

        args = argparse.Namespace(
            project_root=str(tmp_path),
            since="1 year ago",
            top=5,
            no_git=True,
            no_gates=True,
            output=None,
            json_output=True,
            quiet=False,
        )
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            ret = cmd_audit(args)
        assert ret == 0
        payload = json.loads(buf.getvalue())
        assert payload["schema"] == "slopmop/audit/v1"
        # report file should still be written even in json_output mode
        assert (tmp_path / _DEFAULT_OUTPUT).exists()

    def test_writes_report_file_in_quiet_mode(self, tmp_path: Path) -> None:
        """In quiet mode, no stdout output, but the report file is still written."""

        from slopmop.cli.audit import cmd_audit

        out_path = tmp_path / "report.md"
        # isatty() must return True so that json_mode evaluates to False
        fake_tty: MagicMock = MagicMock()
        fake_tty.isatty.return_value = True
        args = argparse.Namespace(
            project_root=str(tmp_path),
            since="1 year ago",
            top=5,
            no_git=True,
            no_gates=True,
            output=str(out_path),
            json_output=False,
            quiet=True,
        )
        with patch("sys.stdout", fake_tty), patch("sys.stderr", fake_tty):
            ret = cmd_audit(args)
        assert ret == 0
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert "slop-mop audit report" in content

    def test_non_quiet_prints_report_to_stdout(self, tmp_path: Path) -> None:
        """Non-quiet, non-json mode prints the report to stdout."""
        import io

        from slopmop.cli.audit import cmd_audit

        buf = io.StringIO()
        buf.isatty = lambda: True  # type: ignore[attr-defined]
        stderr_buf = io.StringIO()
        stderr_buf.isatty = lambda: True  # type: ignore[attr-defined]
        args = argparse.Namespace(
            project_root=str(tmp_path),
            since="1 year ago",
            top=5,
            no_git=True,
            no_gates=True,
            output=str(tmp_path / "report.md"),
            json_output=False,
            quiet=False,
        )
        with patch("sys.stdout", buf), patch("sys.stderr", stderr_buf):
            ret = cmd_audit(args)
        assert ret == 0
        assert "slop-mop audit report" in buf.getvalue()

    def test_default_output_path_used_when_no_output_arg(self, tmp_path: Path) -> None:
        """When output=None, the report is written to the default .slopmop path."""

        from slopmop.cli.audit import _DEFAULT_OUTPUT, cmd_audit

        fake_tty: MagicMock = MagicMock()
        fake_tty.isatty.return_value = True
        args = argparse.Namespace(
            project_root=str(tmp_path),
            since="1 year ago",
            top=5,
            no_git=True,
            no_gates=True,
            output=None,
            json_output=False,
            quiet=True,
        )
        with patch("sys.stdout", fake_tty), patch("sys.stderr", fake_tty):
            ret = cmd_audit(args)
        assert ret == 0
        default_out = tmp_path / _DEFAULT_OUTPUT
        assert default_out.exists()
