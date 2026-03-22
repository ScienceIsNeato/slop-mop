"""Deterministic driver for higher-level refit integration scenarios.

This module is designed to run inside the integration container against the
secondary fixture repo. It treats `.slopmop/refit/protocol.json` as the agent
contract, applies ideal remediation patches from the scenario manifest, and
hands control back to `sm refit --iterate` until the plan completes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Optional

from slopmop.cli.refit import _is_slopmop_artifact

try:
    from tests.integration.scenario_manifest import (
        PatchStep,
        ScenarioManifest,
        load_scenario_manifest_by_name,
    )
except ImportError:  # pragma: no cover - direct script execution inside container
    from scenario_manifest import (
        PatchStep,
        ScenarioManifest,
        load_scenario_manifest_by_name,
    )


class ScenarioDriverError(RuntimeError):
    """Raised when the integration scenario contract is violated."""


def _run_command(
    args: list[str],
    *,
    cwd: Path,
    input_text: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_checked(
    args: list[str],
    *,
    cwd: Path,
    input_text: Optional[str] = None,
    label: str,
) -> subprocess.CompletedProcess[str]:
    result = _run_command(args, cwd=cwd, input_text=input_text)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ScenarioDriverError(f"{label} failed: {detail or result.returncode}")
    return result


def _git_stdout(cwd: Path, *args: str, label: str) -> str:
    result = _run_checked(["git", *args], cwd=cwd, label=label)
    return result.stdout.strip()


def _git_status(cwd: Path) -> list[str]:
    result = _run_command(["git", "status", "--porcelain"], cwd=cwd)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ScenarioDriverError(f"git status failed: {detail or result.returncode}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def assert_clean_worktree(cwd: Path, *, label: str) -> None:
    status = [line for line in _git_status(cwd) if not _is_slopmop_artifact(line)]
    if status:
        raise ScenarioDriverError(
            f"worktree must be clean {label}; found: {' | '.join(status)}"
        )


def fetch_reserved_refs(cwd: Path, manifest: ScenarioManifest) -> None:
    fetch_args = ["git", "fetch", "origin", manifest.scenario_branch]
    fetch_args.extend(
        f"refs/tags/{tag}:refs/tags/{tag}" for tag in manifest.reserved_tags
    )
    _run_checked(fetch_args, cwd=cwd, label="fetch reserved refs")


def verify_reserved_refs(cwd: Path, manifest: ScenarioManifest) -> None:
    remote_branch_ref = f"refs/remotes/origin/{manifest.scenario_branch}"
    branch_sha = _git_stdout(
        cwd,
        "rev-parse",
        remote_branch_ref,
        label="resolve scenario branch ref",
    )
    if not branch_sha:
        raise ScenarioDriverError("scenario branch ref resolved to an empty SHA")

    for tag, expected_sha in zip(
        manifest.reserved_tags,
        [manifest.fixture_base_sha, *[step.to_sha for step in manifest.patch_ladder]],
    ):
        tag_sha = _git_stdout(
            cwd, "rev-parse", f"refs/tags/{tag}", label=f"resolve tag {tag}"
        )
        if tag_sha != expected_sha:
            raise ScenarioDriverError(
                f"reserved tag {tag} does not match manifest: expected {expected_sha}, got {tag_sha}"
            )


def prepare_run_branch(cwd: Path, manifest: ScenarioManifest, run_branch: str) -> None:
    assert_clean_worktree(cwd, label="before creating run branch")
    _run_checked(
        ["git", "checkout", "--detach", manifest.fixture_base_sha],
        cwd=cwd,
        label="checkout fixture base",
    )
    _run_checked(
        ["git", "checkout", "-B", run_branch, manifest.fixture_base_sha],
        cwd=cwd,
        label="create run branch",
    )
    current_branch = _git_stdout(
        cwd, "branch", "--show-current", label="read current branch"
    )
    if current_branch != run_branch:
        raise ScenarioDriverError(
            f"expected active branch {run_branch!r}, found {current_branch!r}"
        )


def load_protocol(cwd: Path) -> dict[str, Any]:
    path = cwd / ".slopmop" / "refit" / "protocol.json"
    if not path.exists():
        raise ScenarioDriverError(f"refit protocol file missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ScenarioDriverError(f"expected protocol JSON object in {path}")
    return payload


def _run_refit_command(cwd: Path, *args: str) -> tuple[int, dict[str, Any]]:
    result = _run_command(["sm", "refit", *args], cwd=cwd)
    return result.returncode, load_protocol(cwd)


def run_refit_start(cwd: Path) -> tuple[int, dict[str, Any]]:
    return _run_refit_command(cwd, "--start", "--json")


def run_refit_iterate(cwd: Path) -> tuple[int, dict[str, Any]]:
    return _run_refit_command(cwd, "--iterate", "--json")


def apply_patch_step(cwd: Path, step: PatchStep) -> None:
    diff_result = _run_checked(
        ["git", "diff", "--binary", step.from_sha, step.to_sha],
        cwd=cwd,
        label=f"build patch for {step.gate}",
    )
    _run_checked(
        ["git", "apply", "--3way", "--whitespace=nowarn"],
        cwd=cwd,
        input_text=diff_result.stdout,
        label=f"apply patch for {step.gate}",
    )


def commit_subjects_since(cwd: Path, base_sha: str) -> list[str]:
    output = _git_stdout(
        cwd,
        "log",
        "--format=%s",
        f"{base_sha}..HEAD",
        label="read commit subjects",
    )
    if not output:
        return []
    return output.splitlines()


def execute_refit_scenario(
    cwd: Path,
    manifest: ScenarioManifest,
    run_branch: str,
) -> dict[str, Any]:
    fetch_reserved_refs(cwd, manifest)
    verify_reserved_refs(cwd, manifest)
    prepare_run_branch(cwd, manifest, run_branch)

    plan_code, plan_protocol = run_refit_start(cwd)
    if plan_code != 0 or plan_protocol.get("event") != "plan_generated":
        raise ScenarioDriverError(
            f"expected plan_generated from refit plan generation, got exit {plan_code} and event {plan_protocol.get('event')!r}"
        )

    applied_steps: list[str] = []
    iteration_count = 0
    while True:
        iteration_count += 1
        continue_code, protocol = run_refit_iterate(cwd)
        event = str(protocol.get("event"))
        if continue_code == 0 and event == "completed":
            break

        if continue_code != 1 or event != "blocked_on_failure":
            raise ScenarioDriverError(
                f"expected blocked_on_failure or completed, got exit {continue_code} and event {event!r}"
            )

        step_index = len(applied_steps)
        if step_index >= len(manifest.patch_ladder):
            raise ScenarioDriverError(
                "protocol requested more remediation steps than the scenario manifest defines"
            )

        expected_step = manifest.patch_ladder[step_index]
        current_gate = str(protocol.get("current_gate"))
        current_branch = str(protocol.get("branch"))
        if current_branch != run_branch:
            raise ScenarioDriverError(
                f"protocol branch mismatch: expected {run_branch!r}, got {current_branch!r}"
            )
        if current_gate != expected_step.gate:
            raise ScenarioDriverError(
                f"protocol gate mismatch: expected {expected_step.gate!r}, got {current_gate!r}"
            )

        assert_clean_worktree(
            cwd, label=f"before applying patch for {expected_step.gate}"
        )
        apply_patch_step(cwd, expected_step)
        applied_steps.append(expected_step.gate)

    final_protocol = load_protocol(cwd)
    final_branch = _git_stdout(
        cwd, "branch", "--show-current", label="read final branch"
    )
    if final_branch != run_branch:
        raise ScenarioDriverError(
            f"final branch mismatch: expected {run_branch!r}, got {final_branch!r}"
        )
    assert_clean_worktree(cwd, label="after scenario completion")

    subjects = list(reversed(commit_subjects_since(cwd, manifest.fixture_base_sha)))
    return {
        "schema": "refit-scenario-summary/v1",
        "scenario": manifest.scenario,
        "run_branch": run_branch,
        "final_event": final_protocol.get("event"),
        "final_status": final_protocol.get("status"),
        "iterations": iteration_count,
        "applied_steps": applied_steps,
        "commit_subjects": subjects,
        "protocol_file": str(cwd / ".slopmop" / "refit" / "protocol.json"),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute a deterministic refit integration scenario"
    )
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--run-branch", required=True)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--summary-file")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    cwd = Path(args.project_root).resolve()
    manifest = load_scenario_manifest_by_name(args.scenario)
    summary = execute_refit_scenario(cwd, manifest, args.run_branch)
    text = json.dumps(summary, indent=2, sort_keys=True)
    if args.summary_file:
        Path(args.summary_file).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via direct script execution
    raise SystemExit(main())
