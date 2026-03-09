"""Unit tests for CI triage rail helpers and buff command paths."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from slopmop.cli import buff as buff_mod
from slopmop.cli import scan_triage as triage
from slopmop.core.result import CheckResult, CheckStatus
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

    def test_default_next_steps(self):
        with_pr = rail.default_next_steps(84)
        assert with_pr[-1] == "Re-run triage: sm buff 84"
        assert with_pr[1] == "Run full validation locally: sm scour"
        assert with_pr[2] == "Push your branch with the fixes"

        no_pr = rail.default_next_steps(None)
        assert no_pr[-1] == "Re-run triage: sm buff"


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

        def fake_gh(_cmd):
            return responses.pop(0)

        monkeypatch.setattr(triage, "_run_gh", fake_gh)
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
        assert payload["next_steps"][1] == "Run full validation locally: sm scour"
        assert len(payload["actionable"]) == 2
        assert payload["lowest_coverage"][0]["coverage_pct"] == 62.5
        assert payload["ci_state"]["latest_status"] == "in_progress"

        triage.print_triage(payload, show_low_coverage=True)
        out = capsys.readouterr().out
        assert "Actionable Gates:" in out
        assert "CI State:" in out
        assert "CI State Note:" in out
        assert "Next Steps:" in out
        assert "Re-run triage: sm buff 84" in out
        assert "Lowest Coverage Findings:" in out

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

    def test_main_success_and_error(self, monkeypatch):
        monkeypatch.setattr(triage, "run_triage", Mock(return_value=(0, {"ok": True})))
        assert triage.main(["--pr", "84"]) == 0

        monkeypatch.setattr(
            triage, "run_triage", Mock(side_effect=triage.TriageError("boom"))
        )
        assert triage.main(["--pr", "84"]) == 2


class TestBuffCommand:
    @staticmethod
    def _feedback_result(status: CheckStatus, **kwargs) -> CheckResult:
        return CheckResult(
            name="myopia:ignored-feedback",
            status=status,
            duration=0.01,
            output=kwargs.get("output", ""),
            error=kwargs.get("error"),
            fix_suggestion=kwargs.get("fix_suggestion"),
            status_detail=kwargs.get("status_detail"),
        )

    def test_cmd_buff_human_success(self, monkeypatch, capsys):
        args = argparse.Namespace(
            json_output=False,
            repo=None,
            run_id=None,
            pr_number=84,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
        )

        monkeypatch.setattr(
            buff_mod,
            "run_triage",
            Mock(return_value=(0, {"summary": {}, "actionable": [], "next_steps": []})),
        )
        monkeypatch.setattr(buff_mod, "write_json_out", Mock())
        monkeypatch.setattr(buff_mod, "print_triage", Mock())
        monkeypatch.setattr(buff_mod, "_project_root_from_cwd", Mock(return_value="/repo"))
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=self._feedback_result(CheckStatus.PASSED)),
        )

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert "== Buff: checking CI code-scanning results ==" in out
        assert "Buff clean: CI scan signals are resolved." in out

    def test_cmd_buff_human_failure(self, monkeypatch, capsys):
        args = argparse.Namespace(
            json_output=False,
            repo=None,
            run_id=None,
            pr_number=84,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
        )

        monkeypatch.setattr(
            buff_mod,
            "run_triage",
            Mock(
                return_value=(
                    1,
                    {"summary": {}, "actionable": [{"gate": "g"}], "next_steps": []},
                )
            ),
        )
        monkeypatch.setattr(buff_mod, "write_json_out", Mock())
        monkeypatch.setattr(buff_mod, "print_triage", Mock())
        monkeypatch.setattr(buff_mod, "_project_root_from_cwd", Mock(return_value="/repo"))
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=self._feedback_result(CheckStatus.PASSED)),
        )

        assert buff_mod.cmd_buff(args) == 1
        out = capsys.readouterr().out
        assert "Buff failed: unresolved CI scan signals remain." in out

    def test_cmd_buff_json_mode(self, monkeypatch, capsys, tmp_path):
        args = argparse.Namespace(
            json_output=True,
            repo=None,
            run_id=None,
            pr_number=84,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=str(tmp_path / "buff.json"),
        )

        payload = {"schema": "slopmop/ci-triage/v1", "summary": {}, "actionable": []}
        monkeypatch.setattr(buff_mod, "run_triage", Mock(return_value=(0, payload)))
        monkeypatch.setattr(buff_mod, "_project_root_from_cwd", Mock(return_value="/repo"))
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=self._feedback_result(CheckStatus.PASSED)),
        )

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert '"schema": "slopmop/ci-triage/v1"' in out

    def test_cmd_buff_uses_resolved_pr_number_from_triage_payload(self, monkeypatch):
        args = argparse.Namespace(
            json_output=False,
            repo=None,
            run_id=None,
            pr_number=None,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
        )

        monkeypatch.setattr(
            buff_mod,
            "run_triage",
            Mock(
                return_value=(
                    0,
                    {
                        "pr_number": 85,
                        "summary": {},
                        "actionable": [],
                        "next_steps": [],
                    },
                )
            ),
        )
        monkeypatch.setattr(buff_mod, "write_json_out", Mock())
        monkeypatch.setattr(buff_mod, "print_triage", Mock())
        monkeypatch.setattr(buff_mod, "_project_root_from_cwd", Mock(return_value="/repo"))
        feedback_gate = Mock(return_value=self._feedback_result(CheckStatus.PASSED))
        monkeypatch.setattr(buff_mod, "_run_pr_feedback_gate", feedback_gate)

        assert buff_mod.cmd_buff(args) == 0
        feedback_gate.assert_called_once_with(85, "/repo")

    def test_cmd_buff_no_payload(self, monkeypatch, capsys):
        args = argparse.Namespace(
            json_output=False,
            repo=None,
            run_id=None,
            pr_number=84,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
        )

        monkeypatch.setattr(buff_mod, "run_triage", Mock(return_value=(0, None)))
        monkeypatch.setattr(buff_mod, "_project_root_from_cwd", Mock(return_value="/repo"))
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=self._feedback_result(CheckStatus.PASSED)),
        )
        assert buff_mod.cmd_buff(args) == 1
        assert "ERROR: CI triage produced no payload." in capsys.readouterr().out

    def test_cmd_buff_triage_error(self, monkeypatch, capsys):
        args = argparse.Namespace(
            json_output=False,
            repo=None,
            run_id=None,
            pr_number=84,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
        )

        monkeypatch.setattr(
            buff_mod,
            "run_triage",
            Mock(side_effect=buff_mod.TriageError("bad triage")),
        )

        assert buff_mod.cmd_buff(args) == 1
        assert "ERROR: bad triage" in capsys.readouterr().out

    def test_cmd_buff_fails_on_unresolved_feedback(self, monkeypatch, capsys):
        args = argparse.Namespace(
            json_output=False,
            repo=None,
            run_id=None,
            pr_number=85,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
        )

        monkeypatch.setattr(
            buff_mod,
            "run_triage",
            Mock(return_value=(0, {"summary": {}, "actionable": [], "next_steps": []})),
        )
        monkeypatch.setattr(buff_mod, "write_json_out", Mock())
        monkeypatch.setattr(buff_mod, "print_triage", Mock())
        monkeypatch.setattr(buff_mod, "_project_root_from_cwd", Mock(return_value="/repo"))
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(
                return_value=self._feedback_result(
                    CheckStatus.FAILED,
                    status_detail="3 unresolved",
                    output="PR #85 has unresolved review threads.",
                    error="3 unresolved PR comment(s)",
                    fix_suggestion="Read full report: cat /tmp/pr_85_comments_report.md",
                )
            ),
        )

        assert buff_mod.cmd_buff(args) == 1
        out = capsys.readouterr().out
        assert "Buff failed: unresolved PR review threads remain." in out
        assert "PR #85 has unresolved review threads." in out

    def test_project_root_from_cwd_uses_git_toplevel(self, monkeypatch):
        monkeypatch.setattr(
            buff_mod.subprocess,
            "run",
            Mock(return_value=SimpleNamespace(returncode=0, stdout="/repo\n")),
        )

        assert buff_mod._project_root_from_cwd() == "/repo"

    def test_project_root_from_cwd_falls_back_to_cwd(self, monkeypatch):
        monkeypatch.setattr(
            buff_mod.subprocess,
            "run",
            Mock(return_value=SimpleNamespace(returncode=1, stdout="")),
        )
        monkeypatch.setattr(buff_mod.os, "getcwd", Mock(return_value="/cwd"))

        assert buff_mod._project_root_from_cwd() == "/cwd"
