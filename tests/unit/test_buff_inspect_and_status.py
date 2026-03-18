"""Unit tests for buff inspect/status paths."""

from __future__ import annotations

import argparse
from unittest.mock import Mock

from slopmop.cli import buff as buff_mod
from slopmop.cli import scan_triage as triage
from slopmop.core.result import CheckResult, CheckStatus


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


class TestBuffInspectCommand:
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
            Mock(return_value=_feedback_result(CheckStatus.PASSED)),
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
            Mock(return_value=_feedback_result(CheckStatus.PASSED)),
        )

        assert buff_mod.cmd_buff(args) == 1
        assert (
            "Buff inspect found unresolved CI scan signals." in capsys.readouterr().out
        )

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
            Mock(return_value=_feedback_result(CheckStatus.PASSED)),
        )

        assert buff_mod.cmd_buff(args) == 0
        assert '"schema": "slopmop/ci-triage/v1"' in capsys.readouterr().out

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
        feedback_gate = Mock(return_value=_feedback_result(CheckStatus.PASSED))
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
            Mock(return_value=_feedback_result(CheckStatus.PASSED)),
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
                return_value=_feedback_result(
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
            Mock(return_value=_feedback_result(CheckStatus.PASSED)),
        )

        assert buff_mod.cmd_buff(args) == 0
        assert (
            "== Buff inspect: checking CI code-scanning results =="
            in capsys.readouterr().out
        )


class TestBuffStatusCommand:
    def test_cmd_buff_status_reports_stale_selected_pr(self, monkeypatch, capsys):
        args = argparse.Namespace(
            pr_or_action="status",
            action_args=[],
            interval=30,
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
            Mock(side_effect=buff_mod.TriageError("Selected working PR #92 is stale")),
        )

        assert buff_mod.cmd_buff(args) == 1
        assert "Selected working PR #92 is stale" in capsys.readouterr().out

    def test_cmd_buff_status_blocks_on_unresolved_feedback(self, monkeypatch, capsys):
        args = argparse.Namespace(
            pr_or_action="status",
            action_args=["85"],
            interval=30,
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
            "_fetch_checks",
            Mock(
                return_value=(
                    [
                        {
                            "name": "Primary Code Scanning Gate (blocking)",
                            "bucket": "pass",
                            "state": "SUCCESS",
                            "link": "https://example.test/check",
                        }
                    ],
                    "",
                )
            ),
        )
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(
                return_value=_feedback_result(
                    CheckStatus.FAILED,
                    output="PR #85 has unresolved review threads.",
                )
            ),
        )

        assert buff_mod.cmd_buff(args) == 1
        out = capsys.readouterr().out
        assert "CI checks are clean, but unresolved PR review threads remain." in out
        assert "PR #85 has unresolved review threads." in out

    def test_cmd_buff_watch_waits_once_for_post_ci_feedback_settle(
        self, monkeypatch, capsys
    ):
        args = argparse.Namespace(
            pr_or_action="watch",
            action_args=["85"],
            interval=7,
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
        checks = [
            {
                "name": "Primary Code Scanning Gate (blocking)",
                "bucket": "pass",
                "state": "SUCCESS",
                "link": "https://example.test/check",
            },
            {
                "name": "Cursor Bugbot",
                "bucket": "neutral",
                "state": "NEUTRAL",
                "link": "https://cursor.com/docs/bugbot",
            },
        ]
        fetch_checks = Mock(side_effect=[(checks, ""), (checks, "")])
        monkeypatch.setattr(buff_mod, "_fetch_checks", fetch_checks)
        feedback_gate = Mock(return_value=_feedback_result(CheckStatus.PASSED))
        monkeypatch.setattr(buff_mod, "_run_pr_feedback_gate", feedback_gate)
        sleep_mock = Mock()
        monkeypatch.setattr(buff_mod.time, "sleep", sleep_mock)

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert "Waiting one extra interval for review feedback to settle" in out
        assert "CI CLEAN" in out
        assert fetch_checks.call_count == 2
        feedback_gate.assert_called_once_with(85, "/repo")
        sleep_mock.assert_called_once_with(7)

    def test_cmd_buff_status_no_checks_still_blocks_on_unresolved_feedback(
        self, monkeypatch, capsys
    ):
        args = argparse.Namespace(
            pr_or_action="status",
            action_args=["85"],
            interval=30,
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
        monkeypatch.setattr(buff_mod, "_fetch_checks", Mock(return_value=([], "")))
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(
                return_value=_feedback_result(
                    CheckStatus.FAILED,
                    output="PR #85 has unresolved review threads.",
                )
            ),
        )

        assert buff_mod.cmd_buff(args) == 1
        out = capsys.readouterr().out
        assert "no CI checks found, but unresolved PR review threads remain" in out
        assert "PR #85 has unresolved review threads." in out

    def test_cmd_buff_status_blocks_when_feedback_not_verified(
        self, monkeypatch, capsys
    ):
        args = argparse.Namespace(
            pr_or_action="status",
            action_args=["85"],
            interval=30,
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
            "_fetch_checks",
            Mock(
                return_value=(
                    [
                        {
                            "name": "Primary Code Scanning Gate (blocking)",
                            "bucket": "pass",
                            "state": "SUCCESS",
                            "link": "https://example.test/check",
                        }
                    ],
                    "",
                )
            ),
        )
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=_feedback_result(CheckStatus.SKIPPED)),
        )

        assert buff_mod.cmd_buff(args) == 1
        out = capsys.readouterr().out
        assert "Buff status error: could not verify unresolved PR feedback." in out
        assert "CI CLEAN" not in out

    def test_cmd_buff_watch_resets_settle_flag_after_failed_pending_poll(
        self, monkeypatch, capsys
    ):
        args = argparse.Namespace(
            pr_or_action="watch",
            action_args=["85"],
            interval=7,
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
        passing_checks = [
            {
                "name": "Primary Code Scanning Gate (blocking)",
                "bucket": "pass",
                "state": "SUCCESS",
                "link": "https://example.test/check",
            },
            {
                "name": "Cursor Bugbot",
                "bucket": "neutral",
                "state": "NEUTRAL",
                "link": "https://cursor.com/docs/bugbot",
            },
        ]
        failed_pending_checks = [
            {
                "name": "Primary Code Scanning Gate (blocking)",
                "bucket": "fail",
                "state": "FAILURE",
                "link": "https://example.test/fail",
            },
            {
                "name": "Cursor Bugbot",
                "bucket": "pending",
                "state": "IN_PROGRESS",
                "link": "https://cursor.com/docs/bugbot",
            },
        ]
        fetch_checks = Mock(
            side_effect=[
                (passing_checks, ""),
                (failed_pending_checks, ""),
                (passing_checks, ""),
                (passing_checks, ""),
            ]
        )
        monkeypatch.setattr(buff_mod, "_fetch_checks", fetch_checks)
        feedback_gate = Mock(return_value=_feedback_result(CheckStatus.PASSED))
        monkeypatch.setattr(buff_mod, "_run_pr_feedback_gate", feedback_gate)
        sleep_mock = Mock()
        monkeypatch.setattr(buff_mod.time, "sleep", sleep_mock)

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert (
            out.count("Waiting one extra interval for review feedback to settle") == 2
        )
        assert fetch_checks.call_count == 4
        feedback_gate.assert_called_once_with(85, "/repo")
        assert sleep_mock.call_count == 3
