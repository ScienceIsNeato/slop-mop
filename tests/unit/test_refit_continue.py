"""Unit tests for the refit iterate (continue) pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import Mock

from slopmop.cli import refit as refit_mod
from tests.conftest import fake_lock as _fake_lock  # shared no-op sm_lock


class TestCmdRefitContinue:
    def test_continue_requires_existing_plan(self, capsys, tmp_path: Path):
        args = argparse.Namespace(start=False, iterate=True, project_root=str(tmp_path))

        assert refit_mod.cmd_refit(args) == 1
        out = capsys.readouterr().out
        assert "No refit plan found" in out

    def test_continue_requires_existing_plan_json_output_emits_protocol(
        self, capsys, tmp_path: Path
    ):
        args = argparse.Namespace(
            start=False,
            iterate=True,
            project_root=str(tmp_path),
            json_output=True,
            output_file=None,
        )

        assert refit_mod.cmd_refit(args) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["event"] == "missing_plan"
        assert payload["status"] == "missing_plan"

    def test_continue_blocks_on_branch_drift(self, monkeypatch, capsys, tmp_path: Path):
        args = argparse.Namespace(start=False, iterate=True, project_root=str(tmp_path))
        monkeypatch.setattr(
            refit_mod,
            "_load_plan",
            Mock(
                return_value={
                    "branch": "feat/refit",
                    "expected_head": "abc123",
                    "current_index": 0,
                    "items": [{"gate": "laziness:repeated-code"}],
                }
            ),
        )
        monkeypatch.setattr(
            refit_mod, "_current_branch", Mock(return_value="other-branch")
        )

        assert refit_mod.cmd_refit(args) == 1
        out = capsys.readouterr().out
        assert "current branch no longer matches" in out

    def test_continue_stops_on_first_failure(self, monkeypatch, capsys, tmp_path: Path):
        args = argparse.Namespace(start=False, iterate=True, project_root=str(tmp_path))
        plan = {
            "project_root": str(tmp_path),
            "branch": "feat/refit",
            "expected_head": "abc123",
            "status": "ready",
            "current_index": 0,
            "items": [
                {
                    "gate": "laziness:repeated-code",
                    "status": "pending",
                    "attempt_count": 0,
                    "commit_message": "refactor(repeated-code): resolve remediation findings",
                    "log_file": None,
                }
            ],
        }
        saved = {}

        monkeypatch.setattr(refit_mod, "_load_plan", Mock(return_value=plan))
        monkeypatch.setattr(
            refit_mod,
            "_save_plan",
            lambda root, plan: saved.update({"plan": plan.copy()}),
        )
        monkeypatch.setattr(refit_mod, "_save_protocol", Mock())
        monkeypatch.setattr(
            refit_mod, "_current_branch", Mock(return_value="feat/refit")
        )
        monkeypatch.setattr(refit_mod, "_current_head", Mock(return_value="abc123"))
        monkeypatch.setattr(refit_mod, "_worktree_status", Mock(return_value=[]))
        monkeypatch.setattr(refit_mod, "_run_scour", Mock(return_value=1))
        monkeypatch.setattr(refit_mod, "sm_lock", _fake_lock)

        assert refit_mod.cmd_refit(args) == 1
        out = capsys.readouterr().out
        assert "Refit stopped on failing gate: laziness:repeated-code" in out
        assert saved["plan"]["status"] == "blocked_on_failure"

    def test_skip_marks_current_gate_and_advances(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        """--skip should mark status=skipped, record reason, and advance.

        Use case observed against manim: gate #2 has 162 jscpd findings,
        but gates #3-6 are quick wins. No way to park #2 and move on —
        plan is a strict queue. --skip unblocks the queue without
        pretending the gate passed.
        """
        args = argparse.Namespace(
            start=False,
            iterate=False,
            skip="162 findings, needs triage",
            project_root=str(tmp_path),
        )
        plan = {
            "project_root": str(tmp_path),
            "branch": "feat/refit",
            "expected_head": "abc123",
            "status": "blocked_on_failure",
            "current_index": 0,
            "current_gate": "myopia:source-duplication",
            "items": [
                {"gate": "myopia:source-duplication", "status": "blocked_on_failure"},
                {"gate": "laziness:dead-code", "status": "pending"},
            ],
        }
        saved = {}

        monkeypatch.setattr(refit_mod, "_load_plan", Mock(return_value=plan))
        monkeypatch.setattr(
            refit_mod,
            "_save_plan",
            lambda root, plan: saved.update({"plan": json.loads(json.dumps(plan))}),
        )
        monkeypatch.setattr(refit_mod, "_save_protocol", Mock())
        monkeypatch.setattr(
            refit_mod, "_ensure_remediation_phase", Mock(return_value=True)
        )
        monkeypatch.setattr(
            refit_mod, "_current_branch", Mock(return_value="feat/refit")
        )
        monkeypatch.setattr(refit_mod, "sm_lock", _fake_lock)

        assert refit_mod.cmd_refit(args) == 0
        out = capsys.readouterr().out
        assert "Skipped gate: myopia:source-duplication" in out
        assert "162 findings, needs triage" in out
        assert "Next gate: laziness:dead-code" in out
        # Plan state: item marked skipped, index advanced
        saved_plan = saved["plan"]
        assert saved_plan["items"][0]["status"] == "skipped"
        assert saved_plan["items"][0]["skip_reason"] == "162 findings, needs triage"
        assert saved_plan["current_index"] == 1
        assert saved_plan["current_gate"] == "laziness:dead-code"
        assert saved_plan["status"] == "ready"

    def test_skip_past_end_is_noop(self, monkeypatch, capsys, tmp_path: Path):
        args = argparse.Namespace(
            start=False, iterate=False, skip="manual skip", project_root=str(tmp_path)
        )
        plan = {
            "project_root": str(tmp_path),
            "status": "completed",
            "current_index": 1,
            "items": [{"gate": "x", "status": "completed"}],
        }
        monkeypatch.setattr(refit_mod, "_load_plan", Mock(return_value=plan))
        save_mock = Mock()
        monkeypatch.setattr(refit_mod, "_save_plan", save_mock)
        monkeypatch.setattr(refit_mod, "_save_protocol", Mock())
        monkeypatch.setattr(
            refit_mod, "_ensure_remediation_phase", Mock(return_value=True)
        )

        assert refit_mod.cmd_refit(args) == 0
        out = capsys.readouterr().out
        assert "No current gate to skip" in out
        save_mock.assert_not_called()

    def test_skipped_gate_renders_in_plan_summary(self):
        """Skipped items get a [~] marker and show their reason."""
        plan = {
            "schema": "refit/v2",
            "items": [
                {
                    "gate": "myopia:source-duplication",
                    "status": "skipped",
                    "skip_reason": "needs triage",
                    "phase_label": "Phase 1",
                    "verify_command": "sm scour",
                    "commit_message": "refactor: ...",
                },
                {
                    "gate": "laziness:dead-code",
                    "status": "completed",
                    "phase_label": "Phase 2",
                    "verify_command": "sm scour",
                    "commit_message": "fix: ...",
                },
            ],
        }
        summary = refit_mod._render_plan_summary(plan)
        assert "[~] myopia:source-duplication" in summary
        assert "skip reason: needs triage" in summary
        assert "[x] laziness:dead-code" in summary

    def test_continue_blocks_on_plan_corruption_when_gate_missing(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        args = argparse.Namespace(start=False, iterate=True, project_root=str(tmp_path))
        plan = {
            "project_root": str(tmp_path),
            "branch": "feat/refit",
            "expected_head": "abc123",
            "status": "ready",
            "current_index": 0,
            "items": [
                {
                    "status": "pending",
                    "attempt_count": 0,
                    "commit_message": "refactor(repeated-code): resolve remediation findings",
                    "log_file": None,
                }
            ],
        }
        saved = {}

        monkeypatch.setattr(refit_mod, "_load_plan", Mock(return_value=plan))
        monkeypatch.setattr(
            refit_mod,
            "_save_plan",
            lambda root, plan: saved.update({"plan": json.loads(json.dumps(plan))}),
        )
        monkeypatch.setattr(
            refit_mod, "_current_branch", Mock(return_value="feat/refit")
        )
        monkeypatch.setattr(refit_mod, "sm_lock", _fake_lock)

        assert refit_mod.cmd_refit(args) == 1
        payload = json.loads(
            (tmp_path / ".slopmop" / "refit" / "protocol.json").read_text(
                encoding="utf-8"
            )
        )
        assert payload["event"] == "blocked_on_plan_corruption"
        assert saved["plan"]["status"] == "blocked_on_plan_corruption"
        assert "current plan item has no gate" in capsys.readouterr().out

    def test_continue_blocks_when_git_status_cannot_be_read(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        args = argparse.Namespace(start=False, iterate=True, project_root=str(tmp_path))
        plan = {
            "project_root": str(tmp_path),
            "branch": "feat/refit",
            "expected_head": "abc123",
            "status": "ready",
            "current_index": 0,
            "items": [
                {
                    "gate": "laziness:repeated-code",
                    "status": "pending",
                    "attempt_count": 0,
                    "commit_message": "refactor(repeated-code): resolve remediation findings",
                    "log_file": None,
                }
            ],
        }

        monkeypatch.setattr(refit_mod, "_load_plan", Mock(return_value=plan))
        monkeypatch.setattr(
            refit_mod, "_current_branch", Mock(return_value="feat/refit")
        )
        monkeypatch.setattr(refit_mod, "_current_head", Mock(return_value="abc123"))
        monkeypatch.setattr(
            refit_mod,
            "_worktree_status",
            Mock(side_effect=RuntimeError("git status failed")),
        )
        monkeypatch.setattr(refit_mod, "sm_lock", _fake_lock)

        assert refit_mod.cmd_refit(args) == 1
        payload = json.loads(
            (tmp_path / ".slopmop" / "refit" / "protocol.json").read_text(
                encoding="utf-8"
            )
        )
        assert payload["event"] == "blocked_on_repo_state_error"
        assert "git status failed" in capsys.readouterr().out

    def test_continue_json_output_emits_protocol_payload(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        args = argparse.Namespace(
            start=False,
            iterate=True,
            project_root=str(tmp_path),
            json_output=True,
            output_file=None,
        )
        plan = {
            "project_root": str(tmp_path),
            "branch": "feat/refit",
            "expected_head": "abc123",
            "status": "ready",
            "current_index": 0,
            "current_gate": "laziness:repeated-code",
            "items": [
                {
                    "id": 1,
                    "gate": "laziness:repeated-code",
                    "status": "pending",
                    "attempt_count": 0,
                    "verify_command": "sm scour -g laziness:repeated-code --no-auto-fix",
                    "commit_message": "refactor(repeated-code): resolve remediation findings",
                    "log_file": None,
                }
            ],
        }

        monkeypatch.setattr(refit_mod, "_load_plan", Mock(return_value=plan))
        monkeypatch.setattr(refit_mod, "_save_plan", Mock())
        monkeypatch.setattr(refit_mod, "write_json_out", Mock())
        monkeypatch.setattr(
            refit_mod, "_current_branch", Mock(return_value="feat/refit")
        )
        monkeypatch.setattr(refit_mod, "_current_head", Mock(return_value="abc123"))
        monkeypatch.setattr(refit_mod, "_worktree_status", Mock(return_value=[]))
        monkeypatch.setattr(refit_mod, "_run_scour", Mock(return_value=1))
        monkeypatch.setattr(refit_mod, "sm_lock", _fake_lock)

        assert refit_mod.cmd_refit(args) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["event"] == "blocked_on_failure"
        assert payload["current_gate"] == "laziness:repeated-code"
        assert (
            payload["next_action"]
            == "Fix the failing gate, then rerun `sm refit --iterate`."
        )

    def test_continue_failure_writes_protocol_file_and_output_mirror(
        self, monkeypatch, tmp_path: Path
    ):
        output_file = tmp_path / "continue-out.json"
        args = argparse.Namespace(
            start=False,
            iterate=True,
            project_root=str(tmp_path),
            json_output=False,
            output_file=str(output_file),
        )
        plan = {
            "project_root": str(tmp_path),
            "branch": "feat/refit",
            "expected_head": "abc123",
            "status": "ready",
            "current_index": 0,
            "current_gate": "laziness:repeated-code",
            "items": [
                {
                    "id": 1,
                    "gate": "laziness:repeated-code",
                    "status": "pending",
                    "attempt_count": 0,
                    "verify_command": "sm scour -g laziness:repeated-code --no-auto-fix",
                    "commit_message": "refactor(repeated-code): resolve remediation findings",
                    "log_file": None,
                }
            ],
        }

        monkeypatch.setattr(refit_mod, "_load_plan", Mock(return_value=plan))
        monkeypatch.setattr(refit_mod, "_save_plan", Mock())
        monkeypatch.setattr(
            refit_mod, "_current_branch", Mock(return_value="feat/refit")
        )
        monkeypatch.setattr(refit_mod, "_current_head", Mock(return_value="abc123"))
        monkeypatch.setattr(refit_mod, "_worktree_status", Mock(return_value=[]))
        monkeypatch.setattr(refit_mod, "_run_scour", Mock(return_value=1))
        monkeypatch.setattr(refit_mod, "sm_lock", _fake_lock)

        assert refit_mod.cmd_refit(args) == 1
        protocol_path = tmp_path / ".slopmop" / "refit" / "protocol.json"
        assert protocol_path.exists()
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
        mirrored = json.loads(output_file.read_text(encoding="utf-8"))
        assert protocol["event"] == "blocked_on_failure"
        assert protocol["protocol_file"] == str(protocol_path)
        assert mirrored == protocol

    def test_continue_advances_without_commit_when_gate_already_passes(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        args = argparse.Namespace(start=False, iterate=True, project_root=str(tmp_path))
        plan = {
            "project_root": str(tmp_path),
            "branch": "feat/refit",
            "expected_head": "abc123",
            "status": "ready",
            "current_index": 0,
            "items": [
                {
                    "gate": "laziness:repeated-code",
                    "status": "pending",
                    "attempt_count": 0,
                    "commit_message": "refactor(repeated-code): resolve remediation findings",
                    "log_file": None,
                }
            ],
        }
        saves = []

        monkeypatch.setattr(refit_mod, "_load_plan", Mock(return_value=plan))
        monkeypatch.setattr(
            refit_mod,
            "_save_plan",
            lambda root, plan: saves.append(json.loads(json.dumps(plan))),
        )
        monkeypatch.setattr(refit_mod, "_save_protocol", Mock())
        monkeypatch.setattr(
            refit_mod, "_current_branch", Mock(return_value="feat/refit")
        )
        monkeypatch.setattr(refit_mod, "_current_head", Mock(return_value="abc123"))
        monkeypatch.setattr(refit_mod, "_worktree_status", Mock(return_value=[]))
        monkeypatch.setattr(refit_mod, "_run_scour", Mock(return_value=0))
        monkeypatch.setattr(refit_mod, "sm_lock", _fake_lock)

        assert refit_mod.cmd_refit(args) == 0
        out = capsys.readouterr().out
        assert "gate already passes with no new commit required" in out
        assert saves[-1]["status"] == "completed"

    def test_continue_commits_when_preexisting_fix_passes(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        """Gate in blocked state with pre-applied fix in worktree: commit it.

        When an item is in blocked_on_failure state, the agent is expected to
        commit dirty files — the dirty-entry guard must not fire here.
        """
        args = argparse.Namespace(start=False, iterate=True, project_root=str(tmp_path))
        plan = {
            "project_root": str(tmp_path),
            "branch": "feat/refit",
            "expected_head": "abc123",
            "status": "ready",
            "current_index": 0,
            "items": [
                {
                    "gate": "laziness:repeated-code",
                    "status": "blocked_on_failure",
                    "attempt_count": 1,
                    "commit_message": "refactor(repeated-code): resolve remediation findings",
                    "log_file": None,
                }
            ],
        }
        saves = []
        heads = iter(["abc123", "abc123", "abc123", "def456"])
        statuses = iter([[" M app.py"], [" M app.py"]])

        monkeypatch.setattr(refit_mod, "_load_plan", Mock(return_value=plan))
        monkeypatch.setattr(
            refit_mod,
            "_save_plan",
            lambda root, plan: saves.append(json.loads(json.dumps(plan))),
        )
        monkeypatch.setattr(refit_mod, "_save_protocol", Mock())
        monkeypatch.setattr(
            refit_mod, "_current_branch", Mock(return_value="feat/refit")
        )
        monkeypatch.setattr(
            refit_mod, "_current_head", Mock(side_effect=lambda _root: next(heads))
        )
        monkeypatch.setattr(
            refit_mod,
            "_worktree_status",
            Mock(side_effect=lambda _root: next(statuses)),
        )
        monkeypatch.setattr(refit_mod, "_run_scour", Mock(return_value=0))
        monkeypatch.setattr(
            refit_mod, "_commit_current_changes", Mock(return_value=(0, "committed"))
        )
        monkeypatch.setattr(refit_mod, "sm_lock", _fake_lock)

        assert refit_mod.cmd_refit(args) == 0
        out = capsys.readouterr().out
        assert "Refit committed laziness:repeated-code" in out
        assert saves[-1]["status"] == "completed"
        assert saves[-1]["items"][0]["commit_sha"] == "def456"

    def test_continue_blocks_when_worktree_changes_during_validation(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        """If the gate run changes the worktree unexpectedly, block.

        Item is in blocked_on_failure state (fix-and-retry flow), so the
        dirty-entry guard is bypassed, and the within-run change is the trigger.
        """
        args = argparse.Namespace(start=False, iterate=True, project_root=str(tmp_path))
        plan = {
            "project_root": str(tmp_path),
            "branch": "feat/refit",
            "expected_head": "abc123",
            "status": "ready",
            "current_index": 0,
            "items": [
                {
                    "gate": "laziness:repeated-code",
                    "status": "blocked_on_failure",
                    "attempt_count": 1,
                    "commit_message": "refactor(repeated-code): resolve remediation findings",
                    "log_file": None,
                }
            ],
        }
        saves = []
        statuses = iter([[" M app.py"], [" M app.py", " M other.py"]])

        monkeypatch.setattr(refit_mod, "_load_plan", Mock(return_value=plan))
        monkeypatch.setattr(
            refit_mod,
            "_save_plan",
            lambda root, plan: saves.append(json.loads(json.dumps(plan))),
        )
        monkeypatch.setattr(refit_mod, "_save_protocol", Mock())
        monkeypatch.setattr(
            refit_mod, "_current_branch", Mock(return_value="feat/refit")
        )
        monkeypatch.setattr(refit_mod, "_current_head", Mock(return_value="abc123"))
        monkeypatch.setattr(
            refit_mod,
            "_worktree_status",
            Mock(side_effect=lambda _root: next(statuses)),
        )
        monkeypatch.setattr(refit_mod, "_run_scour", Mock(return_value=0))
        monkeypatch.setattr(refit_mod, "sm_lock", _fake_lock)

        assert refit_mod.cmd_refit(args) == 1
        out = capsys.readouterr().out
        assert (
            "worktree changed during validation beyond the planned remediation edits"
            in out
        )
        assert saves[-1]["status"] == "blocked_on_dirty_worktree"

    def test_continue_advances_multi_item_plan_across_repeated_runs(
        self, monkeypatch, tmp_path: Path
    ):
        args = argparse.Namespace(
            start=False,
            iterate=True,
            project_root=str(tmp_path),
            json_output=False,
            output_file=None,
        )
        plan = {
            "schema": "refit/v1",
            "project_root": str(tmp_path),
            "branch": "feat/refit",
            "expected_head": "abc123",
            "status": "ready",
            "current_index": 0,
            "current_gate": "laziness:repeated-code",
            "items": [
                {
                    "id": 1,
                    "gate": "laziness:repeated-code",
                    "status": "pending",
                    "attempt_count": 0,
                    "verify_command": "sm scour -g laziness:repeated-code --no-auto-fix",
                    "commit_message": "refactor(repeated-code): resolve remediation findings",
                    "log_file": None,
                    "last_artifact": None,
                    "commit_sha": None,
                },
                {
                    "id": 2,
                    "gate": "overconfidence:coverage-gaps.py",
                    "status": "pending",
                    "attempt_count": 0,
                    "verify_command": "sm scour -g overconfidence:coverage-gaps.py --no-auto-fix",
                    "commit_message": "test(coverage-gaps.py): resolve remediation findings",
                    "log_file": None,
                    "last_artifact": None,
                    "commit_sha": None,
                },
            ],
        }
        refit_dir = tmp_path / ".slopmop" / "refit"
        refit_dir.mkdir(parents=True)
        plan_path = refit_dir / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")

        scour_results = iter([1, 0, 1, 0])
        scour_calls = []
        head_values = iter(
            [
                "abc123",
                "abc123",
                "abc123",
                "abc123",
                "abc123",  # post_drain_head after item0 drain (no drain commit)
                "def456",
                "def456",
                "def456",
                "def456",
                "def456",
            ]
        )
        status_values = iter(
            [
                [],
                [],
                [" M first.py"],
                [" M first.py"],
                [],
                [],
                [],
                [],
            ]
        )

        def _run_scour(_project_root, artifact_path, gate=None):
            scour_calls.append((gate, str(artifact_path)))
            return next(scour_results)

        def _commit_changes(_project_root, message):
            if "source-duplication" in message:
                return 0, "first commit"
            return 0, "second commit"

        monkeypatch.setattr(
            refit_mod, "_current_branch", Mock(return_value="feat/refit")
        )
        monkeypatch.setattr(
            refit_mod,
            "_current_head",
            Mock(side_effect=lambda _root: next(head_values)),
        )
        monkeypatch.setattr(
            refit_mod,
            "_worktree_status",
            Mock(side_effect=lambda _root: next(status_values)),
        )
        monkeypatch.setattr(refit_mod, "_run_scour", Mock(side_effect=_run_scour))
        monkeypatch.setattr(
            refit_mod, "_commit_current_changes", Mock(side_effect=_commit_changes)
        )
        monkeypatch.setattr(refit_mod, "sm_lock", _fake_lock)

        assert refit_mod.cmd_refit(args) == 1
        after_first = json.loads(plan_path.read_text(encoding="utf-8"))
        first_protocol = json.loads(
            (refit_dir / "protocol.json").read_text(encoding="utf-8")
        )

        assert after_first["status"] == "blocked_on_failure"
        assert after_first["current_index"] == 0
        assert after_first["current_gate"] == "laziness:repeated-code"
        assert after_first["items"][0]["status"] == "blocked_on_failure"
        assert after_first["items"][0]["attempt_count"] == 1
        assert first_protocol["event"] == "blocked_on_failure"
        assert first_protocol["current_index"] == 0
        assert first_protocol["current_gate"] == "laziness:repeated-code"
        assert first_protocol["current_item"]["gate"] == "laziness:repeated-code"

        assert refit_mod.cmd_refit(args) == 1
        after_second = json.loads(plan_path.read_text(encoding="utf-8"))
        second_protocol = json.loads(
            (refit_dir / "protocol.json").read_text(encoding="utf-8")
        )

        assert after_second["status"] == "blocked_on_failure"
        assert after_second["current_index"] == 1
        assert after_second["current_gate"] == "overconfidence:coverage-gaps.py"
        assert after_second["expected_head"] == "def456"
        assert after_second["items"][0]["status"] == "completed"
        assert after_second["items"][0]["attempt_count"] == 2
        assert after_second["items"][0]["commit_sha"] == "def456"
        assert after_second["items"][1]["status"] == "blocked_on_failure"
        assert after_second["items"][1]["attempt_count"] == 1
        assert second_protocol["event"] == "blocked_on_failure"
        assert second_protocol["current_index"] == 1
        assert second_protocol["current_gate"] == "overconfidence:coverage-gaps.py"
        assert (
            second_protocol["current_item"]["gate"] == "overconfidence:coverage-gaps.py"
        )

        assert refit_mod.cmd_refit(args) == 0
        after_third = json.loads(plan_path.read_text(encoding="utf-8"))
        third_protocol = json.loads(
            (refit_dir / "protocol.json").read_text(encoding="utf-8")
        )

        assert after_third["status"] == "completed"
        assert after_third["current_index"] == 2
        assert after_third["current_gate"] is None
        assert after_third["items"][1]["status"] == "completed_no_changes"
        assert after_third["items"][1]["attempt_count"] == 2
        assert third_protocol["event"] == "advanced_without_commit"
        assert third_protocol["status"] == "completed"
        assert third_protocol["current_index"] == 2
        assert third_protocol["current_gate"] is None
        assert "current_item" not in third_protocol
        assert [gate for gate, _artifact in scour_calls] == [
            "laziness:repeated-code",
            "laziness:repeated-code",
            "overconfidence:coverage-gaps.py",
            "overconfidence:coverage-gaps.py",
        ]

    def test_continue_accepts_head_drift_before_first_completed(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        """HEAD drift is accepted when no items have completed yet.

        After ``--start`` commits plan artifacts, the user runs
        ``--iterate`` and HEAD has changed.  Since no gates have
        completed, this is expected and the plan should be updated.
        """
        args = argparse.Namespace(start=False, iterate=True, project_root=str(tmp_path))
        plan = {
            "project_root": str(tmp_path),
            "branch": "feat/refit",
            "expected_head": "old_head",
            "status": "ready",
            "current_index": 0,
            "items": [
                {
                    "gate": "laziness:repeated-code",
                    "status": "pending",
                    "attempt_count": 0,
                    "commit_message": "refactor(repeated-code): resolve remediation findings",
                    "log_file": None,
                }
            ],
        }
        saved = {}

        monkeypatch.setattr(refit_mod, "_load_plan", Mock(return_value=plan))
        monkeypatch.setattr(
            refit_mod,
            "_save_plan",
            lambda root, p: saved.update({"plan": json.loads(json.dumps(p))}),
        )
        monkeypatch.setattr(refit_mod, "_save_protocol", Mock())
        monkeypatch.setattr(
            refit_mod, "_current_branch", Mock(return_value="feat/refit")
        )
        monkeypatch.setattr(refit_mod, "_current_head", Mock(return_value="new_head"))
        monkeypatch.setattr(refit_mod, "_worktree_status", Mock(return_value=[]))
        monkeypatch.setattr(refit_mod, "_run_scour", Mock(return_value=1))
        monkeypatch.setattr(refit_mod, "sm_lock", _fake_lock)

        assert refit_mod.cmd_refit(args) == 1
        # The plan's expected_head was updated to reflect the drift.
        assert saved["plan"]["expected_head"] == "new_head"
        # It didn't block — it proceeded to the gate (which failed).
        out = capsys.readouterr().out
        assert "Refit stopped on failing gate" in out

    def test_continue_accepts_head_drift_when_current_gate_is_blocked(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        """HEAD drift is accepted when the current item is in a blocked state.

        After a gate fails, the user fixes the issue and commits, then
        re-runs ``--iterate``.  HEAD naturally changes and should be accepted.
        """
        args = argparse.Namespace(start=False, iterate=True, project_root=str(tmp_path))
        plan = {
            "project_root": str(tmp_path),
            "branch": "feat/refit",
            "expected_head": "old_head",
            "status": "blocked_on_failure",
            "current_index": 0,
            "items": [
                {
                    "gate": "laziness:repeated-code",
                    "status": "blocked_on_failure",
                    "attempt_count": 1,
                    "commit_message": "refactor(repeated-code): resolve remediation findings",
                    "log_file": None,
                },
                {
                    "gate": "overconfidence:coverage-gaps.py",
                    "status": "completed",
                    "attempt_count": 1,
                    "commit_message": "test(coverage): fill coverage gaps",
                    "log_file": None,
                },
            ],
        }
        saved = {}

        monkeypatch.setattr(refit_mod, "_load_plan", Mock(return_value=plan))
        monkeypatch.setattr(
            refit_mod,
            "_save_plan",
            lambda root, p: saved.update({"plan": json.loads(json.dumps(p))}),
        )
        monkeypatch.setattr(refit_mod, "_save_protocol", Mock())
        monkeypatch.setattr(
            refit_mod, "_current_branch", Mock(return_value="feat/refit")
        )
        monkeypatch.setattr(refit_mod, "_current_head", Mock(return_value="new_head"))
        monkeypatch.setattr(refit_mod, "_worktree_status", Mock(return_value=[]))
        monkeypatch.setattr(refit_mod, "_run_scour", Mock(return_value=1))
        monkeypatch.setattr(refit_mod, "sm_lock", _fake_lock)

        assert refit_mod.cmd_refit(args) == 1
        # The plan's expected_head was updated despite completed items
        # because the *current* item is blocked.
        assert saved["plan"]["expected_head"] == "new_head"
        out = capsys.readouterr().out
        assert "Refit stopped on failing gate" in out

    # ------------------------------------------------------------------
    # _cmd_refit_finish
    # ------------------------------------------------------------------
    def test_finish_blocks_when_skipped_items_remain(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        """--finish must refuse when skipped items still exist."""
        args = argparse.Namespace(
            start=False,
            iterate=False,
            skip=None,
            finish=True,
            project_root=str(tmp_path),
        )
        plan = {
            "project_root": str(tmp_path),
            "branch": "feat/refit",
            "status": "completed",
            "current_index": 2,
            "current_gate": None,
            "items": [
                {
                    "gate": "myopia:source-duplication",
                    "status": "skipped",
                    "skip_reason": "too many findings",
                },
                {"gate": "laziness:dead-code", "status": "completed"},
            ],
        }
        monkeypatch.setattr(refit_mod, "_load_plan", Mock(return_value=plan))
        monkeypatch.setattr(refit_mod, "_save_protocol", Mock())
        monkeypatch.setattr(
            refit_mod, "_ensure_remediation_phase", Mock(return_value=True)
        )

        assert refit_mod.cmd_refit(args) == 1
        out = capsys.readouterr().out
        assert "Cannot finish" in out
        assert "1 skipped" in out
        assert "myopia:source-duplication" in out

    def test_finish_blocks_when_unresolved_items_remain(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        """--finish must refuse when unresolved (non-skipped) pending items exist."""
        args = argparse.Namespace(
            start=False,
            iterate=False,
            skip=None,
            finish=True,
            project_root=str(tmp_path),
        )
        plan = {
            "project_root": str(tmp_path),
            "branch": "feat/refit",
            "status": "ready",
            "current_index": 0,
            "current_gate": "myopia:source-duplication",
            "items": [
                {"gate": "myopia:source-duplication", "status": "blocked_on_failure"},
                {"gate": "laziness:dead-code", "status": "pending"},
            ],
        }
        monkeypatch.setattr(refit_mod, "_load_plan", Mock(return_value=plan))
        monkeypatch.setattr(refit_mod, "_save_protocol", Mock())
        monkeypatch.setattr(
            refit_mod, "_ensure_remediation_phase", Mock(return_value=True)
        )

        assert refit_mod.cmd_refit(args) == 1
        out = capsys.readouterr().out
        assert "Cannot finish" in out
        assert "2 unresolved" in out

    # ------------------------------------------------------------------
    # _cmd_refit_skip guard rails
    # ------------------------------------------------------------------
    def test_skip_blocked_when_not_remediation_phase(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        args = argparse.Namespace(
            start=False,
            iterate=False,
            skip="manual skip",
            project_root=str(tmp_path),
        )
        monkeypatch.setattr(
            refit_mod, "_ensure_remediation_phase", Mock(return_value=False)
        )
        monkeypatch.setattr(refit_mod, "_save_protocol", Mock())

        assert refit_mod.cmd_refit(args) == 1
        out = capsys.readouterr().out
        assert "remediation phase" in out
