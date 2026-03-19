"""Doctor command — diagnose environment and toolchain issues.

Checks that the user's environment can run all enabled quality gates.
Reports missing tools, broken venvs, stale locks, and other blockers.

Default mode is read-only (diagnosis only).  Use ``--fix`` to enable
safe auto-repair for sm-owned state (stale locks, missing ``.slopmop/``).
"""

from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from slopmop import __version__
from slopmop.checks.base import ToolContext, find_tool
from slopmop.core.registry import get_registry

# ── Result types ────────────────────────────────────────────────────


class DoctorStatus(str, Enum):
    """Status levels for doctor check results."""

    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"
    FIXED = "fixed"


# Console status labels — fixed width for alignment.
_STATUS_LABEL = {
    DoctorStatus.OK: "  OK  ",
    DoctorStatus.WARN: " WARN ",
    DoctorStatus.FAIL: " FAIL ",
    DoctorStatus.SKIP: " SKIP ",
    DoctorStatus.FIXED: "FIXED ",
}


@dataclass
class DoctorCheckResult:
    """Result from a single doctor diagnostic check."""

    name: str
    status: DoctorStatus
    summary: str
    details: str = ""
    suggested_actions: List[str] = field(default_factory=lambda: [])
    gate: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "status": self.status.value,
            "summary": self.summary,
        }
        if self.details:
            d["details"] = self.details
        if self.suggested_actions:
            d["suggested_actions"] = self.suggested_actions
        if self.gate:
            d["gate"] = self.gate
        return d


@dataclass
class DoctorReport:
    """Complete doctor report."""

    sm_version: str = ""
    python_version: str = ""
    platform_info: str = ""
    project_root: str = ""
    results: List[DoctorCheckResult] = field(default_factory=lambda: [])

    @property
    def has_failures(self) -> bool:
        return any(r.status == DoctorStatus.FAIL for r in self.results)

    @property
    def has_warnings(self) -> bool:
        return any(r.status == DoctorStatus.WARN for r in self.results)

    @property
    def exit_code(self) -> int:
        return 1 if self.has_failures else 0

    def add(self, result: DoctorCheckResult) -> None:
        self.results.append(result)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sm_version": self.sm_version,
            "python_version": self.python_version,
            "platform": self.platform_info,
            "project_root": self.project_root,
            "results": [r.to_dict() for r in self.results],
        }


# ── Environment checks ─────────────────────────────────────────────


def _check_platform(report: DoctorReport) -> None:
    """Report platform info. FAIL if Python < 3.10."""
    vi = sys.version_info
    py_ver = f"{vi.major}.{vi.minor}.{vi.micro}"
    plat = f"{platform.system()} {platform.machine()}"
    summary = f"Python {py_ver} on {plat}"

    report.sm_version = __version__
    report.python_version = py_ver
    report.platform_info = plat

    if vi < (3, 10):
        report.add(
            DoctorCheckResult(
                name="platform",
                status=DoctorStatus.FAIL,
                summary=f"{summary} — Python >= 3.10 required",
                suggested_actions=["Install Python 3.10 or later"],
            )
        )
    else:
        report.add(
            DoctorCheckResult(
                name="platform",
                status=DoctorStatus.OK,
                summary=summary,
                details=f"sys.executable: {sys.executable}",
            )
        )


def _check_sm_resolution(report: DoctorReport) -> None:
    """Report the active sm entry point and detect PATH collisions."""
    sm_path = os.path.abspath(sys.argv[0]) if sys.argv else "unknown"

    # Walk PATH for all candidates named "sm"
    candidates: List[str] = []
    seen: set[str] = set()
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    for d in path_dirs:
        for name in ["sm", "sm.exe", "sm.cmd", "sm.bat"]:
            candidate = os.path.join(d, name)
            try:
                real = os.path.realpath(candidate)
            except OSError:
                continue
            if os.path.isfile(candidate) and real not in seen:
                seen.add(real)
                candidates.append(candidate)

    if len(candidates) > 1:
        detail_lines = "\n".join(f"  {c}" for c in candidates)
        report.add(
            DoctorCheckResult(
                name="sm-resolution",
                status=DoctorStatus.WARN,
                summary=f"{sm_path} (multiple sm found on PATH)",
                details=f"All candidates:\n{detail_lines}",
                suggested_actions=[
                    "Check PATH ordering to ensure the correct sm is first"
                ],
            )
        )
    else:
        report.add(
            DoctorCheckResult(
                name="sm-resolution",
                status=DoctorStatus.OK,
                summary=f"{sm_path}",
            )
        )


