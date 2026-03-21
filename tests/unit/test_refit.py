"""Unit tests for the refit remediation rail."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from slopmop.checks.base import RemediationChurn
from slopmop.cli import refit as refit_mod


class _FakeCheck:
    def __init__(
        self,
        full_name: str,
        display_name: str,
        churn: RemediationChurn,
    ) -> None:
        self.full_name = full_name
        self.display_name = display_name
        self.remediation_churn = churn


class _FakeRegistry:
    def __init__(self, checks_by_name, ordered_checks, priorities, sources) -> None:
        self._checks_by_name = checks_by_name
        self._ordered_checks = ordered_checks
        self._priorities = priorities
        self._sources = sources

    def get_check(self, name, _config):
        return self._checks_by_name.get(name)

    def sort_checks_for_remediation(self, _checks):
        return self._ordered_checks

    def remediation_priority_for_check(self, check):
        return self._priorities[check.full_name]

    def remediation_priority_source_for_check(self, check):
        return self._sources[check.full_name]


class TestBuildPlan:
    def test_build_plan_orders_failed_gates_and_derives_commit_messages(
        self, monkeypatch, tmp_path: Path
    ):
        scour_path = tmp_path / ".slopmop" / "refit" / "initial_scour.json"
        scour_path.parent.mkdir(parents=True)
        scour_path.write_text(
            json.dumps(
                {
                    "results": [
                        {
                            "name": "overconfidence:coverage-gaps.py",
                            "status": "failed",
                            "output": "coverage missing",
                        },
                        {
                            "name": "myopia:source-duplication",
                            "status": "failed",
                            "output": "duplicate code",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / ".sb_config.json").write_text("{}", encoding="utf-8")

        structural = _FakeCheck(
            "myopia:source-duplication",
            "source-duplication",
            RemediationChurn.DOWNSTREAM_CHANGES_VERY_LIKELY,
        )
        coverage = _FakeCheck(
            "overconfidence:coverage-gaps.py",
            "coverage-gaps.py",
            RemediationChurn.DOWNSTREAM_CHANGES_UNLIKELY,
        )
        registry = _FakeRegistry(
            checks_by_name={
                structural.full_name: structural,
                coverage.full_name: coverage,
            },
            ordered_checks=[structural, coverage],
            priorities={
                structural.full_name: 20,
                coverage.full_name: 110,
            },
            sources={
                structural.full_name: "curated",
                coverage.full_name: "churn-default",
            },
        )

        monkeypatch.setattr(refit_mod, "ensure_checks_registered", Mock())
        monkeypatch.setattr(refit_mod, "register_custom_gates", Mock())
        monkeypatch.setattr(refit_mod, "get_registry", Mock(return_value=registry))
        monkeypatch.setattr(
            refit_mod, "_current_branch", Mock(return_value="feat/refit")
        )
        monkeypatch.setattr(refit_mod, "_current_head", Mock(return_value="abc123"))

        plan = refit_mod._build_plan(tmp_path, scour_path)

        assert plan["branch"] == "feat/refit"
        assert plan["expected_head"] == "abc123"
        assert [item["gate"] for item in plan["items"]] == [
            "myopia:source-duplication",
            "overconfidence:coverage-gaps.py",
        ]
        assert plan["items"][0]["commit_message"].startswith(
            "refactor(source-duplication)"
        )
        assert plan["items"][1]["commit_message"].startswith("test(coverage-gaps.py)")


class TestCmdRefitGeneratePlan:
    def test_generate_plan_requires_clean_worktree(self, monkeypatch, capsys, tmp_path):
        args = argparse.Namespace(start=True, iterate=False, project_root=str(tmp_path))
        (tmp_path / ".sb_config.json").write_text("{}", encoding="utf-8")

        monkeypatch.setattr(
            refit_mod, "_run_doctor_preflight", Mock(return_value=(True, "ok"))
        )
        monkeypatch.setattr(
            refit_mod, "_worktree_status", Mock(return_value=[" M app.py"])
        )

        assert refit_mod.cmd_refit(args) == 1
        out = capsys.readouterr().out
        assert "working tree is not clean" in out

    def test_generate_plan_missing_init_json_output_emits_protocol(
        self, capsys, tmp_path: Path
    ):
        args = argparse.Namespace(
            start=True,
            iterate=False,
            project_root=str(tmp_path),
            json_output=True,
            output_file=None,
        )

        assert refit_mod.cmd_refit(args) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["event"] == "preflight_missing_init"
        assert payload["status"] == "preflight_missing_init"

    def test_generate_plan_runs_scour_and_persists_plan(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        args = argparse.Namespace(start=True, iterate=False, project_root=str(tmp_path))
        (tmp_path / ".sb_config.json").write_text("{}", encoding="utf-8")

        saved = {}
        monkeypatch.setattr(
            refit_mod, "_run_doctor_preflight", Mock(return_value=(True, "ok"))
        )
        monkeypatch.setattr(refit_mod, "_worktree_status", Mock(return_value=[]))
        monkeypatch.setattr(refit_mod, "_run_scour", Mock(return_value=1))
        monkeypatch.setattr(
            refit_mod,
            "_build_plan",
            Mock(
                return_value={
                    "project_root": str(tmp_path),
                    "schema": "refit/v1",
                    "generated_at": "now",
                    "branch": "feat/refit",
                    "expected_head": "abc123",
                    "status": "ready",
                    "current_index": 0,
                    "items": [{"gate": "myopia:source-duplication"}],
                }
            ),
        )
        monkeypatch.setattr(
            refit_mod,
            "_save_plan",
            lambda root, plan: saved.update({"root": root, "plan": plan}),
        )
        monkeypatch.setattr(refit_mod, "_save_protocol", Mock())

        assert refit_mod.cmd_refit(args) == 0
        out = capsys.readouterr().out
        assert "Refit plan generated." in out
        assert saved["root"] == tmp_path
        assert saved["plan"]["items"][0]["gate"] == "myopia:source-duplication"

    def test_generate_plan_json_output_emits_protocol_payload(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        args = argparse.Namespace(
            start=True,
            iterate=False,
            project_root=str(tmp_path),
            json_output=True,
            output_file=None,
        )
        (tmp_path / ".sb_config.json").write_text("{}", encoding="utf-8")

        monkeypatch.setattr(
            refit_mod, "_run_doctor_preflight", Mock(return_value=(True, "ok"))
        )
        monkeypatch.setattr(refit_mod, "_worktree_status", Mock(return_value=[]))
        monkeypatch.setattr(refit_mod, "_run_scour", Mock(return_value=1))
        monkeypatch.setattr(
            refit_mod,
            "_build_plan",
            Mock(
                return_value={
                    "project_root": str(tmp_path),
                    "schema": "refit/v1",
                    "generated_at": "now",
                    "branch": "feat/refit",
                    "expected_head": "abc123",
                    "status": "ready",
                    "current_index": 0,
                    "current_gate": "myopia:source-duplication",
                    "items": [
                        {
                            "id": 1,
                            "gate": "myopia:source-duplication",
                            "status": "pending",
                        }
                    ],
                }
            ),
        )
        monkeypatch.setattr(refit_mod, "write_json_out", Mock())

        assert refit_mod.cmd_refit(args) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["event"] == "plan_generated"
        assert payload["current_gate"] == "myopia:source-duplication"

    def test_generate_plan_writes_protocol_file_and_output_mirror(
        self, monkeypatch, tmp_path: Path
    ):
        output_file = tmp_path / "refit-out.json"
        args = argparse.Namespace(
            start=True,
            iterate=False,
            project_root=str(tmp_path),
            json_output=False,
            output_file=str(output_file),
        )
        (tmp_path / ".sb_config.json").write_text("{}", encoding="utf-8")

        monkeypatch.setattr(
            refit_mod, "_run_doctor_preflight", Mock(return_value=(True, "ok"))
        )
        monkeypatch.setattr(refit_mod, "_worktree_status", Mock(return_value=[]))
        monkeypatch.setattr(refit_mod, "_run_scour", Mock(return_value=1))
        monkeypatch.setattr(
            refit_mod,
            "_build_plan",
            Mock(
                return_value={
                    "project_root": str(tmp_path),
                    "schema": "refit/v1",
                    "generated_at": "now",
                    "branch": "feat/refit",
                    "expected_head": "abc123",
                    "status": "ready",
                    "current_index": 0,
                    "current_gate": "myopia:source-duplication",
                    "items": [
                        {
                            "id": 1,
                            "gate": "myopia:source-duplication",
                            "status": "pending",
                        }
                    ],
                }
            ),
        )

        assert refit_mod.cmd_refit(args) == 0
        protocol_path = tmp_path / ".slopmop" / "refit" / "protocol.json"
        assert protocol_path.exists()
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
        mirrored = json.loads(output_file.read_text(encoding="utf-8"))
        assert protocol["event"] == "plan_generated"
        assert protocol["protocol_file"] == str(protocol_path)
        assert mirrored == protocol


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
                    "items": [{"gate": "myopia:source-duplication"}],
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
                    "gate": "myopia:source-duplication",
                    "status": "pending",
                    "attempt_count": 0,
                    "commit_message": "refactor(source-duplication): resolve remediation findings",
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
        assert "Refit stopped on failing gate: myopia:source-duplication" in out
        assert saved["plan"]["status"] == "blocked_on_failure"

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
                    "commit_message": "refactor(source-duplication): resolve remediation findings",
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
                    "gate": "myopia:source-duplication",
                    "status": "pending",
                    "attempt_count": 0,
                    "commit_message": "refactor(source-duplication): resolve remediation findings",
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
            "current_gate": "myopia:source-duplication",
            "items": [
                {
                    "id": 1,
                    "gate": "myopia:source-duplication",
                    "status": "pending",
                    "attempt_count": 0,
                    "verify_command": "sm scour -g myopia:source-duplication --no-auto-fix",
                    "commit_message": "refactor(source-duplication): resolve remediation findings",
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
        assert payload["current_gate"] == "myopia:source-duplication"
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
            "current_gate": "myopia:source-duplication",
            "items": [
                {
                    "id": 1,
                    "gate": "myopia:source-duplication",
                    "status": "pending",
                    "attempt_count": 0,
                    "verify_command": "sm scour -g myopia:source-duplication --no-auto-fix",
                    "commit_message": "refactor(source-duplication): resolve remediation findings",
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
                    "gate": "myopia:source-duplication",
                    "status": "pending",
                    "attempt_count": 0,
                    "commit_message": "refactor(source-duplication): resolve remediation findings",
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
        args = argparse.Namespace(start=False, iterate=True, project_root=str(tmp_path))
        plan = {
            "project_root": str(tmp_path),
            "branch": "feat/refit",
            "expected_head": "abc123",
            "status": "ready",
            "current_index": 0,
            "items": [
                {
                    "gate": "myopia:source-duplication",
                    "status": "pending",
                    "attempt_count": 0,
                    "commit_message": "refactor(source-duplication): resolve remediation findings",
                    "log_file": None,
                }
            ],
        }
        saves = []
        heads = iter(["abc123", "abc123", "def456"])
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
        assert "Refit committed myopia:source-duplication" in out
        assert saves[-1]["status"] == "completed"
        assert saves[-1]["items"][0]["commit_sha"] == "def456"

    def test_continue_blocks_when_worktree_changes_during_validation(
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
                    "gate": "myopia:source-duplication",
                    "status": "pending",
                    "attempt_count": 0,
                    "commit_message": "refactor(source-duplication): resolve remediation findings",
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
            "current_gate": "myopia:source-duplication",
            "items": [
                {
                    "id": 1,
                    "gate": "myopia:source-duplication",
                    "status": "pending",
                    "attempt_count": 0,
                    "verify_command": "sm scour -g myopia:source-duplication --no-auto-fix",
                    "commit_message": "refactor(source-duplication): resolve remediation findings",
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
        assert after_first["current_gate"] == "myopia:source-duplication"
        assert after_first["items"][0]["status"] == "blocked_on_failure"
        assert after_first["items"][0]["attempt_count"] == 1
        assert first_protocol["event"] == "blocked_on_failure"
        assert first_protocol["current_index"] == 0
        assert first_protocol["current_gate"] == "myopia:source-duplication"
        assert first_protocol["current_item"]["gate"] == "myopia:source-duplication"

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
            "myopia:source-duplication",
            "myopia:source-duplication",
            "overconfidence:coverage-gaps.py",
            "overconfidence:coverage-gaps.py",
        ]


class TestIsSlopmopArtifact:
    def test_filters_slopmop_directory(self):
        assert refit_mod._is_slopmop_artifact(" M .slopmop/refit/plan.json") is True

    def test_filters_added_slopmop_file(self):
        assert refit_mod._is_slopmop_artifact("?? .slopmop/") is True

    def test_passes_through_normal_files(self):
        assert refit_mod._is_slopmop_artifact("M  src/main.py") is False

    def test_handles_short_lines(self):
        assert refit_mod._is_slopmop_artifact("M") is False

    def test_handles_rename_to_slopmop(self):
        assert refit_mod._is_slopmop_artifact("R  old.txt -> .slopmop/new.txt") is True

    def test_handles_rename_from_slopmop(self):
        assert refit_mod._is_slopmop_artifact("R  .slopmop/old.txt -> new.txt") is False


class TestWorktreeStatusFiltersSlopmop:
    def test_filters_slopmop_artifacts(self, monkeypatch):
        monkeypatch.setattr(
            refit_mod,
            "_git_output",
            Mock(return_value=(0, " M .slopmop/refit/plan.json\nM  src/main.py\n", "")),
        )
        status = refit_mod._worktree_status(Path("/fake"))
        assert status == ["M  src/main.py"]

    def test_returns_empty_when_only_slopmop_changes(self, monkeypatch):
        monkeypatch.setattr(
            refit_mod,
            "_git_output",
            Mock(return_value=(0, " M .slopmop/refit/plan.json\n?? .slopmop/\n", "")),
        )
        status = refit_mod._worktree_status(Path("/fake"))
        assert status == []


class TestCommitCurrentChanges:
    def test_git_add_excludes_slopmop_directory(self, monkeypatch, tmp_path: Path):
        captured_args: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            captured_args.append(list(cmd))
            result = Mock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        monkeypatch.setattr(refit_mod.subprocess, "run", fake_run)
        code, _ = refit_mod._commit_current_changes(tmp_path, "test commit")

        assert code == 0
        git_add_cmd = captured_args[0]
        assert git_add_cmd == ["git", "add", "-A", "--", ".", ":!.slopmop"]


class TestRunScour:
    def test_run_scour_sets_internal_lock_bypass_env(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        artifact_path = tmp_path / ".slopmop" / "refit" / "gate.json"
        captured = {}

        def _fake_run(command, cwd, env, capture_output, text, check):
            captured["command"] = command
            captured["cwd"] = cwd
            captured["env"] = env
            captured["capture_output"] = capture_output
            captured["text"] = text
            captured["check"] = check
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(refit_mod.subprocess, "run", _fake_run)

        exit_code = refit_mod._run_scour(
            tmp_path,
            artifact_path,
            gate="myopia:source-duplication",
        )

        assert exit_code == 0
        assert captured["cwd"] == tmp_path
        assert captured["env"]["SLOPMOP_SKIP_REPO_LOCK"] == "1"
        assert captured["env"]["SLOPMOP_NESTED_VALIDATE_OWNER"] == "refit"
        assert captured["capture_output"] is True
        assert captured["text"] is True
        assert captured["check"] is False
        assert captured["command"][-2:] == ["-g", "myopia:source-duplication"]


class _FakeLock:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return False


def _fake_lock(_project_root, _verb):
    return _FakeLock()
