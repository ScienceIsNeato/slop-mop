"""Unit tests for buff iterate/finalize/verify/resolve flows."""

from __future__ import annotations

import argparse
import json
from types import SimpleNamespace
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


class TestBuffIterateAndFinalize:
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
            Mock(return_value=_feedback_result(CheckStatus.FAILED)),
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
            Mock(return_value=_feedback_result(CheckStatus.PASSED)),
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
            Mock(return_value=_feedback_result(CheckStatus.PASSED)),
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
            Mock(return_value=_feedback_result(CheckStatus.PASSED)),
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
            Mock(return_value=_feedback_result(CheckStatus.PASSED)),
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
            Mock(return_value=_feedback_result(CheckStatus.PASSED)),
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


class TestBuffVerifyAndResolve:
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
            Mock(return_value=_feedback_result(CheckStatus.PASSED)),
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


class TestBuffProjectRootHelpers:
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