def _check_config(report: DoctorReport, project_root: Path) -> None:
    """Check that .sb_config.json exists and parses."""
    config_file_env = os.environ.get("SB_CONFIG_FILE")
    if config_file_env:
        config_path = Path(config_file_env)
    else:
        config_path = project_root / ".sb_config.json"

    if not config_path.exists():
        report.add(
            DoctorCheckResult(
                name="config",
                status=DoctorStatus.WARN,
                summary=f"No config file at {config_path}",
                suggested_actions=["Run: sm init"],
            )
        )
        return

    try:
        text = config_path.read_text()
        json.loads(text)
        report.add(
            DoctorCheckResult(
                name="config",
                status=DoctorStatus.OK,
                summary=f"{config_path} parsed successfully",
            )
        )
    except json.JSONDecodeError as e:
        report.add(
            DoctorCheckResult(
                name="config",
                status=DoctorStatus.FAIL,
                summary=f"Malformed JSON in {config_path}",
                details=str(e),
                suggested_actions=[f"Fix JSON syntax in {config_path}"],
            )
        )


def _check_slopmop_dir(report: DoctorReport, project_root: Path, fix: bool) -> None:
    """Check .slopmop/ directory exists and is writable."""
    slopmop_dir = project_root / ".slopmop"

    if not slopmop_dir.exists():
        if fix:
            try:
                slopmop_dir.mkdir(parents=True, exist_ok=True)
                report.add(
                    DoctorCheckResult(
                        name="slopmop-dir",
                        status=DoctorStatus.FIXED,
                        summary=f"Created {slopmop_dir}",
                    )
                )
            except OSError as e:
                report.add(
                    DoctorCheckResult(
                        name="slopmop-dir",
                        status=DoctorStatus.FAIL,
                        summary=f"Cannot create {slopmop_dir}: {e}",
                    )
                )
        else:
            report.add(
                DoctorCheckResult(
                    name="slopmop-dir",
                    status=DoctorStatus.WARN,
                    summary=f"{slopmop_dir} does not exist",
                    suggested_actions=[
                        f"mkdir -p {slopmop_dir}",
                        "Or run: sm doctor --fix",
                    ],
                )
            )
        return

    if not os.access(slopmop_dir, os.W_OK):
        report.add(
            DoctorCheckResult(
                name="slopmop-dir",
                status=DoctorStatus.FAIL,
                summary=f"{slopmop_dir} is not writable",
                suggested_actions=[f"chmod u+w {slopmop_dir}"],
            )
        )
    else:
        report.add(
            DoctorCheckResult(
                name="slopmop-dir",
                status=DoctorStatus.OK,
                summary=f"{slopmop_dir} exists and is writable",
            )
        )


def _check_stale_lock(report: DoctorReport, project_root: Path, fix: bool) -> None:
    """Detect stale lock files under .slopmop/."""
    from slopmop.core.lock import LOCK_DIR, LOCK_FILE, _pid_alive, _read_lock_meta

    lock_path = project_root / LOCK_DIR / LOCK_FILE
    if not lock_path.exists():
        report.add(
            DoctorCheckResult(
                name="stale-lock",
                status=DoctorStatus.OK,
                summary="No lock file present",
            )
        )
        return

    meta = _read_lock_meta(lock_path)
    if meta is None or not meta.get("pid"):
        # Empty or unparseable lock file — likely leftover from clean exit
        report.add(
            DoctorCheckResult(
                name="stale-lock",
                status=DoctorStatus.OK,
                summary="Lock file present but empty (normal after clean exit)",
            )
        )
        return

    pid = meta.get("pid")
    verb = meta.get("verb", "unknown")

    if isinstance(pid, int) and not _pid_alive(pid):
        if fix:
            try:
                lock_path.unlink()
                report.add(
                    DoctorCheckResult(
                        name="stale-lock",
                        status=DoctorStatus.FIXED,
                        summary=f"Removed stale lock (PID {pid} is dead)",
                    )
                )
            except OSError as e:
                report.add(
                    DoctorCheckResult(
                        name="stale-lock",
                        status=DoctorStatus.FAIL,
                        summary=f"Cannot remove stale lock: {e}",
                    )
                )
        else:
            report.add(
                DoctorCheckResult(
                    name="stale-lock",
                    status=DoctorStatus.WARN,
                    summary=f"Stale lock from PID {pid} (dead process, verb: {verb})",
                    suggested_actions=[
                        f"rm {lock_path}",
                        "Or run: sm doctor --fix",
                    ],
                )
            )
    elif isinstance(pid, int) and _pid_alive(pid):
        report.add(
            DoctorCheckResult(
                name="stale-lock",
                status=DoctorStatus.WARN,
                summary=f"Lock held by PID {pid} (verb: {verb}, still running)",
            )
        )
    else:
        report.add(
            DoctorCheckResult(
                name="stale-lock",
                status=DoctorStatus.OK,
                summary="Lock file present, no issues detected",
            )
        )


