"""Unit tests for CI triage rail helpers."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from slopmop.cli import ci as ci_mod
from slopmop.cli import scan_triage as triage
from slopmop.reporting import rail


class TestRailHelpers:
    def test_actionable_detail_precedence(self):
        row = {
            "error": "err",
            "fix_suggestion": "fix",
            "status_detail": "detail",
        }
        assert rail.actionable_detail(row) == "err"

        row = {"fix_suggestion": "fix", "status_detail": "detail"}
        assert rail.actionable_detail(row) == "fix"

        row = {"status_detail": "detail"}
        assert rail.actionable_detail(row) == "detail"

        assert rail.actionable_detail({}) == "(no detail)"

    def test_filters_and_normalization(self):
        rows = [
            {"status": "failed", "name": "g1", "error": "e1"},
            {"status": "warned", "name": "g2", "status_detail": "d2"},
            {"status": "passed", "name": "g3"},
            {"status": "error", "name": "g4", "fix_suggestion": "f4"},
        ]

        actionable = rail.filter_actionable_rows(rows)
        assert [r["name"] for r in actionable] == ["g1", "g2", "g4"]

        hard = rail.filter_hard_failures(actionable)
        assert [r["name"] for r in hard] == ["g1", "g4"]

        normalized = rail.normalize_actionable_row(rows[0])
        assert normalized == {"status": "FAILED", "gate": "g1", "detail": "e1"}
        assert rail.format_actionable_line(normalized) == "- FAILED: g1 :: e1"

    def test_sort_rows_by_remediation_order_preserves_unknown_order(self):
        rows = [
            {"status": "failed", "name": "unknown-b"},
            {"status": "failed", "name": "unknown-a"},
        ]

        assert [r["name"] for r in rail.sort_rows_by_remediation_order(rows)] == [
            "unknown-b",
            "unknown-a",
        ]

    def test_default_next_steps(self):
        with_pr = rail.default_next_steps(84)
        assert with_pr[-1] == "Re-run PR inspection: sm buff inspect 84"
        assert with_pr[1] == (
            "If fixes take multiple passes, loop on sm swab until local issues are stable"
        )
        assert with_pr[2] == "Run full validation locally: sm scour"

        no_pr = rail.default_next_steps(None)
        assert no_pr[-1] == "Re-run PR inspection: sm buff inspect"


class TestCiHelpers:
    def test_detect_pr_number_filters_to_open_prs(self, tmp_path, monkeypatch):
        runner = Mock(
            side_effect=[
                SimpleNamespace(returncode=0, stdout="feat-branch\n"),
                SimpleNamespace(returncode=0, stdout=json.dumps([{"number": 42}])),
            ]
        )
        monkeypatch.setattr(ci_mod.subprocess, "run", runner)

        assert ci_mod._detect_pr_number(tmp_path) == 42
        gh_args = runner.call_args_list[1].args[0]
        assert gh_args == [
            "gh",
            "pr",
            "list",
            "--head",
            "feat-branch",
            "--state",
            "open",
            "--json",
            "number",
            "--limit",
            "1",
        ]


class TestScanTriageInternals:
    def test_run_helpers_error_paths(self, monkeypatch):
        def fail_run(*_args, **_kwargs):
            return SimpleNamespace(returncode=1, stderr="boom", stdout="")

        monkeypatch.setattr(triage.subprocess, "run", fail_run)

        with pytest.raises(triage.TriageError):
            triage._run_gh(["repo", "view"])

        with pytest.raises(triage.TriageError):
            triage._run_local(["git", "status"])

    def test_default_repo_and_current_pr(self, monkeypatch):
        monkeypatch.setattr(
            triage,
            "_run_gh",
            Mock(return_value=json.dumps({"nameWithOwner": "o/r"})),
        )
        assert triage.default_repo() == "o/r"

        def fake_local(_cmd):
            return "feat-branch\n"

        def fake_gh(_cmd):
            return json.dumps([{"number": 42}])

        monkeypatch.setattr(triage, "_run_local", fake_local)
        monkeypatch.setattr(triage, "_run_gh", fake_gh)
        assert triage.current_pr_number("o/r") == 42

    def test_current_pr_errors(self, monkeypatch):
        monkeypatch.setattr(triage, "_run_local", Mock(return_value="\n"))
        with pytest.raises(triage.TriageError):
            triage.current_pr_number("o/r")

        monkeypatch.setattr(triage, "_run_local", Mock(return_value="branch\n"))
        monkeypatch.setattr(triage, "_run_gh", Mock(return_value="[]"))
        with pytest.raises(triage.TriageError):
            triage.current_pr_number("o/r")

    def test_latest_completed_run_id(self, monkeypatch):
        responses = [
            json.dumps({"headRefName": "feat-x"}),
            json.dumps(
                [
                    {
                        "name": "other workflow",
                        "status": "completed",
                        "databaseId": 1,
                    },
                    {
                        "name": "slop-mop primary code scanning gate",
                        "status": "completed",
                        "databaseId": 321,
                    },
                ]
            ),
        ]

        monkeypatch.setattr(triage, "_run_gh", lambda _cmd: responses.pop(0))
        assert triage.latest_completed_run_id("o/r", 84, triage.WORKFLOW_NAME) == 321

    def test_workflow_run_state_prefers_latest_completed(self, monkeypatch):
        responses = [
            json.dumps({"headRefName": "feat-x"}),
            json.dumps(
                [
                    {
                        "name": "slop-mop primary code scanning gate",
                        "status": "in_progress",
                        "databaseId": 500,
                    },
                    {
                        "name": "slop-mop primary code scanning gate",
                        "status": "completed",
                        "databaseId": 499,
                    },
                ]
            ),
        ]

        monkeypatch.setattr(triage, "_run_gh", lambda _cmd: responses.pop(0))
        state = triage._workflow_run_state("o/r", 84, triage.WORKFLOW_NAME)
        assert state["latest"]["databaseId"] == 500
        assert state["latest_completed"]["databaseId"] == 499

    def test_latest_completed_run_id_error(self, monkeypatch):
        responses = [
            json.dumps({"headRefName": "feat-x"}),
            json.dumps([]),
        ]

        monkeypatch.setattr(triage, "_run_gh", lambda _cmd: responses.pop(0))
        with pytest.raises(triage.TriageError):
            triage.latest_completed_run_id("o/r", 84, triage.WORKFLOW_NAME)

    def test_validate_open_pr_rejects_closed_pr(self, monkeypatch):
        monkeypatch.setattr(
            triage,
            "_run_gh",
            Mock(return_value=json.dumps({"number": 85, "state": "CLOSED"})),
        )

        with pytest.raises(triage.TriageError, match="is not open"):
            triage.validate_open_pr("o/r", 85)

    def test_resolve_pr_number_prefers_open_branch_pr(self, monkeypatch):
        monkeypatch.setattr(triage, "current_pr_number", Mock(return_value=84))
        monkeypatch.setattr(triage, "get_current_pr_number", Mock(return_value=85))
        validator = Mock(return_value=85)
        monkeypatch.setattr(triage, "validate_open_pr", validator)

        assert triage.resolve_pr_number("o/r", None) == 84
        validator.assert_not_called()

    def test_resolve_pr_number_falls_back_to_selected_pr_when_branch_lookup_fails(
        self, monkeypatch
    ):
        root = "/repo"
        monkeypatch.setattr(
            triage,
            "current_pr_number",
            Mock(side_effect=triage.TriageError("no open PR for branch")),
        )
        monkeypatch.setattr(triage, "_resolve_project_root", Mock(return_value=root))
        selected_pr = Mock(return_value=85)
        validator = Mock(return_value=85)
        monkeypatch.setattr(triage, "get_current_pr_number", selected_pr)
        monkeypatch.setattr(triage, "validate_open_pr", validator)

        assert triage.resolve_pr_number("o/r", None) == 85
        selected_pr.assert_called_once_with(root)
        validator.assert_called_once_with("o/r", 85)

    def test_resolve_pr_number_reports_stale_selected_pr(self, monkeypatch):
        monkeypatch.setattr(
            triage,
            "current_pr_number",
            Mock(side_effect=triage.TriageError("no open PR for branch")),
        )
        monkeypatch.setattr(triage, "_resolve_project_root", Mock(return_value="/repo"))
        monkeypatch.setattr(triage, "get_current_pr_number", Mock(return_value=92))
        monkeypatch.setattr(
            triage,
            "validate_open_pr",
            Mock(side_effect=triage.TriageError("PR #92 is not open (state=merged).")),
        )

        with pytest.raises(
            triage.TriageError, match="Selected working PR #92 is stale"
        ):
            triage.resolve_pr_number("o/r", None)

    def test_load_json_and_coverage_value(self, tmp_path):
        path = tmp_path / "ok.json"
        path.write_text('{"k": 1}', encoding="utf-8")
        assert triage._load_json(path) == {"k": 1}

        bad = tmp_path / "bad.json"
        bad.write_text("[]", encoding="utf-8")
        with pytest.raises(triage.TriageError):
            triage._load_json(bad)

        assert triage._coverage_value("Coverage 78.7% on changed lines") == 78.7
        assert triage._coverage_value("no percent here") is None

    def test_build_payload_and_print(self, capsys):
        doc = {
            "summary": {"failed": 1, "errors": 0, "warned": 1, "all_passed": False},
            "results": [
                {
                    "status": "failed",
                    "name": "myopia:just-this-once.py",
                    "error": "Changed files have <80% coverage",
                    "findings": [
                        {
                            "file": "slopmop/cli/buff.py",
                            "message": "Coverage 62.5% on changed lines",
                        }
                    ],
                },
                {
                    "status": "warned",
                    "name": "myopia:ignored-feedback",
                    "status_detail": "2 unresolved",
                },
                {"status": "passed", "name": "ok"},
            ],
        }

        payload, code = triage.build_triage_payload(
            doc=doc,
            run_id=999,
            json_path=Path(".slopmop/last_ci_scan_results.json"),
            show_low_coverage=True,
            pr_number=84,
            ci_state={
                "latest_run_id": 1001,
                "latest_status": "in_progress",
                "triaged_run_id": 999,
                "note": "Using latest completed run while newer run is in progress.",
            },
        )
        assert code == 1
        assert payload["schema"] == "slopmop/ci-triage/v1"
        assert payload["next_steps"][2] == "Run full validation locally: sm scour"
        assert len(payload["actionable"]) == 2
        assert payload["actionable"][0]["gate"] == "myopia:just-this-once.py"
        assert payload["first_to_fix"]["gate"] == "myopia:just-this-once.py"
        assert payload["lowest_coverage"][0]["coverage_pct"] == 62.5
        assert payload["ci_state"]["latest_status"] == "in_progress"

        triage.print_triage(payload, show_low_coverage=True)
        out = capsys.readouterr().out
        assert "Fix First: myopia:just-this-once.py" in out

    def test_build_payload_sorts_actionable_rows_by_remediation_order(self):
        doc = {
            "summary": {"failed": 2, "errors": 0, "warned": 0, "all_passed": False},
            "results": [
                {
                    "status": "failed",
                    "name": "laziness:sloppy-formatting.py",
                    "error": "fmt",
                },
                {
                    "status": "failed",
                    "name": "myopia:source-duplication",
                    "error": "dup",
                },
            ],
        }

        payload, code = triage.build_triage_payload(
            doc=doc,
            run_id=999,
            json_path=Path(".slopmop/last_ci_scan_results.json"),
            show_low_coverage=False,
            pr_number=84,
        )

        assert code == 1
        assert [row["gate"] for row in payload["actionable"]] == [
            "myopia:source-duplication",
            "laziness:sloppy-formatting.py",
        ]
        assert payload["first_to_fix"]["gate"] == "myopia:source-duplication"

    def test_write_json_out(self, tmp_path):
        target = tmp_path / "triage.json"
        triage.write_json_out(str(target), {"a": 1})
        assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}

        triage.write_json_out(None, {"ignored": True})

    def test_download_results_json(self, monkeypatch, tmp_path):
        source_root = tmp_path / "source"
        source_root.mkdir(parents=True)
        source_file = source_root / triage.ARTIFACT_JSON
        source_file.write_text('{"summary":{}}', encoding="utf-8")

        monkeypatch.setattr(triage.tempfile, "mkdtemp", lambda prefix: str(source_root))
        monkeypatch.setattr(triage, "_run_gh", Mock(return_value=""))

        copied = triage.download_results_json("o/r", 10, triage.ARTIFACT_NAME)
        assert copied.exists()
        assert copied.name == "last_ci_scan_results.json"

    def test_run_triage_paths(self, monkeypatch):
        monkeypatch.setattr(triage, "default_repo", Mock(return_value="o/r"))
        monkeypatch.setattr(triage, "resolve_pr_number", Mock(return_value=84))
        monkeypatch.setattr(
            triage, "download_results_json", Mock(return_value=Path("x.json"))
        )
        monkeypatch.setattr(
            triage, "_load_json", Mock(return_value={"summary": {}, "results": []})
        )
        monkeypatch.setattr(
            triage,
            "_workflow_run_state",
            Mock(
                return_value={
                    "latest": {"databaseId": 201, "status": "in_progress"},
                    "latest_completed": {"databaseId": 200, "status": "completed"},
                }
            ),
        )

        def fake_build(doc, run_id, json_path, show_low_coverage, pr_number, ci_state):
            assert run_id == 200
            assert pr_number == 84
            assert ci_state is not None
            assert ci_state["pending_newer_run"] is True
            return ({"summary": {}, "actionable": [], "next_steps": []}, 0)

        monkeypatch.setattr(triage, "build_triage_payload", fake_build)
        monkeypatch.setattr(triage, "print_triage", Mock())
        monkeypatch.setattr(triage, "write_json_out", Mock())

        code, payload = triage.run_triage(
            repo=None,
            run_id=None,
            pr_number=84,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            show_low_coverage=False,
            json_out="out.json",
            print_output=True,
        )
        assert code == 0
        assert payload is not None

    def test_run_triage_uses_selected_pr_when_no_explicit_pr(self, monkeypatch):
        monkeypatch.setattr(triage, "default_repo", Mock(return_value="o/r"))
        monkeypatch.setattr(triage, "resolve_pr_number", Mock(return_value=85))
        monkeypatch.setattr(
            triage,
            "_workflow_run_state",
            Mock(
                return_value={
                    "latest": {"databaseId": 201, "status": "completed"},
                    "latest_completed": {"databaseId": 201, "status": "completed"},
                }
            ),
        )
        monkeypatch.setattr(
            triage, "download_results_json", Mock(return_value=Path("x.json"))
        )
        monkeypatch.setattr(
            triage, "_load_json", Mock(return_value={"summary": {}, "results": []})
        )
        monkeypatch.setattr(
            triage,
            "build_triage_payload",
            Mock(return_value=({"summary": {}, "actionable": [], "next_steps": []}, 0)),
        )
        monkeypatch.setattr(triage, "write_json_out", Mock())

        code, payload = triage.run_triage(
            repo=None,
            run_id=None,
            pr_number=None,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            show_low_coverage=False,
            json_out=None,
            print_output=False,
        )

        assert code == 0
        assert payload is not None
        triage.resolve_pr_number.assert_called_once_with("o/r", None)

    def test_main_success_and_error(self, monkeypatch):
        monkeypatch.setattr(triage, "run_triage", Mock(return_value=(0, {"ok": True})))
        assert triage.main(["--pr", "84"]) == 0

        monkeypatch.setattr(
            triage, "run_triage", Mock(side_effect=triage.TriageError("boom"))
        )
        assert triage.main(["--pr", "84"]) == 2
