"""Real Docker-backed acceptance test for the deterministic refit scenario loop.

This test is intentionally self-skipping until the external fixture repo gains
the real scenario branch, reserved tags, and patch-ladder SHAs that match the
checked-in manifest. The test shape is still worth checking in now so the repo
already contains the intended acceptance criterion.
"""

from __future__ import annotations

import json

import pytest

from tests.integration.docker_manager import DockerManager
from tests.integration.scenario_manifest import (
    load_scenario_manifest_by_name,
    make_run_branch_name,
    manifest_uses_placeholder_shas,
)

_ok, _reason = DockerManager.prerequisites_met()
_manifest = load_scenario_manifest_by_name("happy-path-small")
_scenario_ready = not manifest_uses_placeholder_shas(_manifest)
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _ok, reason=_reason or "prerequisites not met"),
    pytest.mark.skipif(
        not _scenario_ready,
        reason=(
            "happy-path-small still uses placeholder SHAs; populate the real "
            "bucket-o-slop scenario branch/tags before running this acceptance test"
        ),
    ),
]


class TestRefitScenarioHappyPath:
    def test_refit_scenario_completes_end_to_end(self) -> None:
        run_branch = make_run_branch_name(
            _manifest.scenario,
            "abcdef1",
            "integration",
        )

        with DockerManager() as docker_manager:
            result = docker_manager.run_refit_scenario(
                branch=_manifest.scenario,
                scenario=_manifest.scenario,
                run_branch=run_branch,
                ref=_manifest.fixture_base_sha,
            )

        result.assert_prerequisites()
        if result.extracted is None:
            pytest.fail(
                "refit scenario driver did not produce a summary payload; "
                f"full run follows\n{result}"
            )

        summary = json.loads(result.extracted)
        expected_subjects = [
            step.expected_commit_subject for step in _manifest.patch_ladder
        ]

        assert result.exit_code == 0, result
        assert summary["schema"] == "refit-scenario-summary/v1"
        assert summary["scenario"] == _manifest.scenario
        assert summary["run_branch"] == run_branch
        assert summary["final_event"] == "completed"
        assert summary["final_status"] == "completed"
        assert summary["applied_steps"] == [
            step.gate for step in _manifest.patch_ladder
        ]
        assert summary["commit_subjects"] == expected_subjects
