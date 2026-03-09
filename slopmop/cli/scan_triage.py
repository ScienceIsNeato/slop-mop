"""Fast CI code-scan triage utilities for slop-mop.

This module powers both:
- `sm buff` (post-PR loop)
- `scripts/ci_scan_triage.py` (repo convenience wrapper)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, TypedDict, cast

from slopmop.reporting.rail import (
    default_next_steps,
    filter_actionable_rows,
    filter_hard_failures,
    format_actionable_line,
    normalize_actionable_row,
)

ARTIFACT_NAME = "slopmop-results"
ARTIFACT_JSON = "slopmop-results.json"
WORKFLOW_NAME = "slop-mop primary code scanning gate"
NO_COMPLETED_RUN_MSG = (
    "No completed runs found for that PR/workflow. Pass --run-id explicitly."
)


class TriageError(RuntimeError):
    """Raised when CI triage cannot complete."""


class _RunEntry(TypedDict, total=False):
    databaseId: int
    status: str
    conclusion: str
    createdAt: str
    name: str


class _WorkflowRunState(TypedDict):
    latest: _RunEntry
    latest_completed: _RunEntry


def _run_gh(args: list[str]) -> str:
    cmd = ["gh", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise TriageError(f"gh command failed: {' '.join(cmd)}\n{stderr}")
    return proc.stdout


def _run_local(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise TriageError(f"command failed: {' '.join(cmd)}\n{stderr}")
    return proc.stdout


def default_repo() -> str:
    out = _run_gh(["repo", "view", "--json", "nameWithOwner"])
    data = json.loads(out)
    repo = str(data.get("nameWithOwner") or "").strip()
    if not repo:
        raise TriageError("Could not resolve GitHub repository name.")
    return repo


def current_pr_number(repo: str) -> int:
    branch = _run_local(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if not branch:
        raise TriageError("Could not resolve current git branch.")

    out = _run_gh(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "number",
            "--limit",
            "1",
        ]
    )
    rows = json.loads(out)
    if not isinstance(rows, list) or not rows:
        raise TriageError("Could not resolve current PR number for this branch.")
    row_list: List[Any] = cast(List[Any], rows)
    first_raw = row_list[0]
    if not isinstance(first_raw, dict):
        raise TriageError("Unexpected response shape while resolving PR number.")
    first = cast(Dict[str, Any], first_raw)
    number = first.get("number")
    if not isinstance(number, int):
        raise TriageError("Could not resolve current PR number for this branch.")
    return number


def latest_completed_run_id(repo: str, pr_number: int, workflow: str) -> int:
    state = _workflow_run_state(repo, pr_number, workflow)
    run_id = state["latest_completed"].get("databaseId")
    if not isinstance(run_id, int):
        raise TriageError(NO_COMPLETED_RUN_MSG)
    return run_id


def _workflow_run_state(repo: str, pr_number: int, workflow: str) -> _WorkflowRunState:
    pr_out = _run_gh(
        [
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            "headRefName",
        ]
    )
    pr_data = json.loads(pr_out)
    branch = str(pr_data.get("headRefName") or "").strip()
    if not branch:
        raise TriageError(f"Could not resolve head branch for PR #{pr_number}.")

    out = _run_gh(
        [
            "run",
            "list",
            "--repo",
            repo,
            "--branch",
            branch,
            "--json",
            "databaseId,status,conclusion,createdAt,name",
            "--limit",
            "30",
        ]
    )
    runs_raw = json.loads(out)
    if not isinstance(runs_raw, list):
        raise TriageError("Unexpected response shape from gh run list.")
    run_list: List[Any] = cast(List[Any], runs_raw)
    runs: List[_RunEntry] = [
        cast(_RunEntry, r) for r in run_list if isinstance(r, dict)
    ]

    matched: List[_RunEntry] = []
    for run in runs:
        run_name = str(run.get("name") or "")
        if workflow in run_name:
            matched.append(run)

    if not matched:
        raise TriageError(
            "No workflow runs found for that PR/workflow. Pass --run-id explicitly."
        )

    latest = matched[0]

    latest_completed: _RunEntry | None = None
    for run in matched:
        if run.get("status") == "completed":
            latest_completed = run
            break

    if latest_completed is None:
        raise TriageError(NO_COMPLETED_RUN_MSG)

    return {
        "latest": latest,
        "latest_completed": latest_completed,
    }


def download_results_json(repo: str, run_id: int, artifact_name: str) -> Path:
    tmpdir = Path(tempfile.mkdtemp(prefix="slopmop_scan_triage_"))
    try:
        _run_gh(
            [
                "run",
                "download",
                str(run_id),
                "--repo",
                repo,
                "--name",
                artifact_name,
                "-D",
                str(tmpdir),
            ]
        )
        candidates = list(tmpdir.rglob(ARTIFACT_JSON))
        candidate = candidates[0] if candidates else None
        if candidate is None or not candidate.exists():
            raise TriageError(
                f"Artifact downloaded but {ARTIFACT_JSON} not found under {tmpdir}. "
                "Check artifact name or run ID."
            )

        stable_dir = Path(".slopmop")
        stable_dir.mkdir(parents=True, exist_ok=True)
        stable_path = stable_dir / "last_ci_scan_results.json"
        shutil.copyfile(candidate, stable_path)
        return stable_path
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise TriageError(f"Expected object at JSON root in {path}")
        return cast(dict[str, Any], loaded)
    except Exception as exc:
        raise TriageError(f"Could not parse JSON at {path}: {exc}") from exc


def _coverage_value(message: str) -> float | None:
    match = re.search(r"Coverage\s+([0-9]+(?:\.[0-9]+)?)%", message)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def build_triage_payload(
    doc: dict[str, Any],
    run_id: int,
    json_path: Path,
    show_low_coverage: bool,
    pr_number: int | None,
    ci_state: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    summary_raw = doc.get("summary")
    summary: Dict[str, Any] = (
        cast(Dict[str, Any], summary_raw) if isinstance(summary_raw, dict) else {}
    )

    results_raw = doc.get("results")
    results_list: List[Any] = (
        cast(List[Any], results_raw) if isinstance(results_raw, list) else []
    )
    results: List[Dict[str, Any]] = [
        cast(Dict[str, Any], r) for r in results_list if isinstance(r, dict)
    ]

    actionable = filter_actionable_rows(results)
    hard_failures = filter_hard_failures(actionable)

    payload: dict[str, Any] = {
        "schema": "slopmop/ci-triage/v1",
        "source": "code-scanning",
        "run_id": run_id,
        "artifact_json": str(json_path),
        "summary": {
            "failed": summary.get("failed", 0),
            "errors": summary.get("errors", 0),
            "warned": summary.get("warned", 0),
            "all_passed": summary.get("all_passed"),
        },
        "actionable": [],
        "hard_failures": [],
        "lowest_coverage": [],
        "next_steps": default_next_steps(pr_number),
    }

    if ci_state is not None:
        payload["ci_state"] = ci_state

    for row in actionable:
        payload["actionable"].append(normalize_actionable_row(row))

    for row in hard_failures:
        payload["hard_failures"].append(
            {
                "status": str(row.get("status", "unknown")).upper(),
                "gate": str(row.get("name", "unknown")),
                "error": row.get("error") or row.get("status_detail") or "",
            }
        )

    if show_low_coverage:
        low_coverage_rows: list[tuple[float, str]] = []
        for row in hard_failures:
            findings_raw = row.get("findings")
            findings: List[Any] = (
                cast(List[Any], findings_raw) if isinstance(findings_raw, list) else []
            )
            for finding in findings:
                if not isinstance(finding, dict):
                    continue
                finding_obj = cast(Dict[str, Any], finding)
                message = str(finding_obj.get("message", ""))
                file_path = str(finding_obj.get("file", ""))
                value = _coverage_value(message)
                if value is None:
                    continue
                low_coverage_rows.append((value, f"{file_path}: {message}"))

        if low_coverage_rows:
            low_coverage_rows.sort(key=lambda x: x[0])
            for value, text in low_coverage_rows[:12]:
                payload["lowest_coverage"].append(
                    {
                        "coverage_pct": round(value, 1),
                        "finding": text,
                    }
                )

    return payload, (1 if hard_failures else 0)


def print_triage(payload: dict[str, Any], show_low_coverage: bool) -> None:
    summary = payload["summary"]
    print(f"Run ID: {payload['run_id']}")
    print(f"Artifact JSON: {payload['artifact_json']}")
    print(
        "Summary: "
        f"failed={summary.get('failed', 0)} "
        f"errors={summary.get('errors', 0)} "
        f"warned={summary.get('warned', 0)} "
        f"all_passed={summary.get('all_passed')}"
    )

    ci_state_raw = payload.get("ci_state")
    if isinstance(ci_state_raw, dict):
        ci_state = cast(Dict[str, Any], ci_state_raw)
        latest_status = str(ci_state.get("latest_status") or "unknown")
        latest_id = str(ci_state.get("latest_run_id") or "unknown")
        triaged_id = str(ci_state.get("triaged_run_id") or "unknown")
        print(
            "CI State: "
            f"latest_run={latest_id} ({latest_status}) "
            f"triaged_run={triaged_id}"
        )
        note_raw = ci_state.get("note")
        if isinstance(note_raw, str) and note_raw:
            print(f"CI State Note: {note_raw}")

    actionable = cast(List[Dict[str, Any]], payload.get("actionable") or [])
    if not actionable:
        print("No actionable gate results found.")
        return

    print("\nActionable Gates:")
    for row in actionable:
        print(format_actionable_line(cast(Dict[str, str], row)))

    next_steps = cast(List[str], payload.get("next_steps") or [])
    if next_steps:
        print("\nNext Steps:")
        for idx, step in enumerate(next_steps, start=1):
            print(f"{idx}. {step}")

    if show_low_coverage and payload.get("lowest_coverage"):
        print("\nLowest Coverage Findings:")
        for row in payload["lowest_coverage"]:
            print(f"- {row['coverage_pct']:.1f}% :: {row['finding']}")


def write_json_out(path: str | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_triage(
    *,
    repo: str | None,
    run_id: int | None,
    pr_number: int | None,
    workflow: str,
    artifact: str,
    show_low_coverage: bool,
    json_out: str | None,
    print_output: bool,
) -> tuple[int, dict[str, Any] | None]:
    """Run CI scan triage and return (exit_code, payload)."""
    resolved_repo = repo or default_repo()
    resolved_run_id = run_id
    resolved_pr_number = pr_number
    ci_state: dict[str, Any] | None = None
    if resolved_run_id is None:
        resolved_pr = (
            pr_number if pr_number is not None else current_pr_number(resolved_repo)
        )
        resolved_pr_number = resolved_pr
        state = _workflow_run_state(resolved_repo, resolved_pr, workflow)

        latest = state["latest"]
        latest_completed = state["latest_completed"]

        triaged_run_id = latest_completed.get("databaseId")
        if not isinstance(triaged_run_id, int):
            raise TriageError(NO_COMPLETED_RUN_MSG)

        latest_run_id = latest.get("databaseId")
        latest_status = str(latest.get("status") or "unknown")

        triaged_is_latest = latest_run_id == triaged_run_id
        pending_newer_run = (not triaged_is_latest) and latest_status != "completed"

        note = ""
        if pending_newer_run:
            note = (
                "Using latest completed run while a newer CI run is still "
                f"{latest_status}. Re-run buff after that run completes."
            )
        elif not triaged_is_latest:
            note = (
                "Using latest completed run; newer completed run(s) may exist. "
                "Re-run buff to refresh."
            )

        ci_state = {
            "latest_run_id": latest_run_id,
            "latest_status": latest_status,
            "latest_conclusion": latest.get("conclusion"),
            "latest_created_at": latest.get("createdAt"),
            "triaged_run_id": triaged_run_id,
            "triaged_is_latest": triaged_is_latest,
            "pending_newer_run": pending_newer_run,
            "note": note,
        }

        resolved_run_id = triaged_run_id

    json_path = download_results_json(resolved_repo, resolved_run_id, artifact)
    doc = _load_json(json_path)
    payload, exit_code = build_triage_payload(
        doc,
        resolved_run_id,
        json_path,
        show_low_coverage,
        resolved_pr_number,
        ci_state,
    )
    if print_output:
        print_triage(payload, show_low_coverage)
    write_json_out(json_out, payload)
    return exit_code, payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=None, help="GitHub repo owner/name")
    parser.add_argument("--run-id", type=int, default=None)
    parser.add_argument("--pr", type=int, default=None)
    parser.add_argument("--workflow", default=WORKFLOW_NAME)
    parser.add_argument("--artifact", default=ARTIFACT_NAME)
    parser.add_argument("--show-low-coverage", action="store_true")
    parser.add_argument(
        "--json-out",
        default=".slopmop/last_ci_triage.json",
        help="Path for machine-readable triage payload (set empty string to disable)",
    )
    args = parser.parse_args(argv)

    try:
        exit_code, _ = run_triage(
            repo=args.repo,
            run_id=args.run_id,
            pr_number=args.pr,
            workflow=args.workflow,
            artifact=args.artifact,
            show_low_coverage=args.show_low_coverage,
            json_out=args.json_out or None,
            print_output=True,
        )
        return exit_code
    except TriageError as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
