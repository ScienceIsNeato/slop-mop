"""Pure tests for refit integration scenario manifests and naming helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.integration.scenario_manifest import (
    SCENARIOS_DIR,
    ScenarioManifest,
    is_placeholder_sha,
    load_scenario_manifest,
    load_scenario_manifest_by_name,
    make_run_branch_name,
    manifest_uses_placeholder_shas,
    reserved_refs_for_scenario,
)


def _write_manifest(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _valid_manifest() -> dict[str, object]:
    return {
        "schema": "refit-integration/v1",
        "scenario": "happy-path-small",
        "secondary_repo_url": "https://github.com/ScienceIsNeato/bucket-o-slop.git",
        "fixture_base_sha": "1111111111111111111111111111111111111111",
        "scenario_branch": "scenario/refit/happy-path-small",
        "reserved_tags": [
            "scenario/refit/happy-path-small/base",
            "scenario/refit/happy-path-small/step-01",
            "scenario/refit/happy-path-small/step-02",
        ],
        "patch_ladder": [
            {
                "step": 1,
                "gate": "myopia:source-duplication",
                "from_sha": "1111111111111111111111111111111111111111",
                "to_sha": "2222222222222222222222222222222222222222",
                "expected_commit_subject": "refactor(source-duplication): resolve remediation findings",
            },
            {
                "step": 2,
                "gate": "overconfidence:coverage-gaps.py",
                "from_sha": "2222222222222222222222222222222222222222",
                "to_sha": "3333333333333333333333333333333333333333",
                "expected_commit_subject": "test(coverage-gaps.py): resolve remediation findings",
            },
        ],
        "cross_repo": {
            "scenario_id": "refit-happy-path-small",
            "slop_mop_tracking_issue": None,
            "secondary_repo_tracking_issue": None,
        },
    }


class TestScenarioManifestLoading:
    def test_loads_checked_in_manifest(self) -> None:
        manifest = load_scenario_manifest_by_name("happy-path-small")

        assert isinstance(manifest, ScenarioManifest)
        assert manifest.scenario == "happy-path-small"
        assert manifest.scenario_branch == "scenario/refit/happy-path-small"
        assert len(manifest.patch_ladder) == 3
        assert manifest.patch_ladder[0].gate == "myopia:source-duplication"
        assert manifest.cross_repo.scenario_id == "refit-happy-path-small"

    def test_rejects_non_contiguous_steps(self, tmp_path: Path) -> None:
        payload = _valid_manifest()
        payload["patch_ladder"] = [
            payload["patch_ladder"][0],
            {
                "step": 3,
                "gate": "overconfidence:coverage-gaps.py",
                "from_sha": "2222222222222222222222222222222222222222",
                "to_sha": "3333333333333333333333333333333333333333",
                "expected_commit_subject": "test(coverage-gaps.py): resolve remediation findings",
            },
        ]
        payload["reserved_tags"] = [
            "scenario/refit/happy-path-small/base",
            "scenario/refit/happy-path-small/step-01",
            "scenario/refit/happy-path-small/step-03",
        ]

        with pytest.raises(ValueError, match="contiguous"):
            load_scenario_manifest(_write_manifest(tmp_path, payload))

    def test_rejects_non_linear_patch_chain(self, tmp_path: Path) -> None:
        payload = _valid_manifest()
        payload["patch_ladder"][1][
            "from_sha"
        ] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

        with pytest.raises(ValueError, match="linear chain"):
            load_scenario_manifest(_write_manifest(tmp_path, payload))

    def test_rejects_branch_that_does_not_match_scenario(self, tmp_path: Path) -> None:
        payload = _valid_manifest()
        payload["scenario_branch"] = "scenario/refit/other-scenario"

        with pytest.raises(ValueError, match="scenario_branch must be"):
            load_scenario_manifest(_write_manifest(tmp_path, payload))

    def test_rejects_reserved_tags_that_do_not_match_steps(
        self, tmp_path: Path
    ) -> None:
        payload = _valid_manifest()
        payload["reserved_tags"] = [
            "scenario/refit/happy-path-small/base",
            "scenario/refit/happy-path-small/step-01",
        ]

        with pytest.raises(ValueError, match="reserved_tags must exactly match"):
            load_scenario_manifest(_write_manifest(tmp_path, payload))

    def test_rejects_cross_repo_scenario_id_mismatch(self, tmp_path: Path) -> None:
        payload = _valid_manifest()
        payload["cross_repo"]["scenario_id"] = "refit-other"

        with pytest.raises(ValueError, match="cross_repo.scenario_id"):
            load_scenario_manifest(_write_manifest(tmp_path, payload))

    def test_rejects_when_fixture_base_does_not_match_first_step(
        self, tmp_path: Path
    ) -> None:
        payload = _valid_manifest()
        payload["fixture_base_sha"] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

        with pytest.raises(ValueError, match="fixture_base_sha"):
            load_scenario_manifest(_write_manifest(tmp_path, payload))

    def test_missing_named_manifest_raises_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError, match="No scenario manifest found"):
            load_scenario_manifest_by_name("missing-scenario")


class TestBranchAndRefHelpers:
    def test_reserved_refs_for_scenario(self) -> None:
        assert reserved_refs_for_scenario("happy-path-small", 2) == (
            "scenario/refit/happy-path-small",
            "scenario/refit/happy-path-small/base",
            "scenario/refit/happy-path-small/step-01",
            "scenario/refit/happy-path-small/step-02",
        )

    def test_reserved_refs_reject_zero_steps(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            reserved_refs_for_scenario("happy-path-small", 0)

    def test_make_run_branch_name(self) -> None:
        branch = make_run_branch_name(
            "happy-path-small",
            "abcdef1234567890",
            "run01",
            now=datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
        )

        assert branch == "run/refit/happy-path-small/20260319-abcdef1-run01"

    def test_make_run_branch_name_rejects_invalid_run_id(self) -> None:
        with pytest.raises(ValueError, match="run_id"):
            make_run_branch_name("happy-path-small", "abcdef1", "Run_01")


class TestPlaceholderShaHelpers:
    def test_is_placeholder_sha_detects_repeated_digit_sha(self) -> None:
        assert is_placeholder_sha("1" * 40)
        assert is_placeholder_sha("a" * 40)
        assert not is_placeholder_sha("abcdef1234567890abcdef1234567890abcdef12")

    def test_manifest_uses_real_shas_for_checked_in_happy_path_manifest(self) -> None:
        manifest = load_scenario_manifest_by_name("happy-path-small")
        assert not manifest_uses_placeholder_shas(manifest)


def test_checked_in_manifest_directory_exists() -> None:
    assert SCENARIOS_DIR.is_dir()
