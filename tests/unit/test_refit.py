"""Unit tests for the refit remediation rail."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from slopmop.checks.base import RemediationChurn
from slopmop.cli import refit as refit_mod
from slopmop.doctor.base import DoctorResult, DoctorStatus


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
                            "name": "laziness:repeated-code",
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
            "laziness:repeated-code",
            "repeated-code",
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
            "laziness:repeated-code",
            "overconfidence:coverage-gaps.py",
        ]
        assert plan["items"][0]["commit_message"].startswith("refactor(repeated-code)")
        assert plan["items"][1]["commit_message"].startswith("test(coverage-gaps.py)")


class TestCommitKindForCheck:
    """Commit type prefix derivation for auto-commits."""

    def _check(self, churn: RemediationChurn):
        fake = SimpleNamespace(remediation_churn=churn)
        return fake

    def test_dependency_risk_gets_fix_not_test(self):
        """bandit annotations are security fixes, not tests.

        Observed against manim: auto-commit for 7 bandit nosec annotations
        was `test(dependency-risk.py): ...`. dependency-risk.py lives under
        myopia: (not security:) and has DOWNSTREAM_CHANGES_UNLIKELY, so it
        fell through the keyword matches to the churn fallback → "test".
        """
        kind = refit_mod._commit_kind_for_check(
            "myopia:dependency-risk.py",
            self._check(RemediationChurn.DOWNSTREAM_CHANGES_UNLIKELY),
        )
        assert kind == "fix"

    def test_repeated_code_gets_refactor(self):
        kind = refit_mod._commit_kind_for_check(
            "myopia:repeated-code",
            self._check(RemediationChurn.DOWNSTREAM_CHANGES_VERY_LIKELY),
        )
        assert kind == "refactor"

    def test_unknown_unlikely_churn_falls_through_to_test(self):
        """The churn fallback still applies for truly unknown gates."""
        kind = refit_mod._commit_kind_for_check(
            "myopia:some-novel-gate",
            self._check(RemediationChurn.DOWNSTREAM_CHANGES_UNLIKELY),
        )
        assert kind == "test"


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
                    "items": [{"gate": "laziness:repeated-code"}],
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
        assert saved["plan"]["items"][0]["gate"] == "laziness:repeated-code"

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
                    "current_gate": "laziness:repeated-code",
                    "items": [
                        {
                            "id": 1,
                            "gate": "laziness:repeated-code",
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
        assert payload["current_gate"] == "laziness:repeated-code"

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
                    "current_gate": "laziness:repeated-code",
                    "items": [
                        {
                            "id": 1,
                            "gate": "laziness:repeated-code",
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
        # Two-step add: first -u (tracked), then -A --ignore-errors (new)
        assert captured_args[0] == ["git", "add", "-u"]
        assert captured_args[1] == ["git", "add", "-A", "--ignore-errors"]


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
            gate="laziness:repeated-code",
        )

        assert exit_code == 0
        assert captured["cwd"] == tmp_path
        assert captured["env"]["SLOPMOP_SKIP_REPO_LOCK"] == "1"
        assert captured["env"]["SLOPMOP_NESTED_VALIDATE_OWNER"] == "refit"
        assert captured["capture_output"] is True
        assert captured["text"] is True
        assert captured["check"] is False
        assert "--no-auto-fix" in captured["command"]
        assert captured["command"][-2:] == ["-g", "laziness:repeated-code"]


class TestDoctorPreflight:
    def test_run_doctor_preflight_passes_when_no_failures(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        import slopmop.doctor as doctor_mod

        def _fake_run_checks(ctx, patterns):
            assert ctx.project_root == tmp_path
            assert tuple(patterns) == refit_mod._DOCTOR_PREFLIGHT_CHECKS
            return [
                DoctorResult(
                    name="state.lock",
                    status=DoctorStatus.OK,
                    summary="no lock held",
                ),
                DoctorResult(
                    name="project.python_venv",
                    status=DoctorStatus.WARN,
                    summary="no local venv",
                ),
            ]

        monkeypatch.setattr(doctor_mod, "run_checks", _fake_run_checks)

        ok, detail = refit_mod._run_doctor_preflight(tmp_path)
        assert ok is True
        assert "doctor preflight passed" in detail

    def test_run_doctor_preflight_fails_when_any_check_fails(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        import slopmop.doctor as doctor_mod

        def _fake_run_checks(ctx, patterns):
            assert ctx.project_root == tmp_path
            assert tuple(patterns) == refit_mod._DOCTOR_PREFLIGHT_CHECKS
            return [
                DoctorResult(
                    name="sm_env.tool_inventory",
                    status=DoctorStatus.FAIL,
                    summary="2 tool(s) missing",
                ),
                DoctorResult(
                    name="state.lock",
                    status=DoctorStatus.OK,
                    summary="no lock held",
                ),
            ]

        monkeypatch.setattr(doctor_mod, "run_checks", _fake_run_checks)

        ok, detail = refit_mod._run_doctor_preflight(tmp_path)
        assert ok is False
        assert "doctor preflight failed" in detail
        assert "sm_env.tool_inventory" in detail
        assert "Run `sm doctor" in detail


class TestInitArtifactsBlockRefit:
    """sm init artifacts must surface as dirty and block refit --start.

    This is the EXPECTED behavior: sm init creates files that must be
    committed before sm refit --start can proceed.  The worktree check must
    NOT filter them out — doing so would silently ignore uncommitted config
    that belongs under version control.
    """

    def test_sb_config_json_not_filtered_as_slopmop_artifact(self):
        """.sb_config.json must show as dirty — refit blocks until committed."""
        assert not refit_mod._is_slopmop_artifact("?? .sb_config.json"), (
            ".sb_config.json was incorrectly filtered as a slopmop artifact. "
            "It must show as dirty so refit --start blocks until it is committed."
        )

    def test_sb_config_template_not_filtered_as_slopmop_artifact(self):
        """.sb_config.json.template must show as dirty — refit blocks until committed."""
        assert not refit_mod._is_slopmop_artifact("?? .sb_config.json.template"), (
            ".sb_config.json.template was incorrectly filtered as a slopmop artifact. "
            "It must show as dirty so refit --start blocks until it is committed."
        )

    def test_gitignore_modification_not_filtered_as_slopmop_artifact(self):
        """.gitignore modification must show as dirty — refit blocks until committed."""
        assert not refit_mod._is_slopmop_artifact("M  .gitignore"), (
            ".gitignore was incorrectly filtered as a slopmop artifact. "
            "It must show as dirty so refit --start blocks until it is committed."
        )

    def test_worktree_status_returns_sm_init_files_not_slopmop_dir(self, monkeypatch):
        """_worktree_status surfaces sm init files while still filtering .slopmop/."""
        sm_init_output = (
            "?? .sb_config.json\n"
            "?? .sb_config.json.template\n"
            "M  .gitignore\n"
            " M .slopmop/refit/plan.json\n"
        )
        monkeypatch.setattr(
            refit_mod,
            "_git_output",
            Mock(return_value=(0, sm_init_output, "")),
        )
        status = refit_mod._worktree_status(Path("/fake"))

        assert "?? .sb_config.json" in status
        assert "?? .sb_config.json.template" in status
        assert "M  .gitignore" in status
        assert not any(".slopmop" in line for line in status)
