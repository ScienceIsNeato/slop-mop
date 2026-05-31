"""Unit tests for buff inspect/status paths."""

from __future__ import annotations

import argparse
import json
from unittest.mock import Mock

from slopmop.cli import _buff_status as status_mod
from slopmop.cli import buff as buff_mod
from slopmop.cli import scan_triage as triage
from slopmop.core.result import CheckStatus
from tests.conftest import make_feedback_result, patch_buff_pr_resolution


class TestBuffStatusJson:
    def _patch_common(self, monkeypatch):
        monkeypatch.setattr(
            status_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
        monkeypatch.setattr(status_mod, "_get_repo_slug", Mock(return_value="o/r"))
        monkeypatch.setattr(
            status_mod,
            "resolve_pr_number_with_source",
            Mock(return_value=(84, "explicit")),
        )
        monkeypatch.setattr(status_mod, "_fire_buff_hook", Mock())

    def test_status_json_clean_emits_envelope(self, monkeypatch, capsys):
        self._patch_common(monkeypatch)
        monkeypatch.setattr(
            status_mod,
            "_fetch_checks",
            Mock(return_value=([{"name": "CI", "bucket": "pass"}], None)),
        )
        monkeypatch.setattr(
            status_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=make_feedback_result(CheckStatus.PASSED)),
        )

        exit_code = status_mod.cmd_buff_status(84, False, 30, json_output=True)
        assert exit_code == 0

        envelope = json.loads(capsys.readouterr().out)
        assert envelope["schema"] == "slopmop/v3"
        assert envelope["command"] == "buff"
        assert envelope["status"] == "ok"
        assert envelope["exit_code"] == 0
        assert envelope["data"]["overall_state"] == "clean"
        assert envelope["data"]["pr_number"] == 84
        assert envelope["data"]["checks"]["passed"] == 1

    def test_status_json_feedback_blocked_emits_fail_envelope(
        self, monkeypatch, capsys
    ):
        self._patch_common(monkeypatch)
        monkeypatch.setattr(
            status_mod,
            "_fetch_checks",
            Mock(return_value=([{"name": "CI", "bucket": "pass"}], None)),
        )
        monkeypatch.setattr(
            status_mod,
            "_run_pr_feedback_gate",
            Mock(
                return_value=make_feedback_result(
                    CheckStatus.FAILED,
                    output="PR #84 has unresolved review threads.",
                    error="2 unresolved PR comment(s)",
                )
            ),
        )

        exit_code = status_mod.cmd_buff_status(84, False, 30, json_output=True)
        assert exit_code == 1

        envelope = json.loads(capsys.readouterr().out)
        assert envelope["status"] == "fail"
        assert envelope["exit_code"] == 1
        assert envelope["data"]["overall_state"] == "feedback_blocked"
        assert envelope["next_steps"][0]["command"] == "sm buff inspect"

    # ── Human-mode (show_human=True) coverage for every terminal state ──────
    #
    # The json tests above exercise show_human=False; these drive the
    # human-output branches (watch=False, json_output=False) so both arcs of
    # every ``if show_human:`` guard and each overall_state return are covered.

    def _patch_human(self, monkeypatch, *, checks, feedback):
        """Patch resolution + narration so a non-json status call runs cleanly."""
        self._patch_common(monkeypatch)
        monkeypatch.setattr(
            status_mod, "_get_current_branch", Mock(return_value="feature")
        )
        monkeypatch.setattr(status_mod, "_fetch_checks", Mock(return_value=checks))
        if feedback is not None:
            monkeypatch.setattr(
                status_mod, "_run_pr_feedback_gate", Mock(return_value=feedback)
            )
        # Silence narration helpers — the point is the control flow in
        # _buff_status, not what these already-tested helpers print.
        for name in (
            "print_ci_state_summary",
            "print_pr_selection_trace",
            "format_feedback_state",
            "_print_failed_status",
            "_print_in_progress_status",
            "_print_success_status",
        ):
            monkeypatch.setattr(status_mod, name, Mock(return_value=""))
        import slopmop.reporting as reporting_mod

        monkeypatch.setattr(reporting_mod, "print_project_header", Mock())
        monkeypatch.setattr(buff_mod, "_warn_if_pr_worktree_mismatch", Mock())

    def test_human_clean(self, monkeypatch, capsys):
        self._patch_human(
            monkeypatch,
            checks=([{"name": "slopmop", "bucket": "pass"}], None),
            feedback=make_feedback_result(CheckStatus.PASSED),
        )
        exit_code = status_mod.cmd_buff_status(84, False, 30, json_output=False)
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "Final PR state: clean" in out
        assert "{" not in out  # no json envelope in human mode

    def test_human_ci_failed(self, monkeypatch):
        self._patch_human(
            monkeypatch,
            checks=([{"name": "CI", "bucket": "fail", "link": "http://x"}], None),
            feedback=None,
        )
        exit_code = status_mod.cmd_buff_status(84, False, 30, json_output=False)
        assert exit_code == 1

    def test_human_ci_in_progress(self, monkeypatch, capsys):
        self._patch_human(
            monkeypatch,
            checks=([{"name": "CI", "bucket": "pending"}], None),
            feedback=None,
        )
        exit_code = status_mod.cmd_buff_status(84, False, 30, json_output=False)
        assert exit_code == 1
        assert "sm buff watch" in capsys.readouterr().out

    def test_human_feedback_blocked(self, monkeypatch):
        self._patch_human(
            monkeypatch,
            checks=([{"name": "slopmop", "bucket": "pass"}], None),
            feedback=make_feedback_result(
                CheckStatus.FAILED, output="unresolved threads"
            ),
        )
        exit_code = status_mod.cmd_buff_status(84, False, 30, json_output=False)
        assert exit_code == 1

    def test_human_no_checks_feedback_resolved(self, monkeypatch, capsys):
        self._patch_human(
            monkeypatch,
            checks=([], None),
            feedback=make_feedback_result(CheckStatus.PASSED),
        )
        exit_code = status_mod.cmd_buff_status(84, False, 30, json_output=False)
        assert exit_code == 0
        assert "No CI checks found" in capsys.readouterr().out

    def test_human_no_checks_feedback_blocked(self, monkeypatch):
        self._patch_human(
            monkeypatch,
            checks=([], None),
            feedback=make_feedback_result(CheckStatus.FAILED, output="threads"),
        )
        exit_code = status_mod.cmd_buff_status(84, False, 30, json_output=False)
        assert exit_code == 1

    def test_human_error_checks_none(self, monkeypatch, capsys):
        self._patch_human(
            monkeypatch,
            checks=(None, "PR not found"),
            feedback=None,
        )
        exit_code = status_mod.cmd_buff_status(84, False, 30, json_output=False)
        assert exit_code == 2  # "not found" → exit 2
        assert "ERROR: PR not found" in capsys.readouterr().out

    # ── Remaining json-mode states (show_human=False) ──────────────────────

    def test_json_ci_in_progress_emits_wait_next_step(self, monkeypatch, capsys):
        self._patch_common(monkeypatch)
        monkeypatch.setattr(
            status_mod,
            "_fetch_checks",
            Mock(return_value=([{"name": "CI", "bucket": "pending"}], None)),
        )
        exit_code = status_mod.cmd_buff_status(84, False, 30, json_output=True)
        assert exit_code == 1
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["data"]["overall_state"] == "ci_in_progress"
        # "still running" is informational, not a blocking failure — agents
        # keying off status alone must not treat an in-flight PR as failed.
        assert envelope["status"] == "info"
        assert envelope["next_steps"][0]["command"] == "sm buff watch"

    def test_json_ci_failed(self, monkeypatch, capsys):
        self._patch_common(monkeypatch)
        monkeypatch.setattr(
            status_mod,
            "_fetch_checks",
            Mock(return_value=([{"name": "CI", "bucket": "fail", "link": "u"}], None)),
        )
        exit_code = status_mod.cmd_buff_status(84, False, 30, json_output=True)
        assert exit_code == 1
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["data"]["overall_state"] == "ci_failed"

    def test_json_error_emits_error_envelope(self, monkeypatch, capsys):
        self._patch_common(monkeypatch)
        monkeypatch.setattr(
            status_mod, "_fetch_checks", Mock(return_value=(None, "boom"))
        )
        exit_code = status_mod.cmd_buff_status(84, False, 30, json_output=True)
        assert exit_code == 1
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["status"] == "error"
        assert envelope["data"]["overall_state"] == "error"

    def test_json_no_checks_feedback_resolved(self, monkeypatch, capsys):
        self._patch_common(monkeypatch)
        monkeypatch.setattr(status_mod, "_fetch_checks", Mock(return_value=([], None)))
        monkeypatch.setattr(
            status_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=make_feedback_result(CheckStatus.PASSED)),
        )
        exit_code = status_mod.cmd_buff_status(84, False, 30, json_output=True)
        assert exit_code == 0
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["data"]["overall_state"] == "no_checks_feedback_resolved"

    def test_json_no_checks_feedback_blocked(self, monkeypatch, capsys):
        self._patch_common(monkeypatch)
        monkeypatch.setattr(status_mod, "_fetch_checks", Mock(return_value=([], None)))
        monkeypatch.setattr(
            status_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=make_feedback_result(CheckStatus.FAILED, output="t")),
        )
        exit_code = status_mod.cmd_buff_status(84, False, 30, json_output=True)
        assert exit_code == 1
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["data"]["overall_state"] == "no_checks_feedback_blocked"

    # ── _render_status_feedback_blocker direct unit coverage ───────────────

    def test_render_feedback_blocker_error_status(self, capsys):
        """Non-FAILED feedback hits the 'could not verify' error branch."""
        result = make_feedback_result(CheckStatus.ERROR, error="gh exploded")
        rc = status_mod._render_status_feedback_blocker(result, no_checks=False)
        assert rc == 1
        out = capsys.readouterr().out
        assert "could not verify" in out
        assert "gh exploded" in out

    def test_render_feedback_blocker_no_checks_no_output(self, capsys):
        """no_checks=True with empty output exercises the alternate arcs."""
        result = make_feedback_result(CheckStatus.FAILED)  # no output
        rc = status_mod._render_status_feedback_blocker(result, no_checks=True)
        assert rc == 1
        assert "no CI checks found" in capsys.readouterr().out


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
            "run_inspect_scan",
            Mock(return_value=(0, {"summary": {}, "actionable": [], "next_steps": []})),
        )
        monkeypatch.setattr(buff_mod, "write_json_out", Mock())
        monkeypatch.setattr(buff_mod, "print_triage", Mock())
        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
        patch_buff_pr_resolution(monkeypatch, 84)
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=make_feedback_result(CheckStatus.PASSED)),
        )

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert "== Buff inspect: checking CI code-scanning results ==" in out
        assert "== Buff PR selection ==" in out
        assert "Selected PR: #84 (explicit)" in out
        assert "== Buff PR state ==" in out
        assert "Overall: clean - CI scan signals and PR feedback are resolved" in out
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
            "run_inspect_scan",
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
        patch_buff_pr_resolution(monkeypatch, 84)
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=make_feedback_result(CheckStatus.PASSED)),
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
        monkeypatch.setattr(
            buff_mod, "run_inspect_scan", Mock(return_value=(0, payload))
        )
        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
        patch_buff_pr_resolution(monkeypatch, 84)
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=make_feedback_result(CheckStatus.PASSED)),
        )

        assert buff_mod.cmd_buff(args) == 0
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["schema"] == "slopmop/v3"
        assert envelope["command"] == "buff"
        assert envelope["status"] == "ok"
        assert envelope["exit_code"] == 0
        assert envelope["data"]["schema"] == "slopmop/ci-triage/v1"

        # The --output file must carry the same v3 envelope as stdout, not the
        # bare inner payload — a pipeline capturing the file sees the contract.
        file_doc = json.loads((tmp_path / "buff.json").read_text(encoding="utf-8"))
        assert file_doc == envelope

    def test_cmd_buff_uses_pre_resolved_pr_number(self, monkeypatch):
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
            "run_inspect_scan",
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
        patch_buff_pr_resolution(monkeypatch, 85, "branch")
        feedback_gate = Mock(return_value=make_feedback_result(CheckStatus.PASSED))
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

        monkeypatch.setattr(buff_mod, "run_inspect_scan", Mock(return_value=(0, None)))
        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
        patch_buff_pr_resolution(monkeypatch, 84)
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=make_feedback_result(CheckStatus.PASSED)),
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
            "run_inspect_scan",
            Mock(side_effect=buff_mod.TriageError("bad triage")),
        )
        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
        patch_buff_pr_resolution(monkeypatch, 84)

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
            "run_inspect_scan",
            Mock(return_value=(0, {"summary": {}, "actionable": [], "next_steps": []})),
        )
        monkeypatch.setattr(buff_mod, "write_json_out", Mock())
        monkeypatch.setattr(buff_mod, "print_triage", Mock())
        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
        patch_buff_pr_resolution(monkeypatch, 85)
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(
                return_value=make_feedback_result(
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
            "run_inspect_scan",
            Mock(return_value=(0, {"summary": {}, "actionable": [], "next_steps": []})),
        )
        monkeypatch.setattr(buff_mod, "write_json_out", Mock())
        monkeypatch.setattr(buff_mod, "print_triage", Mock())
        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
        patch_buff_pr_resolution(monkeypatch, 85)
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=make_feedback_result(CheckStatus.PASSED)),
        )

        assert buff_mod.cmd_buff(args) == 0
        assert (
            "== Buff inspect: checking CI code-scanning results =="
            in capsys.readouterr().out
        )

    def test_cmd_buff_inspect_warns_on_pr_branch_mismatch(self, monkeypatch, capsys):
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
            "run_inspect_scan",
            Mock(return_value=(0, {"summary": {}, "actionable": [], "next_steps": []})),
        )
        monkeypatch.setattr(buff_mod, "write_json_out", Mock())
        monkeypatch.setattr(buff_mod, "print_triage", Mock())
        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
        patch_buff_pr_resolution(monkeypatch, 85)
        monkeypatch.setattr(
            buff_mod, "_get_current_branch", Mock(return_value="feat/perf-testing")
        )
        monkeypatch.setattr(
            buff_mod, "_get_pr_head_branch", Mock(return_value="feature/old-work")
        )
        monkeypatch.setattr(buff_mod, "_get_branch_pr_number", Mock(return_value=102))
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=make_feedback_result(CheckStatus.PASSED)),
        )

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert "Notice: buff is operating on a PR from a different branch." in out
        assert "feat/perf-testing" in out
        assert "feature/old-work" in out
        assert "#102" in out
        assert "sm buff 102" in out

    def test_cmd_buff_inspect_mismatch_no_branch_pr(self, monkeypatch, capsys):
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
            "run_inspect_scan",
            Mock(return_value=(0, {"summary": {}, "actionable": [], "next_steps": []})),
        )
        monkeypatch.setattr(buff_mod, "write_json_out", Mock())
        monkeypatch.setattr(buff_mod, "print_triage", Mock())
        monkeypatch.setattr(
            buff_mod, "_project_root_from_cwd", Mock(return_value="/repo")
        )
        patch_buff_pr_resolution(monkeypatch, 85)
        monkeypatch.setattr(
            buff_mod, "_get_current_branch", Mock(return_value="feat/perf-testing")
        )
        monkeypatch.setattr(
            buff_mod, "_get_pr_head_branch", Mock(return_value="feature/old-work")
        )
        monkeypatch.setattr(buff_mod, "_get_branch_pr_number", Mock(return_value=None))
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=make_feedback_result(CheckStatus.PASSED)),
        )

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert "Notice: buff is operating on a PR from a different branch." in out
        assert "Switch to the PR branch" in out
