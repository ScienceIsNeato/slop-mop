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
        assert with_pr[-1] == "Re-run PR inspection: sm buff inspect 84"
        assert with_pr[1] == (
            "If fixes take multiple passes, loop on sm swab until local issues are stable"
        )
        assert with_pr[2] == "Run full validation locally: sm scour"

        no_pr = rail.default_next_steps(None)
        assert no_pr[-1] == "Re-run PR inspection: sm buff inspect"


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

    def test_validate_open_pr_rejects_closed_pr(self, monkeypatch):
        monkeypatch.setattr(
            triage,
            "_run_gh",
            Mock(return_value=json.dumps({"number": 85, "state": "CLOSED"})),
        )

        with pytest.raises(triage.TriageError, match="is not open"):
            triage.validate_open_pr("o/r", 85)

    def test_resolve_pr_number_uses_selected_pr(self, monkeypatch):
        monkeypatch.setattr(triage, "get_current_pr_number", Mock(return_value=85))
        monkeypatch.setattr(triage, "validate_open_pr", Mock(return_value=85))

        assert triage.resolve_pr_number("o/r", None) == 85
        triage.validate_open_pr.assert_called_once_with("o/r", 85)

    def test_resolve_pr_number_reads_selection_from_git_root(self, monkeypatch):
        root = Path("/repo")
        root_resolver = Mock(return_value=root)
        selected_pr = Mock(return_value=85)
        validator = Mock(return_value=85)
        monkeypatch.setattr(triage, "_project_root_from_cwd", root_resolver)
        monkeypatch.setattr(triage, "get_current_pr_number", selected_pr)
        monkeypatch.setattr(triage, "validate_open_pr", validator)

        assert triage.resolve_pr_number("o/r", None) == 85
        selected_pr.assert_called_once_with(root)
        validator.assert_called_once_with("o/r", 85)

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
        assert payload["lowest_coverage"][0]["coverage_pct"] == 62.5
        assert payload["ci_state"]["latest_status"] == "in_progress"

        triage.print_triage(payload, show_low_coverage=True)
        out = capsys.readouterr().out
        assert "Actionable Gates:" in out
        assert "CI State:" in out
        assert "CI State Note:" in out
        assert "Next Steps:" in out
        assert "Re-run PR inspection: sm buff inspect 84" in out
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
        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=self._feedback_result(CheckStatus.PASSED)),
        )

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert "== Buff inspect: checking CI code-scanning results ==" in out
        assert (
            "Buff inspect clean: CI scan signals and PR feedback are resolved." in out
        )

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
        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=self._feedback_result(CheckStatus.PASSED)),
        )

        assert buff_mod.cmd_buff(args) == 1
        out = capsys.readouterr().out
        assert "Buff inspect found unresolved CI scan signals." in out

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
        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
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
        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
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
        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
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
        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
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
        assert "Buff inspect found unresolved PR review threads." in out
        assert "PR #85 has unresolved review threads." in out

    def test_cmd_buff_inspect_aliases_default_behavior(self, monkeypatch, capsys):
        args = argparse.Namespace(
            pr_or_action="inspect",
            action_args=["85"],
            json_output=False,
            repo=None,
            run_id=None,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
            scenario=None,
            message=None,
            no_resolve=False,
        )

        monkeypatch.setattr(
            buff_mod,
            "run_triage",
            Mock(return_value=(0, {"summary": {}, "actionable": [], "next_steps": []})),
        )
        monkeypatch.setattr(buff_mod, "write_json_out", Mock())
        monkeypatch.setattr(buff_mod, "print_triage", Mock())
        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=self._feedback_result(CheckStatus.PASSED)),
        )

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert "== Buff inspect: checking CI code-scanning results ==" in out

    def test_cmd_buff_iterate_selects_rank_frontier(
        self, monkeypatch, capsys, tmp_path
    ):
        args = argparse.Namespace(
            pr_or_action="iterate",
            action_args=["85"],
            json_output=False,
            repo=None,
            run_id=None,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
            scenario=None,
            message=None,
            no_resolve=False,
        )

        loop_dir = (
            tmp_path / ".slopmop" / "buff-persistent-memory" / "pr-85" / "loop-001"
        )
        loop_dir.mkdir(parents=True)
        (loop_dir / "protocol.json").write_text(
            json.dumps(
                {
                    "pr_number": 85,
                    "loop_dir": str(loop_dir),
                    "ordered_threads": [
                        {
                            "thread_id": "PRRT_a",
                            "resolution_priority_rank": 1,
                            "resolution_scenario": "fixed_in_code",
                            "category": "🐛 Logic/Correctness",
                            "path": "a.py",
                            "line": 10,
                        },
                        {
                            "thread_id": "PRRT_b",
                            "resolution_priority_rank": 1,
                            "resolution_scenario": "fixed_in_code",
                            "category": "🧪 Testing",
                            "path": "b.py",
                            "line": 12,
                        },
                        {
                            "thread_id": "PRRT_c",
                            "resolution_priority_rank": 2,
                            "resolution_scenario": "needs_human_feedback",
                            "category": "❓ Question",
                            "path": "c.py",
                            "line": 3,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value=str(tmp_path))
        )
        monkeypatch.setattr(buff_mod, "_get_repo_slug", Mock(return_value="o/r"))
        monkeypatch.setattr(buff_mod, "resolve_pr_number", Mock(return_value=85))
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=self._feedback_result(CheckStatus.FAILED)),
        )

        assert buff_mod.cmd_buff(args) == 1
        out = capsys.readouterr().out
        assert "Buff iterate round prepared for PR #85." in out
        assert "PRRT_a" in out
        assert "PRRT_b" in out
        assert "PRRT_c" not in out
        assert "Drafts artifact:" in out
        iteration_doc = json.loads(
            (loop_dir / "next_iteration.json").read_text(encoding="utf-8")
        )
        assert iteration_doc["thread_ids"] == ["PRRT_a", "PRRT_b"]
        drafts_doc = json.loads((loop_dir / "drafts.json").read_text(encoding="utf-8"))
        assert len(drafts_doc["drafts"]) == 2
        assert drafts_doc["drafts"][0]["draft_status"] == "pending"
        assert (
            "Replace with commit SHA after committing"
            in drafts_doc["drafts"][0]["comment_template"]
        )
        assert (loop_dir / "iteration_log.md").exists()

    def test_cmd_buff_iterate_runs_scour_when_feedback_is_clean(
        self, monkeypatch, capsys
    ):
        args = argparse.Namespace(
            pr_or_action="iterate",
            action_args=["85"],
            json_output=False,
            repo=None,
            run_id=None,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
            scenario=None,
            message=None,
            no_resolve=False,
        )

        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
        monkeypatch.setattr(buff_mod, "_get_repo_slug", Mock(return_value="o/r"))
        monkeypatch.setattr(buff_mod, "resolve_pr_number", Mock(return_value=85))
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=self._feedback_result(CheckStatus.PASSED)),
        )
        monkeypatch.setattr(buff_mod, "_run_scour_quietly", Mock(return_value=1))

        assert buff_mod.cmd_buff(args) == 1
        out = capsys.readouterr().out
        assert "Falling through to scour before finalization." in out
        assert "Scour found issues." in out

    def test_cmd_buff_finalize_reports_ready_without_push(self, monkeypatch, capsys):
        args = argparse.Namespace(
            pr_or_action="finalize",
            action_args=["85"],
            json_output=False,
            repo=None,
            run_id=None,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
            scenario=None,
            message=None,
            no_resolve=False,
            push=False,
        )

        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
        monkeypatch.setattr(buff_mod, "_get_repo_slug", Mock(return_value="o/r"))
        monkeypatch.setattr(buff_mod, "resolve_pr_number", Mock(return_value=85))
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=self._feedback_result(CheckStatus.PASSED)),
        )
        monkeypatch.setattr(buff_mod, "_run_scour_quietly", Mock(return_value=0))
        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert (
            "Buff finalize ready: PR #85 is clean. Re-run with --push to publish."
            in out
        )
        assert "Finalize plan:" in out

    def test_cmd_buff_finalize_pushes_when_requested(self, monkeypatch, capsys):
        args = argparse.Namespace(
            pr_or_action="finalize",
            action_args=["85"],
            json_output=False,
            repo=None,
            run_id=None,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
            scenario=None,
            message=None,
            no_resolve=False,
            push=True,
        )

        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
        monkeypatch.setattr(buff_mod, "_get_repo_slug", Mock(return_value="o/r"))
        monkeypatch.setattr(buff_mod, "resolve_pr_number", Mock(return_value=85))
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=self._feedback_result(CheckStatus.PASSED)),
        )
        monkeypatch.setattr(buff_mod, "_run_scour_quietly", Mock(return_value=0))
        push_branch = Mock(return_value=0)
        monkeypatch.setattr(buff_mod, "_push_current_branch", push_branch)

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert "Buff finalize complete: pushed the current branch for PR #85." in out
        assert "Finalize plan:" in out
        push_branch.assert_called_once_with("/repo")

    def test_cmd_buff_finalize_blocks_when_scour_fails(self, monkeypatch, capsys):
        args = argparse.Namespace(
            pr_or_action="finalize",
            action_args=["85"],
            json_output=False,
            repo=None,
            run_id=None,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
            scenario=None,
            message=None,
            no_resolve=False,
            push=False,
        )

        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
        monkeypatch.setattr(buff_mod, "_get_repo_slug", Mock(return_value="o/r"))
        monkeypatch.setattr(buff_mod, "resolve_pr_number", Mock(return_value=85))
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=self._feedback_result(CheckStatus.PASSED)),
        )
        monkeypatch.setattr(buff_mod, "_run_scour_quietly", Mock(return_value=1))

        assert buff_mod.cmd_buff(args) == 1
        out = capsys.readouterr().out
        assert "Buff finalize blocked: scour found issues." in out
        assert "Finalize plan:" in out

    def test_cmd_buff_finalize_writes_plan_file(self, monkeypatch, capsys, tmp_path):
        args = argparse.Namespace(
            pr_or_action="finalize",
            action_args=["85"],
            json_output=False,
            repo=None,
            run_id=None,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
            scenario=None,
            message=None,
            no_resolve=False,
            push=False,
        )

        loop_dir = (
            tmp_path / ".slopmop" / "buff-persistent-memory" / "pr-85" / "loop-009"
        )
        loop_dir.mkdir(parents=True)
        (loop_dir / "protocol.json").write_text(
            json.dumps({"pr_number": 85, "loop_dir": str(loop_dir)}),
            encoding="utf-8",
        )

        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value=str(tmp_path))
        )
        monkeypatch.setattr(buff_mod, "_get_repo_slug", Mock(return_value="o/r"))
        monkeypatch.setattr(buff_mod, "resolve_pr_number", Mock(return_value=85))
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=self._feedback_result(CheckStatus.PASSED)),
        )
        monkeypatch.setattr(buff_mod, "_run_scour_quietly", Mock(return_value=0))

        assert buff_mod.cmd_buff(args) == 0
        plan_doc = json.loads(
            (
                tmp_path
                / ".slopmop"
                / "buff-persistent-memory"
                / "pr-85"
                / "loop-009"
                / "finalize_plan.json"
            ).read_text(encoding="utf-8")
        )
        assert plan_doc["ready_to_push"] is True
        assert plan_doc["next_step"] == "sm buff finalize --push"

    def test_cmd_buff_verify_clean(self, monkeypatch, capsys):
        args = argparse.Namespace(
            pr_or_action="verify",
            action_args=["85"],
            json_output=False,
            repo=None,
            run_id=None,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
            scenario=None,
            message=None,
            no_resolve=False,
        )

        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
        monkeypatch.setattr(buff_mod, "_get_repo_slug", Mock(return_value="o/r"))
        monkeypatch.setattr(buff_mod, "resolve_pr_number", Mock(return_value=85))
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=self._feedback_result(CheckStatus.PASSED)),
        )

        assert buff_mod.cmd_buff(args) == 0
        assert (
            "Buff verify clean: PR #85 has no unresolved review threads."
            in capsys.readouterr().out
        )

    def test_cmd_buff_resolve_posts_comment_and_resolves_thread(
        self, monkeypatch, capsys
    ):
        args = argparse.Namespace(
            pr_or_action="resolve",
            action_args=["85", "PRRT_abc"],
            json_output=False,
            repo=None,
            run_id=None,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
            scenario="fixed_in_code",
            message="Fixed in commit abc123.",
            no_resolve=False,
        )

        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
        monkeypatch.setattr(
            buff_mod,
            "_get_repo_owner_name",
            Mock(return_value=("owner", "repo")),
        )
        monkeypatch.setattr(buff_mod, "resolve_pr_number", Mock(return_value=85))
        post_comment = Mock()
        resolve_thread = Mock()
        monkeypatch.setattr(buff_mod, "_post_pr_comment", post_comment)
        monkeypatch.setattr(buff_mod, "_resolve_review_thread", resolve_thread)

        assert buff_mod.cmd_buff(args) == 0
        post_comment.assert_called_once_with(
            "/repo",
            "owner",
            "repo",
            85,
            "[fixed_in_code] Fixed in commit abc123.",
        )
        resolve_thread.assert_called_once_with("/repo", "PRRT_abc")
        assert (
            "Buff resolve complete: commented and resolved PRRT_abc on PR #85."
            in capsys.readouterr().out
        )

    def test_cmd_buff_verify_requires_selected_or_explicit_pr(
        self, monkeypatch, capsys
    ):
        args = argparse.Namespace(
            pr_or_action="verify",
            action_args=[],
            json_output=False,
            repo=None,
            run_id=None,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
            scenario=None,
            message=None,
            no_resolve=False,
        )

        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
        monkeypatch.setattr(buff_mod, "_get_repo_slug", Mock(return_value="o/r"))
        monkeypatch.setattr(
            buff_mod,
            "resolve_pr_number",
            Mock(side_effect=buff_mod.TriageError("No working PR selected.")),
        )

        assert buff_mod.cmd_buff(args) == 1
        assert "No working PR selected." in capsys.readouterr().out

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