# ── Per-gate readiness checks ──────────────────────────────────────


def _check_gate_readiness(
    report: DoctorReport,
    check: Any,
    project_root: Path,
    verbose: bool = False,
) -> None:
    """Run readiness diagnostics for a single enabled gate."""
    gate_name = check.full_name
    ctx = check.tool_context

    if ctx == ToolContext.PURE:
        report.add(
            DoctorCheckResult(
                name=gate_name,
                status=DoctorStatus.OK,
                summary="Pure analysis — no external dependencies",
                gate=gate_name,
            )
        )
        return

    if ctx == ToolContext.SM_TOOL:
        required = getattr(check, "required_tools", [])
        if not required:
            report.add(
                DoctorCheckResult(
                    name=gate_name,
                    status=DoctorStatus.OK,
                    summary="SM_TOOL gate (no specific tools declared)",
                    gate=gate_name,
                )
            )
            return

        missing: List[str] = []
        found: List[str] = []
        for tool_name in required:
            resolved = find_tool(tool_name, str(project_root))
            if resolved is None:
                missing.append(tool_name)
            else:
                found.append(tool_name)

        if missing:
            # Build install hints from the check's declared install_hint.
            hint = getattr(check, "install_hint", "pip")
            actions: list[str] = []
            if hint == "pip":
                actions.append(f"pip install {' '.join(missing)}")
            else:
                for t in missing:
                    actions.append(f"Install {t} and ensure it is on PATH")

            report.add(
                DoctorCheckResult(
                    name=gate_name,
                    status=DoctorStatus.FAIL,
                    summary=f"Missing tools: {', '.join(missing)}",
                    details=(
                        f"Found: {', '.join(found)}" if found else "No tools found"
                    ),
                    suggested_actions=actions,
                    gate=gate_name,
                )
            )
        else:
            report.add(
                DoctorCheckResult(
                    name=gate_name,
                    status=DoctorStatus.OK,
                    summary=f"All tools found: {', '.join(found)}",
                    gate=gate_name,
                )
            )
        return

    if ctx == ToolContext.PROJECT:
        from slopmop.checks.mixins import PythonCheckMixin

        mixin = PythonCheckMixin()
        pr = str(project_root)
        if mixin.has_project_venv(pr):
            report.add(
                DoctorCheckResult(
                    name=gate_name,
                    status=DoctorStatus.OK,
                    summary="Project venv found",
                    gate=gate_name,
                )
            )
        else:
            # PROJECT gates warn+skip at runtime, so doctor should WARN not FAIL.
            report.add(
                DoctorCheckResult(
                    name=gate_name,
                    status=DoctorStatus.WARN,
                    summary="No project virtual environment found (gate will skip at runtime)",
                    suggested_actions=[
                        PythonCheckMixin.suggest_venv_command(pr),
                    ],
                    gate=gate_name,
                )
            )
        return

    if ctx == ToolContext.NODE:
        from slopmop.checks.mixins import JavaScriptCheckMixin

        js_mixin = JavaScriptCheckMixin()
        pr = str(project_root)
        has_pkg = js_mixin.has_package_json(pr)
        has_nm = js_mixin.has_node_modules(pr)

        if not has_pkg:
            report.add(
                DoctorCheckResult(
                    name=gate_name,
                    status=DoctorStatus.FAIL,
                    summary="No package.json found",
                    gate=gate_name,
                )
            )
        elif not has_nm:
            pm = js_mixin._detect_package_manager(pr)
            report.add(
                DoctorCheckResult(
                    name=gate_name,
                    status=DoctorStatus.FAIL,
                    summary="node_modules/ not found",
                    suggested_actions=[f"{pm} install"],
                    gate=gate_name,
                )
            )
        else:
            report.add(
                DoctorCheckResult(
                    name=gate_name,
                    status=DoctorStatus.OK,
                    summary="package.json and node_modules present",
                    gate=gate_name,
                )
            )
        return

    # Unknown tool_context — report as OK with note
    report.add(
        DoctorCheckResult(
            name=gate_name,
            status=DoctorStatus.OK,
            summary=f"tool_context={ctx.value} (no specific doctor check)",
            gate=gate_name,
        )
    )


