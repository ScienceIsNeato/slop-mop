"""Structured remediation for onboarding repositories into slop-mop.

`sm refit` turns open-ended remediation into a deterministic plan-and-execute
loop:
- `sm refit --start` captures the current failing scour gates and
  persists a one-gate-at-a-time plan.
- `sm refit --iterate` resumes that plan, rerunning the current gate,
  auto-committing when it passes, and stopping on the first blocker.
- `sm refit --finish` checks the plan against scour results and transitions
  the repo from remediation to maintenance mode.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

from slopmop.checks import ensure_checks_registered
from slopmop.checks.base import BaseCheck, RemediationChurn
from slopmop.checks.custom import register_custom_gates
from slopmop.cli.buff import _load_json_file
from slopmop.cli.scan_triage import write_json_out
from slopmop.core.lock import SmLockError, sm_lock
from slopmop.core.registry import get_registry
from slopmop.workflow.state_machine import RepoPhase
from slopmop.workflow.state_store import read_phase

_REFIT_DIR = ".slopmop/refit"
_PLAN_FILE = "plan.json"
_PLAN_SUMMARY_FILE = "plan_summary.md"
_PROTOCOL_FILE = "protocol.json"
_INITIAL_SCOUR_FILE = "initial_scour.json"
_CONTINUE_SCOUR_FILE = "current_gate_scour.json"
_SCHEMA_VERSION = "refit/v1"
_POST_REFIT_NEXT_ACTION = (
    "Run `sm scour --no-auto-fix` and continue with the normal workflow."
)
_CONTINUE_LOOP = 2
_NESTED_VALIDATE_OWNER = "refit"
_MAINTENANCE_NEXT_ACTION = (
    "Use the normal swab/scour/buff workflow for maintenance repos."
)


def _project_root(args: argparse.Namespace) -> Path:
    return Path(getattr(args, "project_root", ".")).resolve()


def _refit_dir(project_root: Path) -> Path:
    return project_root / _REFIT_DIR


def _plan_path(project_root: Path) -> Path:
    return _refit_dir(project_root) / _PLAN_FILE


def _plan_summary_path(project_root: Path) -> Path:
    return _refit_dir(project_root) / _PLAN_SUMMARY_FILE


def _protocol_path(project_root: Path) -> Path:
    return _refit_dir(project_root) / _PROTOCOL_FILE


def _initial_scour_path(project_root: Path) -> Path:
    return _refit_dir(project_root) / _INITIAL_SCOUR_FILE


def _continue_scour_path(project_root: Path) -> Path:
    return _refit_dir(project_root) / _CONTINUE_SCOUR_FILE


def _plan_project_root(plan: Dict[str, Any]) -> Path:
    return Path(str(plan["project_root"]))


def _plan_file_line(plan: Dict[str, Any]) -> str:
    return f"Plan file: {_plan_path(_plan_project_root(plan))}"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_config(project_root: Path) -> Dict[str, Any]:
    config_file = os.environ.get("SB_CONFIG_FILE")
    config_path = Path(config_file) if config_file else project_root / ".sb_config.json"
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return cast(Dict[str, Any], data)


def _git_output(project_root: Path, *args: str) -> Tuple[int, str, str]:
    result = subprocess.run(
        ["git", *args],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    # Use rstrip('\n') instead of strip() for stdout to preserve leading
    # whitespace in porcelain format (e.g. " M foo.py").
    return result.returncode, result.stdout.rstrip("\n"), result.stderr.strip()


def _git_output_or_none(project_root: Path, *args: str) -> Optional[str]:
    code, stdout, _stderr = _git_output(project_root, *args)
    if code != 0:
        return None
    return stdout


def _current_branch(project_root: Path) -> Optional[str]:
    return _git_output_or_none(project_root, "branch", "--show-current")


def _current_head(project_root: Path) -> Optional[str]:
    return _git_output_or_none(project_root, "rev-parse", "HEAD")


def _is_slopmop_artifact(status_line: str) -> bool:
    if len(status_line) < 3:
        return False
    # Git porcelain format: XY PATH (XY = 2-char status code).
    # Use lstrip() after the status prefix to handle variable spacing
    # between the status code and the path.
    path = status_line[2:].lstrip()
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    path = path.strip().strip('"')
    return path == ".slopmop" or path.startswith(".slopmop/")


def _worktree_status(project_root: Path) -> List[str]:
    code, stdout, stderr = _git_output(project_root, "status", "--porcelain")
    if code != 0:
        detail = stderr or stdout or "unknown git status failure"
        raise RuntimeError(
            f"'git status --porcelain' failed with exit code {code}: {detail}"
        )
    if not stdout:
        return []
    return [
        line
        for line in stdout.splitlines()
        if line.strip() and not _is_slopmop_artifact(line)
    ]


def _ensure_remediation_phase(project_root: Path) -> bool:
    phase = read_phase(project_root)
    return phase == RepoPhase.REMEDIATION


def _ensure_init_completed(project_root: Path) -> bool:
    return (project_root / ".sb_config.json").exists()


def _run_doctor_preflight(_project_root: Path) -> Tuple[bool, str]:
    # TODO: replace this stub with a real `sm doctor` invocation once the
    # doctor command lands. This feature is expected to ship and merge with the
    # stub in place so refit can stabilize ahead of the doctor work.
    return True, "doctor preflight stub passed"


def _run_scour(
    project_root: Path, artifact_path: Path, gate: Optional[str] = None
) -> int:
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "slopmop.sm",
        "scour",
        "--no-auto-fix",
        "--no-cache",
        "--json-file",
        str(artifact_path),
        "--project-root",
        str(project_root),
    ]
    if gate:
        command.extend(["-g", gate])
    env = os.environ.copy()
    env["SLOPMOP_SKIP_REPO_LOCK"] = "1"
    env["SLOPMOP_NESTED_VALIDATE_OWNER"] = _NESTED_VALIDATE_OWNER
    result = subprocess.run(
        command,
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode


def _load_plan(project_root: Path) -> Dict[str, Any]:
    path = _plan_path(project_root)
    if not path.exists():
        raise FileNotFoundError("No refit plan found. Run `sm refit --start`.")
    return _load_json_file(path)


def _save_protocol(project_root: Path, protocol: Dict[str, Any]) -> None:
    refit_dir = _refit_dir(project_root)
    refit_dir.mkdir(parents=True, exist_ok=True)
    _protocol_path(project_root).write_text(
        json.dumps(protocol, indent=2, sort_keys=True), encoding="utf-8"
    )


def _emit_protocol(
    args: argparse.Namespace,
    project_root: Path,
    protocol: Dict[str, Any],
    human_lines: List[str],
) -> None:
    protocol.setdefault("protocol_file", str(_protocol_path(project_root)))
    _save_protocol(project_root, protocol)
    write_json_out(getattr(args, "output_file", None), protocol)
    if getattr(args, "json_output", False):
        print(json.dumps(protocol, indent=2))
        return
    for line in human_lines:
        print(line)


def _emit_standalone_protocol(
    args: argparse.Namespace,
    project_root: Path,
    *,
    event: str,
    status: str,
    next_action: str,
    human_lines: List[str],
    details: Optional[Dict[str, Any]] = None,
) -> None:
    protocol: Dict[str, Any] = {
        "schema": _SCHEMA_VERSION,
        "recorded_at": _iso_now(),
        "event": event,
        "status": status,
        "project_root": str(project_root),
        "next_action": next_action,
    }
    if details:
        protocol["details"] = details
    _emit_protocol(args, project_root, protocol, human_lines)


def _snapshot_protocol(
    plan: Dict[str, Any],
    *,
    event: str,
    next_action: str,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    items = cast(List[Dict[str, Any]], plan.get("items", []))
    current_index = int(plan.get("current_index", 0))
    current_item = items[current_index] if 0 <= current_index < len(items) else None
    protocol: Dict[str, Any] = {
        "schema": _SCHEMA_VERSION,
        "recorded_at": _iso_now(),
        "event": event,
        "status": plan.get("status"),
        "project_root": plan.get("project_root"),
        "branch": plan.get("branch"),
        "expected_head": plan.get("expected_head"),
        "current_index": current_index,
        "current_gate": plan.get("current_gate"),
        "next_action": next_action,
        "plan_file": str(_plan_path(Path(str(plan.get("project_root"))))),
        "summary_file": str(_plan_summary_path(Path(str(plan.get("project_root"))))),
    }
    if current_item is not None:
        protocol["current_item"] = {
            "id": current_item.get("id"),
            "gate": current_item.get("gate"),
            "status": current_item.get("status"),
            "verify_command": current_item.get("verify_command"),
            "commit_message": current_item.get("commit_message"),
            "attempt_count": current_item.get("attempt_count"),
            "last_artifact": current_item.get("last_artifact"),
        }
    if details:
        protocol["details"] = details
    return protocol


def _save_plan(project_root: Path, plan: Dict[str, Any]) -> None:
    refit_dir = _refit_dir(project_root)
    refit_dir.mkdir(parents=True, exist_ok=True)
    _plan_path(project_root).write_text(
        json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8"
    )
    _plan_summary_path(project_root).write_text(
        _render_plan_summary(plan), encoding="utf-8"
    )


def _gate_family(name: str) -> str:
    return name.split(":", 1)[1] if ":" in name else name


def _phase_label_for_check(check: BaseCheck) -> str:
    if check.remediation_churn == RemediationChurn.DOWNSTREAM_CHANGES_VERY_LIKELY:
        return "structural"
    if check.remediation_churn == RemediationChurn.DOWNSTREAM_CHANGES_LIKELY:
        return "logic"
    if check.remediation_churn == RemediationChurn.DOWNSTREAM_CHANGES_UNLIKELY:
        return "correctness"
    return "polish"


def _commit_kind_for_check(name: str, check: BaseCheck) -> str:
    family = _gate_family(name)
    if any(token in family for token in ("sloppy-formatting", ".format", "format")):
        return "style"
    if any(
        token in family
        for token in (
            "bogus-tests",
            "hand-wavy-tests",
            "coverage-gaps",
            "untested-code",
            "tests",
        )
    ):
        return "test"
    if (
        any(
            token in family
            for token in (
                "source-duplication",
                "dead-code",
                "complexity-creep",
                "code-sprawl",
                "string-duplication",
            )
        )
        or check.remediation_churn == RemediationChurn.DOWNSTREAM_CHANGES_VERY_LIKELY
    ):
        return "refactor"
    if any(
        token in family
        for token in (
            "config-debt",
            "gate-dodging",
            "debugger-artifacts",
            "generated-artifacts",
        )
    ):
        return "chore"
    if name.startswith("security:") or any(
        token in family
        for token in (
            "type-blindness",
            "missing-annotations",
            "static-analysis",
            "vulnerability-blindness",
            # Security checks don't all live under the "security:" category
            # prefix — dependency-risk.py (bandit) is under myopia:. Without
            # this, bandit annotations get a "test(...)" commit prefix via
            # the churn fallback, which is nonsense.
            "dependency-risk",
            "leaked-secrets",
        )
    ):
        return "fix"
    if check.remediation_churn == RemediationChurn.DOWNSTREAM_CHANGES_VERY_UNLIKELY:
        return "chore"
    if check.remediation_churn == RemediationChurn.DOWNSTREAM_CHANGES_UNLIKELY:
        return "test"
    return "fix"


def _commit_message_for_check(name: str, check: BaseCheck) -> str:
    kind = _commit_kind_for_check(name, check)
    family = _gate_family(name)
    return f"{kind}({family}): resolve remediation findings"


def _failed_results_from_scour_artifact(
    artifact: Dict[str, Any],
) -> List[Dict[str, Any]]:
    raw_results = artifact.get("results")
    if not isinstance(raw_results, list):
        return []
    result_items = cast(List[object], raw_results)
    failures: List[Dict[str, Any]] = []
    for raw_item in result_items:
        if not isinstance(raw_item, dict):
            continue
        item = cast(Dict[str, Any], raw_item)
        status = str(item.get("status", ""))
        if status in {"failed", "error"}:
            failures.append(item)
    return failures


def _build_plan(project_root: Path, scour_artifact_path: Path) -> Dict[str, Any]:
    config = _load_config(project_root)
    ensure_checks_registered()
    register_custom_gates(config)
    registry = get_registry()

    artifact = _load_json_file(scour_artifact_path)
    failing_results = _failed_results_from_scour_artifact(artifact)

    checks: List[BaseCheck] = []
    result_by_name: Dict[str, Dict[str, Any]] = {}
    for result in failing_results:
        name = str(result.get("name", ""))
        check = registry.get_check(name, config)
        if check is None:
            continue
        checks.append(check)
        result_by_name[name] = result

    ordered_checks = registry.sort_checks_for_remediation(checks)
    items: List[Dict[str, Any]] = []
    for index, check in enumerate(ordered_checks, start=1):
        result = result_by_name.get(check.full_name, {})
        items.append(
            {
                "id": index,
                "gate": check.full_name,
                "display_name": check.display_name,
                "phase_label": _phase_label_for_check(check),
                "remediation_priority": registry.remediation_priority_for_check(check),
                "priority_source": registry.remediation_priority_source_for_check(
                    check
                ),
                "remediation_churn": check.remediation_churn.name,
                "verify_command": f"sm scour -g {check.full_name} --no-auto-fix",
                "commit_message": _commit_message_for_check(check.full_name, check),
                "status": "pending",
                "summary": result.get("status_detail")
                or result.get("error")
                or result.get("output")
                or "",
                "log_file": result.get("log_file"),
                "attempt_count": 0,
                "last_artifact": None,
                "commit_sha": None,
            }
        )

    branch = _current_branch(project_root)
    head = _current_head(project_root)
    return {
        "schema": _SCHEMA_VERSION,
        "generated_at": _iso_now(),
        "project_root": str(project_root),
        "branch": branch,
        "expected_head": head,
        "status": "ready",
        "current_index": 0,
        "current_gate": items[0]["gate"] if items else None,
        "initial_scour_artifact": str(scour_artifact_path),
        "items": items,
    }


def _render_plan_summary(plan: Dict[str, Any]) -> str:
    items = cast(List[Dict[str, Any]], plan.get("items", []))
    lines = [
        "# Refit Plan",
        "",
        f"- schema: {plan.get('schema')}",
        f"- generated_at: {plan.get('generated_at')}",
        f"- branch: {plan.get('branch')}",
        f"- expected_head: {plan.get('expected_head')}",
        f"- status: {plan.get('status')}",
        f"- current_index: {plan.get('current_index')}",
        "",
        "## Items",
        "",
    ]
    if not items:
        lines.append("No failing gates were found in the initial scour run.")
        return "\n".join(lines) + "\n"

    for item in items:
        status = item.get("status")
        if status in {"completed", "completed_no_changes"}:
            marker = "x"
        elif status == "skipped":
            marker = "~"
        else:
            marker = " "
        lines.append(
            f"- [{marker}] {item.get('gate')} | {item.get('phase_label')} | {status}"
        )
        if status == "skipped" and item.get("skip_reason"):
            lines.append(f"  skip reason: {item.get('skip_reason')}")
        lines.append(f"  verify: {item.get('verify_command')}")
        lines.append(f"  commit: {item.get('commit_message')}")
    return "\n".join(lines) + "\n"


def _plan_generated_lines(plan: Dict[str, Any]) -> List[str]:
    items = cast(List[Dict[str, Any]], plan.get("items", []))
    lines = [
        "Refit plan generated.",
        _plan_file_line(plan),
        f"Summary: {_plan_summary_path(_plan_project_root(plan))}",
        f"Protocol: {_protocol_path(_plan_project_root(plan))}",
        f"Plan items: {len(items)}",
    ]
    if items:
        current = items[0]
        lines.append(f"Next gate: {current['gate']}")
        lines.append("Next command: sm refit --iterate")
    else:
        lines.append("No failing scour gates remain. Refit has nothing to do.")
    return lines


def _completion_lines(plan: Dict[str, Any]) -> List[str]:
    return [
        "Refit plan complete.",
        "Next step: run `sm scour --no-auto-fix` and resume the normal workflow.",
        _plan_file_line(plan),
        f"Protocol: {_protocol_path(_plan_project_root(plan))}",
    ]


def _status_is_same(before: List[str], after: List[str]) -> bool:
    return before == after


def _commit_current_changes(project_root: Path, message: str) -> Tuple[int, str]:
    add_result = subprocess.run(
        ["git", "add", "-A", "--", ".", ":!.slopmop"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if add_result.returncode != 0:
        detail = (add_result.stderr or add_result.stdout or "").strip()
        return add_result.returncode, detail or "git add failed"

    commit_result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    detail = (commit_result.stderr or commit_result.stdout or "").strip()
    return commit_result.returncode, detail


def _advance_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    items = cast(List[Dict[str, Any]], plan.get("items", []))
    next_index = int(plan.get("current_index", 0)) + 1
    plan["current_index"] = next_index
    if next_index >= len(items):
        plan["current_gate"] = None
        plan["status"] = "completed"
    else:
        plan["current_gate"] = items[next_index].get("gate")
        plan["status"] = "ready"
    return plan


def _load_continue_plan(
    args: argparse.Namespace, project_root: Path
) -> Optional[Dict[str, Any]]:
    try:
        return _load_plan(project_root)
    except (FileNotFoundError, ValueError) as exc:
        _emit_standalone_protocol(
            args,
            project_root,
            event="missing_plan",
            status="missing_plan",
            next_action="Run `sm refit --start`, then rerun `sm refit --iterate`.",
            human_lines=[str(exc)],
        )
        return None


def _ensure_continue_branch(
    args: argparse.Namespace,
    project_root: Path,
    plan: Dict[str, Any],
) -> bool:
    expected_branch = plan.get("branch")
    current_branch = _current_branch(project_root)
    if not expected_branch or current_branch == expected_branch:
        return True
    protocol = _snapshot_protocol(
        plan,
        event="blocked_on_branch_drift",
        next_action="Review branch state, then rerun `sm refit --iterate` from the planned branch.",
        details={
            "expected_branch": expected_branch,
            "current_branch": current_branch,
        },
    )
    _emit_protocol(
        args,
        project_root,
        protocol,
        [
            "Refit blocked: current branch no longer matches the generated plan. "
            f"Expected {expected_branch}, found {current_branch}."
        ],
    )
    return False


def _emit_continue_completion(
    args: argparse.Namespace, project_root: Path, plan: Dict[str, Any]
) -> int:
    plan["status"] = "completed"
    _save_plan(project_root, plan)
    protocol = _snapshot_protocol(
        plan,
        event="completed",
        next_action=_POST_REFIT_NEXT_ACTION,
    )
    _emit_protocol(args, project_root, protocol, _completion_lines(plan))
    return 0


def _cmd_refit_start(args: argparse.Namespace) -> int:
    project_root = _project_root(args)
    if not _ensure_remediation_phase(project_root):
        _emit_standalone_protocol(
            args,
            project_root,
            event="blocked_on_phase",
            status="blocked_on_phase",
            next_action=_MAINTENANCE_NEXT_ACTION,
            human_lines=[
                "Refit is only available while the repo is in remediation phase. "
                "Run the normal swab/scour/buff workflow for maintenance repos."
            ],
        )
        return 1
    if not _ensure_init_completed(project_root):
        _emit_standalone_protocol(
            args,
            project_root,
            event="preflight_missing_init",
            status="preflight_missing_init",
            next_action="Run `sm init`, then rerun `sm refit --start`.",
            human_lines=[
                "Refit preflight failed: no .sb_config.json found. Run `sm init` first."
            ],
        )
        return 1

    doctor_ok, doctor_detail = _run_doctor_preflight(project_root)
    if not doctor_ok:
        _emit_standalone_protocol(
            args,
            project_root,
            event="preflight_doctor_failed",
            status="preflight_doctor_failed",
            next_action="Resolve the doctor preflight issue, then rerun `sm refit --start`.",
            human_lines=[f"Refit preflight failed: {doctor_detail}"],
            details={"doctor_detail": doctor_detail},
        )
        return 1

    worktree = _worktree_status(project_root)
    if worktree:
        _emit_standalone_protocol(
            args,
            project_root,
            event="preflight_dirty_worktree",
            status="preflight_dirty_worktree",
            next_action=(
                "Commit, stash, or discard local changes before rerunning "
                "`sm refit --start`."
            ),
            human_lines=[
                "Refit preflight failed: working tree is not clean. "
                "Commit, stash, or discard local changes before generating a plan."
            ],
            details={"worktree_status": worktree},
        )
        return 1

    artifact_path = _initial_scour_path(project_root)
    exit_code = _run_scour(project_root, artifact_path)
    if exit_code not in {0, 1}:
        _emit_standalone_protocol(
            args,
            project_root,
            event="initial_scour_error",
            status="initial_scour_error",
            next_action="Inspect the initial scour failure and rerun `sm refit --start`.",
            human_lines=[
                "Refit could not generate a plan because the initial scour run errored."
            ],
            details={"artifact": str(artifact_path)},
        )
        return 1

    plan = _build_plan(project_root, artifact_path)
    _save_plan(project_root, plan)
    protocol = _snapshot_protocol(
        plan,
        event="plan_generated",
        next_action="Run `sm refit --iterate` to start advancing the plan.",
        details={
            "initial_scour_artifact": str(artifact_path),
            "item_count": len(cast(List[Dict[str, Any]], plan.get("items", []))),
        },
    )
    _emit_protocol(args, project_root, protocol, _plan_generated_lines(plan))
    return 0


def _cmd_refit_iterate(args: argparse.Namespace) -> int:
    project_root = _project_root(args)
    if not _ensure_remediation_phase(project_root):
        _emit_standalone_protocol(
            args,
            project_root,
            event="blocked_on_phase",
            status="blocked_on_phase",
            next_action=_MAINTENANCE_NEXT_ACTION,
            human_lines=[
                "Refit is only available while the repo is in remediation phase. "
                "Run the normal swab/scour/buff workflow for maintenance repos."
            ],
        )
        return 1

    plan = _load_continue_plan(args, project_root)
    if plan is None:
        return 1

    if plan.get("status") == "completed":
        _emit_standalone_protocol(
            args,
            project_root,
            event="already_completed",
            status="already_completed",
            next_action="Run `sm refit --finish` to transition to maintenance mode.",
            human_lines=[
                "Refit plan is already completed. "
                "Run `sm refit --finish` to check results and transition to maintenance."
            ],
        )
        return 0

    if not _ensure_continue_branch(args, project_root, plan):
        return 1

    from slopmop.cli._refit_iteration import process_current_plan_item

    try:
        with sm_lock(project_root, "refit"):
            while True:
                result = process_current_plan_item(args, project_root, plan)
                if result == _CONTINUE_LOOP:
                    continue
                return result
    except SmLockError as exc:
        protocol: Dict[str, Any] = {
            "schema": _SCHEMA_VERSION,
            "recorded_at": _iso_now(),
            "event": "blocked_on_lock",
            "status": "blocked_on_lock",
            "project_root": str(project_root),
            "next_action": "Wait for the active sm process to finish, then rerun `sm refit --iterate`.",
            "details": {"message": str(exc)},
        }
        _emit_protocol(
            args,
            project_root,
            protocol,
            [f"Refit blocked: {exc}"],
        )
        return 1


def _cmd_refit_finish(args: argparse.Namespace) -> int:
    project_root = _project_root(args)
    if not _ensure_remediation_phase(project_root):
        _emit_standalone_protocol(
            args,
            project_root,
            event="blocked_on_phase",
            status="already_maintenance",
            next_action=_MAINTENANCE_NEXT_ACTION,
            human_lines=[
                "This repo is already in maintenance mode. Nothing to finish."
            ],
        )
        return 0

    plan = _load_continue_plan(args, project_root)
    if plan is None:
        return 1

    items = cast(List[Dict[str, Any]], plan.get("items", []))
    done = {"completed", "completed_no_changes"}
    pending = [i for i in items if i.get("status") not in done]
    skipped = [i for i in pending if i.get("status") == "skipped"]
    unresolved = [i for i in pending if i.get("status") != "skipped"]
    if pending:
        lines = [f"Cannot finish: {len(pending)} gate(s) not completed."]
        if unresolved:
            lines.append(
                f"  {len(unresolved)} unresolved. Next: {unresolved[0].get('gate', '?')}. "
                "Run `sm refit --iterate`."
            )
        if skipped:
            lines.append(
                f"  {len(skipped)} skipped. Either resolve them or disable the "
                "checks in .sb_config.json:"
            )
            for item in skipped:
                reason = item.get("skip_reason", "")
                lines.append(f"    - {item.get('gate')}  ({reason})")
        _emit_standalone_protocol(
            args,
            project_root,
            event="finish_blocked_incomplete",
            status="finish_blocked_incomplete",
            next_action=(
                "Run `sm refit --iterate` for unresolved gates; disable skipped "
                "gates in .sb_config.json if permanently out of scope."
            ),
            human_lines=lines,
            details={
                "pending_count": len(pending),
                "skipped_count": len(skipped),
                "unresolved_count": len(unresolved),
                "skipped_gates": [i.get("gate") for i in skipped],
            },
        )
        return 1

    from slopmop.workflow.state_store import record_baseline

    record_baseline(project_root)
    _emit_standalone_protocol(
        args,
        project_root,
        event="refit_completed",
        status="maintenance",
        next_action=_POST_REFIT_NEXT_ACTION,
        human_lines=[
            "All remediation gates passed.",
            "Repo transitioned from remediation to maintenance mode.",
            _POST_REFIT_NEXT_ACTION,
        ],
    )
    return 0


def _cmd_refit_skip(args: argparse.Namespace) -> int:
    """Mark the current gate as skipped and advance without running it.

    Use when a gate is intractable right now (tool unavailable, needs
    discussion, out of scope for this pass). Skipped items still block
    --finish — disable the check in .sb_config.json if it's permanently
    out of scope.
    """
    project_root = _project_root(args)
    if not _ensure_remediation_phase(project_root):
        _emit_standalone_protocol(
            args,
            project_root,
            event="blocked_on_phase",
            status="blocked_on_phase",
            next_action=_MAINTENANCE_NEXT_ACTION,
            human_lines=["Refit is only available in remediation phase."],
        )
        return 1

    plan = _load_continue_plan(args, project_root)
    if plan is None:
        return 1

    if not _ensure_continue_branch(args, project_root, plan):
        return 1

    items = cast(List[Dict[str, Any]], plan.get("items", []))
    current_index = int(plan.get("current_index", 0))
    if current_index >= len(items):
        _emit_standalone_protocol(
            args,
            project_root,
            event="skip_past_end",
            status=str(plan.get("status", "completed")),
            next_action="Run `sm refit --finish`.",
            human_lines=[
                "No current gate to skip — plan is already past its last item."
            ],
        )
        return 0

    current_item = items[current_index]
    gate = str(current_item.get("gate", "?"))
    reason = str(getattr(args, "skip", None) or "manual skip")

    try:
        with sm_lock(project_root, "refit"):
            current_item["status"] = "skipped"
            current_item["skip_reason"] = reason
            plan = _advance_plan(plan)
            _save_plan(project_root, plan)
    except SmLockError as exc:
        protocol: Dict[str, Any] = {
            "schema": _SCHEMA_VERSION,
            "recorded_at": _iso_now(),
            "event": "blocked_on_lock",
            "status": "blocked_on_lock",
            "project_root": str(project_root),
            "next_action": "Wait for the active sm process to finish, then rerun `sm refit --skip`.",
            "details": {"message": str(exc)},
        }
        _emit_protocol(
            args,
            project_root,
            protocol,
            [f"Refit blocked: {exc}"],
        )
        return 1

    next_gate = plan.get("current_gate")
    next_line = (
        f"Next gate: {next_gate}. Run: sm refit --iterate"
        if next_gate
        else "No gates remain. Run: sm refit --finish"
    )
    protocol = _snapshot_protocol(
        plan,
        event="gate_skipped",
        next_action="Run `sm refit --iterate` to resume, or disable the skipped check in .sb_config.json.",
        details={"skipped_gate": gate, "reason": reason},
    )
    _emit_protocol(
        args,
        project_root,
        protocol,
        [
            f"Skipped gate: {gate}",
            f"Reason: {reason}",
            next_line,
            "Note: skipped gates still block --finish. If this gate is permanently "
            "out of scope, disable it in .sb_config.json.",
        ],
    )
    return 0


def cmd_refit(args: argparse.Namespace) -> int:
    """Run the structured remediation process."""
    if getattr(args, "start", False):
        return _cmd_refit_start(args)
    if getattr(args, "iterate", False):
        return _cmd_refit_iterate(args)
    if getattr(args, "skip", None) is not None:
        return _cmd_refit_skip(args)
    if getattr(args, "finish", False):
        return _cmd_refit_finish(args)
    print("Refit requires exactly one mode: --start, --iterate, --skip, or --finish")
    return 1
