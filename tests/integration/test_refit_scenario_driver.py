"""Pure tests for the deterministic refit scenario driver."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.integration.refit_scenario_driver import (
    ScenarioDriverError,
    apply_patch_step,
    assert_clean_worktree,
    execute_refit_scenario,
    load_protocol,
)
from tests.integration.scenario_manifest import load_scenario_manifest_by_name


class TestLoadProtocol:
    def test_load_protocol_reads_refit_protocol_file(self, tmp_path: Path) -> None:
        protocol_path = tmp_path / ".slopmop" / "refit" / "protocol.json"
        protocol_path.parent.mkdir(parents=True)
        protocol_path.write_text(json.dumps({"event": "completed"}), encoding="utf-8")

        payload = load_protocol(tmp_path)

        assert payload["event"] == "completed"

    def test_load_protocol_requires_existing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ScenarioDriverError, match="protocol file missing"):
            load_protocol(tmp_path)


class TestAssertCleanWorktree:
    def test_ignores_slopmop_internal_artifacts(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver._git_status",
            Mock(return_value=["?? .slopmop/", "?? .slopmop/refit/protocol.json"]),
        )

        assert_clean_worktree(tmp_path, label="after refit")

    def test_rejects_non_slopmop_drift(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver._git_status",
            Mock(
                return_value=["?? src/new_file.py", "?? .slopmop/refit/protocol.json"]
            ),
        )

        with pytest.raises(ScenarioDriverError, match="src/new_file.py"):
            assert_clean_worktree(tmp_path, label="after refit")


class TestApplyPatchStep:
    def test_apply_patch_step_builds_diff_and_applies_it(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        manifest = load_scenario_manifest_by_name("happy-path-small")
        calls = []

        def _run_checked(args, *, cwd, input_text=None, label):
            calls.append((args, input_text, label))
            if args[:3] == ["git", "diff", "--binary"]:
                return type("Result", (), {"stdout": "patch-data"})()
            return type("Result", (), {"stdout": ""})()

        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver._run_checked",
            _run_checked,
        )

        apply_patch_step(tmp_path, manifest.patch_ladder[0])

        assert calls[0][0] == [
            "git",
            "diff",
            "--binary",
            manifest.patch_ladder[0].from_sha,
            manifest.patch_ladder[0].to_sha,
        ]
        assert calls[1][0] == ["git", "apply", "--3way", "--whitespace=nowarn"]
        assert calls[1][1] == "patch-data"


class TestExecuteRefitScenario:
    def test_execute_refit_scenario_applies_steps_until_complete(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        manifest = load_scenario_manifest_by_name("happy-path-small")
        continue_responses = iter(
            [
                (
                    1,
                    {
                        "event": "blocked_on_failure",
                        "current_gate": manifest.patch_ladder[0].gate,
                        "branch": "run/refit/happy-path-small/20260319-abcdef1-run01",
                    },
                ),
                (
                    1,
                    {
                        "event": "blocked_on_failure",
                        "current_gate": manifest.patch_ladder[1].gate,
                        "branch": "run/refit/happy-path-small/20260319-abcdef1-run01",
                    },
                ),
                (0, {"event": "completed", "status": "completed"}),
            ]
        )
        applied = []

        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.fetch_reserved_refs",
            Mock(),
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.verify_reserved_refs",
            Mock(),
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.prepare_run_branch",
            Mock(),
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.run_refit_generate_plan",
            Mock(return_value=(0, {"event": "plan_generated"})),
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.run_refit_continue",
            Mock(side_effect=lambda _cwd: next(continue_responses)),
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.apply_patch_step",
            Mock(side_effect=lambda _cwd, step: applied.append(step.gate)),
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.assert_clean_worktree",
            Mock(),
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.load_protocol",
            Mock(return_value={"event": "completed", "status": "completed"}),
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver._git_stdout",
            Mock(
                side_effect=[
                    "run/refit/happy-path-small/20260319-abcdef1-run01",
                    "third\nsecond\nfirst",
                ]
            ),
        )

        summary = execute_refit_scenario(
            tmp_path,
            manifest,
            "run/refit/happy-path-small/20260319-abcdef1-run01",
        )

        assert summary["final_event"] == "completed"
        assert summary["applied_steps"] == [
            manifest.patch_ladder[0].gate,
            manifest.patch_ladder[1].gate,
        ]
        assert summary["commit_subjects"] == ["first", "second", "third"]

    def test_execute_refit_scenario_rejects_unexpected_protocol_event(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        manifest = load_scenario_manifest_by_name("happy-path-small")

        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.fetch_reserved_refs", Mock()
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.verify_reserved_refs", Mock()
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.prepare_run_branch", Mock()
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.run_refit_generate_plan",
            Mock(return_value=(0, {"event": "plan_generated"})),
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.run_refit_continue",
            Mock(
                return_value=(
                    0,
                    {"event": "committed", "branch": "run/refit/happy-path-small/x"},
                )
            ),
        )

        with pytest.raises(
            ScenarioDriverError, match="blocked_on_failure or completed"
        ):
            execute_refit_scenario(tmp_path, manifest, "run/refit/happy-path-small/x")

    def test_execute_refit_scenario_rejects_gate_mismatch(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        manifest = load_scenario_manifest_by_name("happy-path-small")

        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.fetch_reserved_refs", Mock()
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.verify_reserved_refs", Mock()
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.prepare_run_branch", Mock()
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.run_refit_generate_plan",
            Mock(return_value=(0, {"event": "plan_generated"})),
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.run_refit_continue",
            Mock(
                return_value=(
                    1,
                    {
                        "event": "blocked_on_failure",
                        "current_gate": "wrong:gate",
                        "branch": "run/refit/happy-path-small/x",
                    },
                )
            ),
        )

        with pytest.raises(ScenarioDriverError, match="protocol gate mismatch"):
            execute_refit_scenario(tmp_path, manifest, "run/refit/happy-path-small/x")

    def test_execute_refit_scenario_rejects_branch_mismatch(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        manifest = load_scenario_manifest_by_name("happy-path-small")

        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.fetch_reserved_refs", Mock()
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.verify_reserved_refs", Mock()
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.prepare_run_branch", Mock()
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.run_refit_generate_plan",
            Mock(return_value=(0, {"event": "plan_generated"})),
        )
        monkeypatch.setattr(
            "tests.integration.refit_scenario_driver.run_refit_continue",
            Mock(
                return_value=(
                    1,
                    {
                        "event": "blocked_on_failure",
                        "current_gate": manifest.patch_ladder[0].gate,
                        "branch": "other-branch",
                    },
                )
            ),
        )

        with pytest.raises(ScenarioDriverError, match="protocol branch mismatch"):
            execute_refit_scenario(tmp_path, manifest, "run/refit/happy-path-small/x")