# ── Check catalog (for --list-checks) ──────────────────────────────

_ENV_CHECKS = [
    ("platform", "OS, arch, Python version, sm version"),
    ("sm-resolution", "Active sm entry point and PATH collision detection"),
    ("config", "Config file existence and JSON validity"),
    ("slopmop-dir", ".slopmop/ directory existence and write permissions"),
    ("stale-lock", "Stale lock file detection under .slopmop/"),
]


# ── Gate enablement helper ──────────────────────────────────────────


def _is_gate_enabled(cfg: Dict[str, Any], full_name: str) -> bool:
    """Check if a gate is enabled in config (mirrors config.py logic)."""
    disabled = cfg.get("disabled_gates", [])
    if isinstance(disabled, list) and full_name in disabled:
        return False
    if ":" not in full_name:
        return True
    category, gate = full_name.split(":", 1)
    cat_raw = cfg.get(category)
    if isinstance(cat_raw, dict):
        cat_dict = cast(Dict[str, object], cat_raw)
        gates_raw = cat_dict.get("gates")
        if isinstance(gates_raw, dict):
            gates_dict = cast(Dict[str, object], gates_raw)
            gate_raw = gates_dict.get(gate)
            if isinstance(gate_raw, dict):
                gate_dict = cast(Dict[str, object], gate_raw)
                if "enabled" in gate_dict:
                    return bool(gate_dict["enabled"])
    return True


# ── Output rendering ───────────────────────────────────────────────


def _print_report(report: DoctorReport, verbose: bool) -> None:
    """Render the doctor report to console."""
    # Header
    print(
        f"sm doctor — slop-mop v{report.sm_version} / "
        f"Python {report.python_version} / {report.platform_info}"
    )
    print(f"Project: {report.project_root}")
    print()

    # Group results: env checks vs gate checks
    env_results = [r for r in report.results if r.gate is None]
    gate_results = [r for r in report.results if r.gate is not None]

    if env_results:
        print("Environment")
        for r in env_results:
            _print_result_line(r, verbose)
        print()

    if gate_results:
        print("Gate Readiness")
        for r in gate_results:
            _print_result_line(r, verbose)
        print()

    # Summary
    fail_count = sum(1 for r in report.results if r.status == DoctorStatus.FAIL)
    warn_count = sum(1 for r in report.results if r.status == DoctorStatus.WARN)
    fixed_count = sum(1 for r in report.results if r.status == DoctorStatus.FIXED)

    parts: List[str] = []
    if fail_count:
        parts.append(f"{fail_count} failed")
    if warn_count:
        parts.append(f"{warn_count} warnings")
    if fixed_count:
        parts.append(f"{fixed_count} fixed")
    if not parts:
        parts.append("All checks passed")

    print(", ".join(parts) + ".")
    if fail_count and not fixed_count:
        print("Run `sm doctor --fix` to repair sm-owned issues.")


def _print_result_line(r: DoctorCheckResult, verbose: bool) -> None:
    """Print a single check result line."""
    label = _STATUS_LABEL.get(r.status, r.status.value.ljust(6))
    # For gate results, show the gate name; for env, show the check name
    display_name = r.gate if r.gate else r.name
    print(f"  {label} {display_name:<42s} {r.summary}")

    if r.suggested_actions:
        for action in r.suggested_actions:
            print(f"         {'':42s} Fix: {action}")

    if verbose and r.details:
        for line in r.details.splitlines():
            print(f"         {'':42s} {line}")


# ── Orchestrator ───────────────────────────────────────────────────


