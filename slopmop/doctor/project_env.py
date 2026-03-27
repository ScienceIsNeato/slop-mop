"""Project-environment health checks.

These look at the *target project*, not at slop-mop itself.  They
answer "do the project's own dependencies exist so gates can actually
run meaningful checks against real code?"

None of these have ``--fix`` — creating a venv or running
``npm install`` for the user is overreach.  The hints are explicit and
copy-pastable.

``project.python_venv`` — does a local ``venv/`` or ``.venv/`` exist?
``SKIP`` when the project has no Python markers at all.

``project.pip_check`` — does the project's venv have a coherent
dependency set?  ``SKIP`` when no venv exists (depends on
``project.python_venv``).

``project.js_deps`` — lockfile-vs-``node_modules`` mismatch detection,
or ``deno`` binary presence for Deno projects.
``SKIP`` when no ``package.json`` and no ``deno.json``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple, cast

from slopmop.checks.mixins import (
    PYTHON_SOURCE_PROJECT_VENV,
    PythonCheckMixin,
    detect_js_package_manager,
    has_node_modules,
    has_package_json,
    has_project_venv,
    is_deno_project,
    resolve_project_python,
    suggest_js_install_command,
)
from slopmop.checks.quality.config_debt import _has_python_markers
from slopmop.doctor.base import DoctorCheck, DoctorContext, DoctorResult

_NO_PYTHON_PROJECT_MARKERS = "no Python project markers"


class ProjectVenvCheck(DoctorCheck):
    name = "project.python_venv"
    description = "Project-local venv/ or .venv/ discoverable"

    def run(self, ctx: DoctorContext) -> DoctorResult:
        root = ctx.project_root
        if not _has_python_markers(root):
            return self._skip(_NO_PYTHON_PROJECT_MARKERS)

        if has_project_venv(root):
            python_path, _ = resolve_project_python(root)
            return self._ok(
                f"project venv: {python_path}",
                data={"python": python_path},
            )

        # Figure out what the gates would fall back to so the user
        # knows what's actually being checked against.
        python_path, source = resolve_project_python(root)
        hint = PythonCheckMixin.suggest_venv_command(str(root))

        return self._warn(
            f"no local venv — gates fall back to {source}",
            detail=(
                "No ``venv/`` or ``.venv/`` in project root.  PROJECT-context "
                "gates (tests, coverage, pip-audit) will fall back to:\n"
                f"  {python_path}  ({source})\n\n"
                "This may not have project dependencies installed."
            ),
            fix_hint=f"cd {root} && {hint}",
            data={"fallback_python": python_path, "source": source},
        )


class ProjectPipCheck(DoctorCheck):
    name = "project.pip_check"
    description = "Dependency integrity of the project's own venv"

    def run(self, ctx: DoctorContext) -> DoctorResult:
        root = ctx.project_root
        if not _has_python_markers(root):
            return self._skip(_NO_PYTHON_PROJECT_MARKERS)

        # Only check a true project-local venv — checking sm's own env
        # here would duplicate sm_env.pip_check and confuse the report.
        python_path, source = resolve_project_python(root)
        if source != PYTHON_SOURCE_PROJECT_VENV:
            return self._skip("no project-local venv (see project.python_venv)")

        try:
            proc = subprocess.run(
                [python_path, "-m", "pip", "check"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return self._warn(
                "could not run pip check in project venv",
                detail=f"{type(exc).__name__}: {exc}",
            )

        data: dict[str, object] = {
            "returncode": proc.returncode,
            "python": python_path,
        }

        if proc.returncode == 0:
            return self._ok("project pip check passed", data=data)

        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        hint = PythonCheckMixin.suggest_venv_command(str(root))
        return self._fail(
            "project venv has dependency conflicts",
            detail=(f"Project Python: {python_path}\n\n{output or '(no output)'}\n"),
            fix_hint=(f"# Repair the project venv:\ncd {root} && {hint}"),
            data=data,
        )


class ProjectPipAuditRemediabilityCheck(DoctorCheck):
    """Check whether pip-audit fix versions are installable from this index."""

    name = "project.pip_audit_remediability"
    description = "pip-audit fixes available from project package index"

    @staticmethod
    def _run_pip_audit_json(
        python_path: str, project_root: str
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """Run pip-audit and return parsed JSON report (or None) with raw output."""
        cmd = [python_path, "-m", "pip_audit", "--format", "json"]
        proc = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        try:
            report_any = json.loads(proc.stdout or "")
            if isinstance(report_any, dict):
                report = cast(Dict[str, Any], report_any)
                return report, output
        except json.JSONDecodeError:
            pass
        return None, output

    @staticmethod
    def _can_install_fix_version(
        python_path: str,
        project_root: str,
        package_name: str,
        version: str,
    ) -> Tuple[Optional[bool], str]:
        """Probe whether ``package==version`` is obtainable from current index.

        Returns (True/False/None, output). None means indeterminate due to
        transport/index errors where availability cannot be trusted.
        """
        req = f"{package_name}=={version}"
        proc = subprocess.run(
            [python_path, "-m", "pip", "install", "--dry-run", "--no-deps", req],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if proc.returncode == 0:
            return True, output

        lowered = output.lower()
        no_match = (
            "could not find a version that satisfies the requirement" in lowered
            or "no matching distribution found for" in lowered
        )
        if no_match:
            return False, output

        if "no such option: --dry-run" in lowered:
            # Older pip fallback: ask index for known versions.
            idx = subprocess.run(
                [python_path, "-m", "pip", "index", "versions", package_name],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
            idx_output = ((idx.stdout or "") + (idx.stderr or "")).strip()
            if idx.returncode != 0:
                return None, idx_output
            import re

            pattern = r"(?<![.\d])" + re.escape(version) + r"(?![.\d])"
            return bool(re.search(pattern, idx_output)), idx_output

        return None, output

    @staticmethod
    def _extract_candidate_fix_versions(vulns: List[dict[str, Any]]) -> List[str]:
        candidate_versions: List[str] = []
        for vuln in vulns:
            fixes_any = vuln.get("fix_versions", [])
            if not isinstance(fixes_any, list):
                continue
            fixes_list = cast(List[Any], fixes_any)
            for fix_any in fixes_list:
                if (
                    isinstance(fix_any, str)
                    and fix_any
                    and fix_any not in candidate_versions
                ):
                    candidate_versions.append(fix_any)
        return candidate_versions

    @staticmethod
    def _extract_vuln_ids(vulns: List[dict[str, Any]]) -> List[str]:
        vuln_ids: List[str] = []
        for vuln in vulns:
            vuln_id = vuln.get("id")
            if isinstance(vuln_id, str) and vuln_id:
                vuln_ids.append(vuln_id)
        return vuln_ids

    def _classify_dependency(
        self,
        dep: Dict[str, Any],
        python_path: str,
        project_root: str,
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        name = str(dep.get("name", "?"))
        current_version = str(dep.get("version", "?"))

        vulns_any = dep.get("vulns", [])
        vulns: List[dict[str, Any]] = []
        if isinstance(vulns_any, list):
            vuln_list = cast(List[Any], vulns_any)
            for vuln_any in vuln_list:
                if isinstance(vuln_any, dict):
                    vulns.append(cast(dict[str, Any], vuln_any))

        vuln_ids = self._extract_vuln_ids(vulns)
        candidate_versions = self._extract_candidate_fix_versions(vulns)
        if not candidate_versions:
            return (
                "no_upstream_fix",
                {
                    "name": name,
                    "current_version": current_version,
                    "vuln_ids": vuln_ids,
                },
            )

        installable_found = False
        saw_indeterminate = False
        checked_versions: List[str] = []
        for version in candidate_versions[:5]:
            checked_versions.append(version)
            installable, _probe_output = self._can_install_fix_version(
                python_path,
                project_root,
                name,
                version,
            )
            if installable is True:
                installable_found = True
                break
            if installable is None:
                saw_indeterminate = True

        if installable_found:
            return "remediable", None

        entry: Dict[str, Any] = {
            "name": name,
            "current_version": current_version,
            "vuln_ids": vuln_ids,
            "candidate_fix_versions": checked_versions,
        }
        if saw_indeterminate:
            return "indeterminate", entry
        return "blocked", entry

    def _analyze_vulnerable_dependencies(
        self,
        vulnerable: List[Dict[str, Any]],
        python_path: str,
        project_root: str,
    ) -> Tuple[int, List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        blocked: List[Dict[str, Any]] = []
        no_upstream_fix: List[Dict[str, Any]] = []
        indeterminate: List[Dict[str, Any]] = []
        remediable_count = 0

        for dep in vulnerable:
            outcome, payload = self._classify_dependency(dep, python_path, project_root)
            if outcome == "remediable":
                remediable_count += 1
                continue
            if payload is None:
                continue
            if outcome == "blocked":
                blocked.append(payload)
            elif outcome == "indeterminate":
                indeterminate.append(payload)
            else:
                no_upstream_fix.append(payload)

        return remediable_count, blocked, no_upstream_fix, indeterminate

    @staticmethod
    def _blocked_detail_lines(blocked: List[Dict[str, Any]]) -> List[str]:
        detail_lines = [
            "At least one vulnerable dependency has known fix versions,",
            "but none are installable from the current package index context:",
            "",
        ]
        for item in blocked:
            fixes_any = item.get("candidate_fix_versions", [])
            fixes = ", ".join(str(v) for v in fixes_any)
            vuln_ids_any = item.get("vuln_ids", [])
            vuln_ids = ", ".join(str(v) for v in vuln_ids_any) or "unknown-id"
            detail_lines.append(
                f"  {item['name']} {item['current_version']} ({vuln_ids})"
            )
            detail_lines.append(f"    candidates: {fixes}")
        return detail_lines

    @staticmethod
    def _vulnerable_dependencies(report: Dict[str, Any]) -> List[Dict[str, Any]]:
        dependencies_any = report.get("dependencies", [])
        if not isinstance(dependencies_any, list):
            return []
        dependencies: List[Dict[str, Any]] = []
        dep_list = cast(List[Any], dependencies_any)
        for dep_any in dep_list:
            if not isinstance(dep_any, dict):
                continue
            dep_dict = cast(Dict[str, Any], dep_any)
            if dep_dict.get("vulns"):
                dependencies.append(dep_dict)
        return dependencies

    @staticmethod
    def _analysis_data(
        python_path: str,
        vulnerable_count: int,
        remediable_count: int,
        blocked: List[Dict[str, Any]],
        no_upstream_fix: List[Dict[str, Any]],
        indeterminate: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "python": python_path,
            "vulnerable_count": vulnerable_count,
            "remediable_count": remediable_count,
            "blocked": blocked,
            "no_upstream_fix": no_upstream_fix,
            "indeterminate": indeterminate,
        }

    def run(self, ctx: DoctorContext) -> DoctorResult:
        root = ctx.project_root
        if not _has_python_markers(root):
            return self._skip(_NO_PYTHON_PROJECT_MARKERS)

        python_path, source = resolve_project_python(root)
        if source != PYTHON_SOURCE_PROJECT_VENV:
            return self._skip("no project-local venv (see project.python_venv)")

        try:
            report, raw_output = self._run_pip_audit_json(python_path, str(root))
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return self._warn(
                "could not run pip-audit in project venv",
                detail=f"{type(exc).__name__}: {exc}",
            )

        if report is None:
            return self._fail(
                "could not parse pip-audit output",
                detail=(
                    f"Project Python: {python_path}\n"
                    "pip-audit did not return parseable JSON output.\n\n"
                    f"Output:\n{raw_output or '(no output)'}"
                ),
                fix_hint=(
                    f"cd {root} && {python_path} -m pip install pip-audit\n"
                    "Then rerun: sm doctor project.pip_audit_remediability"
                ),
                data={"python": python_path},
            )

        vulnerable = self._vulnerable_dependencies(report)
        if not vulnerable:
            return self._ok(
                "pip-audit: no vulnerable dependencies",
                data={"python": python_path, "vulnerable_count": 0},
            )

        remediable_count, blocked, no_upstream_fix, indeterminate = (
            self._analyze_vulnerable_dependencies(vulnerable, python_path, str(root))
        )

        data = self._analysis_data(
            python_path,
            len(vulnerable),
            remediable_count,
            blocked,
            no_upstream_fix,
            indeterminate,
        )

        if blocked:
            detail_lines = self._blocked_detail_lines(blocked)
            return self._fail(
                f"{len(blocked)} dependency fix path(s) blocked by package index",
                detail="\n".join(detail_lines),
                fix_hint=(
                    "Publish/mirror one of the candidate fixed versions in the active index.\n"
                    "If temporarily unavoidable, add a scoped ignore in pip_audit_ignore_vulns\n"
                    "with a tracking ticket and expiry."
                ),
                data=data,
            )

        if indeterminate:
            return self._warn(
                f"could not verify installability for {len(indeterminate)} dependency fix path(s)",
                detail=(
                    "pip-audit found vulnerabilities with fix versions, but index/network "
                    "probes were inconclusive."
                ),
                fix_hint="Re-run doctor after index/network is reachable.",
                data=data,
            )

        if no_upstream_fix:
            return self._warn(
                f"{len(no_upstream_fix)} vulnerable dependency/dependencies have no upstream fix",
                detail=(
                    "pip-audit reported vulnerabilities without published fix versions. "
                    "This is not an index-availability blocker."
                ),
                fix_hint=(
                    "Track risk acceptance or alternatives; use pip_audit_ignore_vulns only "
                    "with explicit ticket + expiry."
                ),
                data=data,
            )

        return self._ok(
            f"pip-audit fixes appear installable ({remediable_count}/{len(vulnerable)} vulnerable package(s))",
            data=data,
        )


class ProjectJsDepsCheck(DoctorCheck):
    name = "project.js_deps"
    description = "JS/TS toolchain presence (Node or Deno)"

    def run(self, ctx: DoctorContext) -> DoctorResult:
        root = ctx.project_root

        has_node = has_package_json(root)
        has_deno = is_deno_project(str(root))

        if not has_node and not has_deno:
            return self._skip("no package.json or deno.json")

        # --- Deno path (checked first; a project can have both) ---
        if has_deno:
            return self._check_deno(root)

        # --- Node path ---
        return self._check_node(root)

    def _check_deno(self, root: Any) -> DoctorResult:
        deno_bin = shutil.which("deno")
        data: dict[str, object] = {
            "runtime": "deno",
            "deno_binary": deno_bin,
        }

        if deno_bin:
            return self._ok(
                f"deno — binary found at {deno_bin}",
                data=data,
            )

        return self._warn(
            "deno — binary not found on PATH",
            detail=(
                "Detected deno.json but ``deno`` is not on PATH.  "
                "JS/TS gates (lint, fmt) will skip or fail."
            ),
            fix_hint="Install Deno: https://docs.deno.com/runtime/getting_started/installation/",
            data=data,
        )

    def _check_node(self, root: Any) -> DoctorResult:
        pm = detect_js_package_manager(root)
        have_modules = has_node_modules(root)

        data: dict[str, object] = {
            "runtime": "node",
            "package_manager": pm,
            "has_node_modules": have_modules,
        }

        if have_modules:
            return self._ok(
                f"{pm} — node_modules present",
                data=data,
            )

        return self._warn(
            f"{pm} — node_modules missing",
            detail=(
                f"Detected {pm} (from lockfile) but ``node_modules/`` is "
                "absent.  JS gates (lint, tests) will skip or fail."
            ),
            fix_hint=f"cd {root} && {suggest_js_install_command(root)}",
            data=data,
        )
