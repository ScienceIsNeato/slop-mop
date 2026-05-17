"""Unit tests for buff inspect/status paths."""

from __future__ import annotations

import argparse
from unittest.mock import Mock

from slopmop.cli import buff as buff_mod
from slopmop.cli import buff_common as common_mod
from slopmop.cli import scan_triage as triage
from slopmop.core.result import CheckStatus
from tests.conftest import make_feedback_result


def patch_status_pr_resolution(monkeypatch, pr_number=85, source="explicit"):
    """Patch buff PR resolution for status/watch command tests."""

    resolver = Mock(return_value=(pr_number, source))
    monkeypatch.setattr(buff_mod, "resolve_pr_number_with_source", resolver)
    return resolver


class TestBuffStatusCommand:
    def test_get_current_branch_returns_branch(self, monkeypatch):
        monkeypatch.setattr(
            common_mod.subprocess,
            "run",
            Mock(return_value=Mock(returncode=0, stdout="feature/demo\n")),
        )

        assert buff_mod._get_current_branch(buff_mod.Path("/repo")) == "feature/demo"

    def test_get_current_branch_returns_none_on_command_failure(self, monkeypatch):
        monkeypatch.setattr(
            common_mod.subprocess,
            "run",
            Mock(return_value=Mock(returncode=1, stdout="")),
        )

        assert buff_mod._get_current_branch(buff_mod.Path("/repo")) is None

    def test_get_pr_head_branch_returns_branch(self, monkeypatch):
        monkeypatch.setattr(
            buff_mod.subprocess,
            "run",
            Mock(return_value=Mock(returncode=0, stdout='{"headRefName":"feat-x"}')),
        )

        assert buff_mod._get_pr_head_branch(buff_mod.Path("/repo"), 85) == "feat-x"

    def test_get_pr_head_branch_returns_none_on_invalid_json(self, monkeypatch):
        monkeypatch.setattr(
            buff_mod.subprocess,
            "run",
            Mock(return_value=Mock(returncode=0, stdout="not-json")),
        )

        assert buff_mod._get_pr_head_branch(buff_mod.Path("/repo"), 85) is None

    def test_cmd_buff_status_fires_buff_hook_on_clean_terminal_state(
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
        patch_status_pr_resolution(monkeypatch, 85)
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
            Mock(return_value=make_feedback_result(CheckStatus.PASSED)),
        )
        fire_hook = Mock()
        monkeypatch.setattr(buff_mod, "_fire_buff_hook", fire_hook)

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert "== Buff PR selection ==" in out
        assert "Selected PR: #85 (explicit)" in out
        assert "Overall PR state: CI clean - 1/1 checks completed successfully" in out
        assert (
            "Final PR state: clean - CI checks passed and PR feedback is resolved"
            in out
        )
        assert "CI CLEAN" in out
        fire_hook.assert_called_once_with(has_issues=False)

    def test_cmd_buff_status_fires_buff_hook_on_failed_terminal_state(
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
        patch_status_pr_resolution(monkeypatch, 85)
        monkeypatch.setattr(
            buff_mod,
            "_fetch_checks",
            Mock(
                return_value=(
                    [
                        {
                            "name": "Primary Code Scanning Gate (blocking)",
                            "bucket": "fail",
                            "state": "FAILURE",
                            "link": "https://example.test/check",
                        }
                    ],
                    "",
                )
            ),
        )
        fire_hook = Mock()
        monkeypatch.setattr(buff_mod, "_fire_buff_hook", fire_hook)

        assert buff_mod.cmd_buff(args) == 1
        out = capsys.readouterr().out
        assert "Primary Code Scanning Gate (blocking)" in out
        assert "failed" in out.lower()
        fire_hook.assert_called_once_with(has_issues=True)

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
            "resolve_pr_number_with_source",
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
        patch_status_pr_resolution(monkeypatch, 85)
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
                return_value=make_feedback_result(
                    CheckStatus.FAILED,
                    output="PR #85 has unresolved review threads.",
                )
            ),
        )

        assert buff_mod.cmd_buff(args) == 1
        out = capsys.readouterr().out
        assert "CI checks are clean, but unresolved PR review threads remain." in out
        assert "PR #85 has unresolved review threads." in out

    def test_cmd_buff_status_warns_on_pr_worktree_mismatch(self, monkeypatch, capsys):
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
        patch_status_pr_resolution(monkeypatch, 85)
        monkeypatch.setattr(buff_mod, "_get_current_branch", Mock(return_value="main"))
        monkeypatch.setattr(
            buff_mod, "_get_pr_head_branch", Mock(return_value="feature/pr-85")
        )
        monkeypatch.setattr(buff_mod, "_get_branch_pr_number", Mock(return_value=102))
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
            Mock(return_value=make_feedback_result(CheckStatus.PASSED)),
        )
        monkeypatch.setattr(buff_mod, "_fire_buff_hook", Mock())

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert "Notice: buff is operating on a PR from a different branch." in out
        assert "Current branch:" in out
        assert "main" in out
        assert "feature/pr-85" in out
        assert "#102" in out
        assert "sm buff 102" in out

    def test_cmd_buff_watch_waits_once_for_post_ci_feedback_settle(
        self, monkeypatch, capsys
    ):
        """Bugbot settle requires one extra poll wait after all CI checks complete.

        When Bugbot's completedAt is set (truly finished), the watch loop fires
        one settle sleep then runs the feedback gate once as the final verdict.
        """
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
        patch_status_pr_resolution(monkeypatch, 85)
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
                # completedAt set — Bugbot has truly finished
                "completedAt": "2026-03-18T12:00:00Z",
            },
        ]
        # Two fetches: settle wait, final check.
        fetch_checks = Mock(side_effect=[(checks, ""), (checks, "")])
        monkeypatch.setattr(buff_mod, "_fetch_checks", fetch_checks)
        feedback_gate = Mock(return_value=make_feedback_result(CheckStatus.PASSED))
        monkeypatch.setattr(buff_mod, "_run_pr_feedback_gate", feedback_gate)
        sleep_mock = Mock()
        monkeypatch.setattr(buff_mod.time, "sleep", sleep_mock)

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert "Waiting one extra interval for review feedback to settle" in out
        assert "CI CLEAN" in out
        # Two loop iterations, two fetch calls.
        assert fetch_checks.call_count == 2
        # Gate called once: final verdict only.
        assert feedback_gate.call_count == 1
        # One settle sleep.
        assert sum(1 for c in sleep_mock.call_args_list if c.args == (7,)) == 1
        sleep_mock.assert_called_with(7)

    def test_cmd_buff_watch_treats_bugbot_with_no_completed_at_as_in_progress(
        self, monkeypatch, capsys
    ):
        """Bugbot with no completedAt is still running — buff keeps polling.

        Root cause of the bug: Bugbot shows bucket=skipping/neutral before it
        has set completedAt, so it isn't actually done yet.  The fix is to
        treat neutral/skipping checks without completedAt as in_progress.
        """
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
        patch_status_pr_resolution(monkeypatch, 85)
        # First two polls: Bugbot has no completedAt — still in_progress
        in_flight_checks = [
            {
                "name": "Primary Code Scanning Gate (blocking)",
                "bucket": "pass",
                "state": "SUCCESS",
                "link": "https://example.test/check",
            },
            {
                "name": "Cursor Bugbot",
                "bucket": "skipping",
                "state": "NEUTRAL",
                "link": "https://cursor.com/docs/bugbot",
                # No completedAt — Bugbot hasn't finished yet
            },
        ]
        # Third poll: Bugbot sets completedAt — now truly done
        done_checks = [
            {
                "name": "Primary Code Scanning Gate (blocking)",
                "bucket": "pass",
                "state": "SUCCESS",
                "link": "https://example.test/check",
            },
            {
                "name": "Cursor Bugbot",
                "bucket": "skipping",
                "state": "NEUTRAL",
                "link": "https://cursor.com/docs/bugbot",
                "completedAt": "2026-03-18T12:00:00Z",
            },
        ]
        fetch_checks = Mock(
            side_effect=[
                (in_flight_checks, ""),  # poll 1: Bugbot in_progress
                (in_flight_checks, ""),  # poll 2: still in_progress
                (done_checks, ""),  # poll 3: Bugbot done — settle fires
                (done_checks, ""),  # poll 4: final gate check
            ]
        )
        monkeypatch.setattr(buff_mod, "_fetch_checks", fetch_checks)
        feedback_gate = Mock(return_value=make_feedback_result(CheckStatus.PASSED))
        monkeypatch.setattr(buff_mod, "_run_pr_feedback_gate", feedback_gate)
        sleep_mock = Mock()
        monkeypatch.setattr(buff_mod.time, "sleep", sleep_mock)

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert "CI CLEAN" in out
        # 4 fetches: 2 in_progress polls, settle, final
        assert fetch_checks.call_count == 4
        # Gate called once after settle
        assert feedback_gate.call_count == 1
        # 3 sleeps: 2 in_progress polls + 1 settle
        assert sum(1 for c in sleep_mock.call_args_list if c.args == (7,)) == 3

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
        patch_status_pr_resolution(monkeypatch, 85)
        monkeypatch.setattr(buff_mod, "_fetch_checks", Mock(return_value=([], "")))
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(
                return_value=make_feedback_result(
                    CheckStatus.FAILED,
                    output="PR #85 has unresolved review threads.",
                )
            ),
        )

        assert buff_mod.cmd_buff(args) == 1
        out = capsys.readouterr().out
        assert "no CI checks found, but unresolved PR review threads remain" in out
        assert "PR #85 has unresolved review threads." in out

    def test_cmd_buff_status_no_checks_clean_fires_success_hook(
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
        patch_status_pr_resolution(monkeypatch, 85)
        monkeypatch.setattr(buff_mod, "_fetch_checks", Mock(return_value=([], "")))
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=make_feedback_result(CheckStatus.PASSED)),
        )
        fire_hook = Mock()
        monkeypatch.setattr(buff_mod, "_fire_buff_hook", fire_hook)

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert "No CI checks found for this PR" in out
        fire_hook.assert_called_once_with(has_issues=False)

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
        patch_status_pr_resolution(monkeypatch, 85)
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
            Mock(return_value=make_feedback_result(CheckStatus.SKIPPED)),
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
        patch_status_pr_resolution(monkeypatch, 85)
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
                # completedAt set — Bugbot has truly finished
                "completedAt": "2026-03-18T12:00:00Z",
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
        # Sequence (single-phase settle with completedAt fix):
        # 1. passing → settle fires (Bugbot has completedAt), sleep1, settled=True
        # 2. failed+pending → reset settled=False, sleep2, continue
        # 3. passing → settle fires again (settled=False), sleep3, settled=True
        # 4. passing → final gate check → PASSED → success
        fetch_checks = Mock(
            side_effect=[
                (passing_checks, ""),
                (failed_pending_checks, ""),
                (passing_checks, ""),
                (passing_checks, ""),
            ]
        )
        monkeypatch.setattr(buff_mod, "_fetch_checks", fetch_checks)
        feedback_gate = Mock(return_value=make_feedback_result(CheckStatus.PASSED))
        monkeypatch.setattr(buff_mod, "_run_pr_feedback_gate", feedback_gate)
        sleep_mock = Mock()
        monkeypatch.setattr(buff_mod.time, "sleep", sleep_mock)

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert (
            out.count("Waiting one extra interval for review feedback to settle") == 2
        )
        assert fetch_checks.call_count == 4
        # Gate called once: final verdict only (no phase-2).
        assert feedback_gate.call_count == 1
        # 3 sleeps: settle, failed-reset, settle-again.
        assert sum(1 for c in sleep_mock.call_args_list if c.args == (7,)) == 3

    def test_cmd_buff_watch_fail_fast_exits_immediately(self, monkeypatch, capsys):
        args = argparse.Namespace(
            pr_or_action="watch",
            action_args=["85"],
            interval=7,
            fail_fast=True,
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
        patch_status_pr_resolution(monkeypatch, 85)
        checks = [
            {
                "name": "lint",
                "bucket": "fail",
                "state": "FAILURE",
                "link": "https://example.test/fail",
            },
            {
                "name": "build",
                "bucket": "pending",
                "state": "IN_PROGRESS",
                "link": "",
            },
        ]
        fetch_checks = Mock(return_value=(checks, ""))
        monkeypatch.setattr(buff_mod, "_fetch_checks", fetch_checks)
        sleep_mock = Mock()
        monkeypatch.setattr(buff_mod.time, "sleep", sleep_mock)

        assert buff_mod.cmd_buff(args) == 1
        out = capsys.readouterr().out
        assert "fail-fast" in out
        assert "SLOP IN CI" in out
        # Should NOT have slept — fail-fast exits immediately
        assert not any(c.args == (7,) for c in sleep_mock.call_args_list)
        assert fetch_checks.call_count == 1

    def test_cmd_buff_watch_retries_empty_checks(self, monkeypatch, capsys):
        args = argparse.Namespace(
            pr_or_action="watch",
            action_args=["85"],
            interval=5,
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
        patch_status_pr_resolution(monkeypatch, 85)
        passing_checks = [
            {
                "name": "lint",
                "bucket": "pass",
                "state": "SUCCESS",
                "link": "",
            },
        ]
        # First 2 polls return empty, third returns checks
        fetch_checks = Mock(side_effect=[([], ""), ([], ""), (passing_checks, "")])
        monkeypatch.setattr(buff_mod, "_fetch_checks", fetch_checks)
        feedback_gate = Mock(return_value=make_feedback_result(CheckStatus.PASSED))
        monkeypatch.setattr(buff_mod, "_run_pr_feedback_gate", feedback_gate)
        sleep_mock = Mock()
        monkeypatch.setattr(buff_mod.time, "sleep", sleep_mock)

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert "No CI checks registered yet" in out
        assert fetch_checks.call_count == 3
        assert sum(1 for c in sleep_mock.call_args_list if c.args == (5,)) == 2

    def test_cmd_buff_watch_shows_poll_counter(self, monkeypatch, capsys):
        args = argparse.Namespace(
            pr_or_action="watch",
            action_args=["85"],
            interval=5,
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
        patch_status_pr_resolution(monkeypatch, 85)
        pending = [
            {"name": "build", "bucket": "pending", "state": "PENDING", "link": ""}
        ]
        passing = [{"name": "build", "bucket": "pass", "state": "SUCCESS", "link": ""}]
        fetch_checks = Mock(side_effect=[(pending, ""), (passing, "")])
        monkeypatch.setattr(buff_mod, "_fetch_checks", fetch_checks)
        feedback_gate = Mock(return_value=make_feedback_result(CheckStatus.PASSED))
        monkeypatch.setattr(buff_mod, "_run_pr_feedback_gate", feedback_gate)
        sleep_mock = Mock()
        monkeypatch.setattr(buff_mod.time, "sleep", sleep_mock)

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert "Poll #2" in out
        assert "CI CLEAN" in out

    def test_cmd_buff_watch_shows_total_watch_time(self, monkeypatch, capsys):
        args = argparse.Namespace(
            pr_or_action="watch",
            action_args=["85"],
            interval=5,
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
        patch_status_pr_resolution(monkeypatch, 85)
        checks = [{"name": "lint", "bucket": "pass", "state": "SUCCESS", "link": ""}]
        monkeypatch.setattr(buff_mod, "_fetch_checks", Mock(return_value=(checks, "")))
        feedback_gate = Mock(return_value=make_feedback_result(CheckStatus.PASSED))
        monkeypatch.setattr(buff_mod, "_run_pr_feedback_gate", feedback_gate)

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert "Total watch time:" in out