def run_doctor(
    project_root: str = ".",
    fix: bool = False,
    checks_filter: Optional[List[str]] = None,
    list_checks: bool = False,
    json_output: Optional[bool] = None,
    verbose: bool = False,
    quiet: bool = False,
) -> int:
    """Run doctor diagnostics.

    Returns 0 if no FAILs, 1 otherwise.
    """
    from slopmop.checks import ensure_checks_registered
    from slopmop.sm import load_config

    ensure_checks_registered()

    root = Path(project_root).resolve()

    # Resolve JSON mode
    if json_output is None:
        json_mode = not sys.stdout.isatty()
    else:
        json_mode = json_output

    registry = get_registry()
    config = load_config(root)

    # --list-checks mode
    if list_checks:
        _print_list_checks(registry, config, root, json_mode)
        return 0

    report = DoctorReport(project_root=str(root))

    # Normalize filter: empty list means run all.
    has_filter = checks_filter is not None and len(checks_filter) > 0
    filter_set: set[str] = set(checks_filter) if has_filter and checks_filter else set()

    # ── Environment checks ──────────────────────────────────────
    env_check_names = {name for name, _ in _ENV_CHECKS}
    run_env = not has_filter or bool(filter_set & env_check_names)

    if run_env:
        _check_platform(report)
        if not has_filter or "sm-resolution" in filter_set:
            _check_sm_resolution(report)
        if not has_filter or "config" in filter_set:
            _check_config(report, root)
        if not has_filter or "slopmop-dir" in filter_set:
            _check_slopmop_dir(report, root, fix)
        if not has_filter or "stale-lock" in filter_set:
            _check_stale_lock(report, root, fix)

    # ── Per-gate readiness ──────────────────────────────────────
    all_gates = registry.list_checks()

    for gate_name in all_gates:
        if not _is_gate_enabled(config, gate_name):
            continue

        if has_filter and gate_name not in filter_set:
            continue

        check = registry.get_check(gate_name, config)
        if check is None:
            continue

        if not check.is_applicable(str(root)):
            continue

        _check_gate_readiness(report, check, root, verbose)

    # ── Output ──────────────────────────────────────────────────
    if json_mode:
        print(json.dumps(report.to_dict(), indent=2))
    elif not quiet:
        _print_report(report, verbose)

    return report.exit_code


def _print_list_checks(
    registry: Any, config: Dict[str, Any], root: Path, json_mode: bool
) -> None:
    """Print all available doctor checks."""
    checks_list: List[Dict[str, str]] = []

    # Environment checks
    for name, desc in _ENV_CHECKS:
        checks_list.append({"name": name, "type": "environment", "description": desc})

    # Per-gate checks
    all_gates = registry.list_checks()
    for gate_name in all_gates:
        if not _is_gate_enabled(config, gate_name):
            continue
        check = registry.get_check(gate_name, config)
        if check is None:
            continue
        if not check.is_applicable(str(root)):
            continue
        ctx = check.tool_context
        checks_list.append(
            {
                "name": gate_name,
                "type": "gate",
                "description": f"{ctx.value} gate readiness",
                "gate": gate_name,
            }
        )

    if json_mode:
        print(json.dumps(checks_list, indent=2))
    else:
        print("Available doctor checks:")
        print()
        print("  Environment:")
        for c in checks_list:
            if c["type"] == "environment":
                print(f"    {c['name']:<20s} {c['description']}")
        print()
        print("  Gate readiness:")
        for c in checks_list:
            if c["type"] == "gate":
                print(f"    {c['name']:<50s} {c['description']}")


# ── Public API for config hook ─────────────────────────────────────


def check_single_gate_readiness(
    gate_name: str,
    project_root: Path,
    config: Dict[str, Any],
) -> DoctorReport:
    """Run readiness check for a single gate.

    Used by ``config --enable`` to warn about missing prerequisites
    immediately after a gate is enabled.
    """
    from slopmop.checks import ensure_checks_registered

    ensure_checks_registered()
    registry = get_registry()
    check = registry.get_check(gate_name, config)
    report = DoctorReport(project_root=str(project_root))
    if check is not None:
        _check_gate_readiness(report, check, project_root, verbose=False)
    return report


# ── CLI entry point ────────────────────────────────────────────────


def cmd_doctor(args: Any) -> int:
    """Handle the doctor verb from argparse."""
    checks = getattr(args, "checks", None)
    if checks is not None and len(checks) == 0:
        checks = None

    return run_doctor(
        project_root=getattr(args, "project_root", "."),
        fix=getattr(args, "fix", False),
        checks_filter=checks,
        list_checks=getattr(args, "list_checks", False),
        json_output=getattr(args, "json_output", None),
        verbose=getattr(args, "verbose", False),
        quiet=getattr(args, "quiet", False),
    )
