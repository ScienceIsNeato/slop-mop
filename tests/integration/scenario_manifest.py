"""Scenario manifest helpers for higher-level refit integration tests.

These helpers define the machine-readable contract for the refit integration
harness: immutable scenario refs in the secondary repo plus a fresh per-run
writable branch and a patch ladder describing the ideal remediation steps.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

SCENARIO_MANIFEST_SCHEMA = "refit-integration/v1"
SCENARIOS_DIR = Path(__file__).parent / "scenarios"

_SCENARIO_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TAG_NAME_RE = re.compile(
    r"^scenario/refit/[a-z0-9]+(?:-[a-z0-9]+)*/(?:base|step-[0-9]{2})$"
)
_BRANCH_RE = re.compile(r"^scenario/refit/[a-z0-9]+(?:-[a-z0-9]+)*$")
_RUN_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class PatchStep:
    step: int
    gate: str
    from_sha: str
    to_sha: str
    expected_commit_subject: str


@dataclass(frozen=True)
class CrossRepoMetadata:
    scenario_id: str
    slop_mop_tracking_issue: Optional[str]
    secondary_repo_tracking_issue: Optional[str]


@dataclass(frozen=True)
class ScenarioManifest:
    schema: str
    scenario: str
    secondary_repo_url: str
    fixture_base_sha: str
    scenario_branch: str
    reserved_tags: tuple[str, ...]
    patch_ladder: tuple[PatchStep, ...]
    cross_repo: CrossRepoMetadata

    @property
    def manifest_path(self) -> Path:
        return SCENARIOS_DIR / f"{self.scenario}.json"


def _load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def _require_str(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _validate_sha(value: str, *, label: str) -> str:
    if not _SHA_RE.fullmatch(value):
        raise ValueError(f"{label} must be a full 40-character lowercase git SHA")
    return value


def _validate_scenario_name(name: str) -> str:
    if not _SCENARIO_NAME_RE.fullmatch(name):
        raise ValueError(
            "scenario must use lowercase kebab-case, for example 'happy-path-small'"
        )
    return name


def _validate_scenario_branch(name: str, branch: str) -> str:
    expected = f"scenario/refit/{name}"
    if branch != expected:
        raise ValueError(f"scenario_branch must be {expected!r}, got {branch!r}")
    if not _BRANCH_RE.fullmatch(branch):
        raise ValueError(
            f"scenario_branch is not a valid reserved scenario branch: {branch}"
        )
    return branch


def _validate_reserved_tags(
    name: str, raw_tags: Any, step_count: int
) -> tuple[str, ...]:
    if not isinstance(raw_tags, list) or not raw_tags:
        raise ValueError("reserved_tags must be a non-empty list of tag names")
    tags: list[str] = []
    expected_tags = [f"scenario/refit/{name}/base"] + [
        f"scenario/refit/{name}/step-{index:02d}" for index in range(1, step_count + 1)
    ]
    for raw_tag in raw_tags:
        tag = _require_str(raw_tag, label="reserved_tags[]")
        if not _TAG_NAME_RE.fullmatch(tag):
            raise ValueError(f"reserved tag has invalid format: {tag}")
        tags.append(tag)
    if tags != expected_tags:
        raise ValueError(
            "reserved_tags must exactly match the base tag followed by one tag per patch step"
        )
    return tuple(tags)


def _validate_patch_ladder(raw_steps: Any) -> tuple[PatchStep, ...]:
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("patch_ladder must be a non-empty list")

    steps: list[PatchStep] = []
    expected_step = 1
    seen_to_shas: set[str] = set()
    for raw_step in raw_steps:
        if not isinstance(raw_step, dict):
            raise ValueError("each patch_ladder item must be an object")
        step = raw_step.get("step")
        if not isinstance(step, int):
            raise ValueError("patch_ladder[].step must be an integer")
        if step != expected_step:
            raise ValueError(
                f"patch_ladder steps must start at 1 and be contiguous; expected {expected_step}, got {step}"
            )
        gate = _require_str(raw_step.get("gate"), label="patch_ladder[].gate")
        from_sha = _validate_sha(
            _require_str(raw_step.get("from_sha"), label="patch_ladder[].from_sha"),
            label="patch_ladder[].from_sha",
        )
        to_sha = _validate_sha(
            _require_str(raw_step.get("to_sha"), label="patch_ladder[].to_sha"),
            label="patch_ladder[].to_sha",
        )
        if from_sha == to_sha:
            raise ValueError(
                "patch_ladder step cannot use the same from_sha and to_sha"
            )
        if to_sha in seen_to_shas:
            raise ValueError(f"patch_ladder contains duplicate to_sha: {to_sha}")
        expected_commit_subject = _require_str(
            raw_step.get("expected_commit_subject"),
            label="patch_ladder[].expected_commit_subject",
        )
        steps.append(
            PatchStep(
                step=step,
                gate=gate,
                from_sha=from_sha,
                to_sha=to_sha,
                expected_commit_subject=expected_commit_subject,
            )
        )
        seen_to_shas.add(to_sha)
        expected_step += 1

    for previous, current in zip(steps, steps[1:]):
        if previous.to_sha != current.from_sha:
            raise ValueError(
                "patch_ladder must form a linear chain where each step's to_sha matches the next step's from_sha"
            )
    return tuple(steps)


def _validate_cross_repo(raw_cross_repo: Any, scenario: str) -> CrossRepoMetadata:
    if not isinstance(raw_cross_repo, dict):
        raise ValueError("cross_repo must be an object")
    scenario_id = _require_str(
        raw_cross_repo.get("scenario_id"), label="cross_repo.scenario_id"
    )
    expected_scenario_id = f"refit-{scenario}"
    if scenario_id != expected_scenario_id:
        raise ValueError(
            f"cross_repo.scenario_id must be {expected_scenario_id!r}, got {scenario_id!r}"
        )

    def _optional_string(key: str) -> Optional[str]:
        value = raw_cross_repo.get(key)
        if value is None:
            return None
        return _require_str(value, label=f"cross_repo.{key}")

    return CrossRepoMetadata(
        scenario_id=scenario_id,
        slop_mop_tracking_issue=_optional_string("slop_mop_tracking_issue"),
        secondary_repo_tracking_issue=_optional_string("secondary_repo_tracking_issue"),
    )


def load_scenario_manifest(path: Path) -> ScenarioManifest:
    data = _load_json_object(path)
    schema = _require_str(data.get("schema"), label="schema")
    if schema != SCENARIO_MANIFEST_SCHEMA:
        raise ValueError(f"schema must be {SCENARIO_MANIFEST_SCHEMA!r}, got {schema!r}")
    scenario = _validate_scenario_name(
        _require_str(data.get("scenario"), label="scenario")
    )
    secondary_repo_url = _require_str(
        data.get("secondary_repo_url"), label="secondary_repo_url"
    )
    fixture_base_sha = _validate_sha(
        _require_str(data.get("fixture_base_sha"), label="fixture_base_sha"),
        label="fixture_base_sha",
    )
    scenario_branch = _validate_scenario_branch(
        scenario,
        _require_str(data.get("scenario_branch"), label="scenario_branch"),
    )
    patch_ladder = _validate_patch_ladder(data.get("patch_ladder"))
    reserved_tags = _validate_reserved_tags(
        scenario,
        data.get("reserved_tags"),
        len(patch_ladder),
    )
    cross_repo = _validate_cross_repo(data.get("cross_repo"), scenario)
    if patch_ladder[0].from_sha != fixture_base_sha:
        raise ValueError(
            "fixture_base_sha must match the first patch_ladder step's from_sha"
        )
    return ScenarioManifest(
        schema=schema,
        scenario=scenario,
        secondary_repo_url=secondary_repo_url,
        fixture_base_sha=fixture_base_sha,
        scenario_branch=scenario_branch,
        reserved_tags=reserved_tags,
        patch_ladder=patch_ladder,
        cross_repo=cross_repo,
    )


def load_scenario_manifest_by_name(scenario: str) -> ScenarioManifest:
    name = _validate_scenario_name(scenario)
    path = SCENARIOS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"No scenario manifest found for {name!r}: {path}")
    return load_scenario_manifest(path)


def reserved_refs_for_scenario(scenario: str, step_count: int) -> tuple[str, ...]:
    name = _validate_scenario_name(scenario)
    if step_count < 1:
        raise ValueError("step_count must be at least 1")
    refs = [f"scenario/refit/{name}", f"scenario/refit/{name}/base"]
    refs.extend(
        f"scenario/refit/{name}/step-{index:02d}" for index in range(1, step_count + 1)
    )
    return tuple(refs)


def make_run_branch_name(
    scenario: str,
    slopmop_sha: str,
    run_id: str,
    now: Optional[datetime] = None,
) -> str:
    name = _validate_scenario_name(scenario)
    sha = _require_str(slopmop_sha, label="slopmop_sha")
    if not re.fullmatch(r"[0-9a-f]{7,40}", sha):
        raise ValueError("slopmop_sha must be a 7-40 character lowercase hex SHA")
    normalized_run_id = _require_str(run_id, label="run_id")
    if not _RUN_ID_RE.fullmatch(normalized_run_id):
        raise ValueError("run_id must use lowercase kebab-case")
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d")
    return f"run/refit/{name}/{stamp}-{sha[:7]}-{normalized_run_id}"


def is_placeholder_sha(sha: str) -> bool:
    return bool(_SHA_RE.fullmatch(sha)) and len(set(sha)) == 1


def manifest_uses_placeholder_shas(manifest: ScenarioManifest) -> bool:
    if is_placeholder_sha(manifest.fixture_base_sha):
        return True
    return any(
        is_placeholder_sha(step.from_sha) or is_placeholder_sha(step.to_sha)
        for step in manifest.patch_ladder
    )
