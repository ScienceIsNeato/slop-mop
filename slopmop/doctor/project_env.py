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

``project.js_deps`` — lockfile-vs-``node_modules`` mismatch detection.
``SKIP`` when no ``package.json``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from slopmop.checks.mixins import (
    PYTHON_SOURCE_PROJECT_VENV,
    PythonCheckMixin,
    detect_js_package_manager,
    has_node_modules,
    has_package_json,
    has_project_venv,
    resolve_project_python,
    suggest_js_install_command,
)
from slopmop.doctor.base import DoctorCheck, DoctorContext, DoctorResult


def _has_python_markers(root: Path) -> bool:
    """Loose "is this a Python project" — manifest presence only."""
    return any(
        (root / name).exists()
        for name in ("pyproject.toml", "setup.py", "requirements.txt", "Pipfile")
    )


class ProjectVenvCheck(DoctorCheck):
    name = "project.python_venv"
    description = "Project-local venv/ or .venv/ discoverable"

    def run(self, ctx: DoctorContext) -> DoctorResult:
        root = ctx.project_root
        if not _has_python_markers(root):
            return self._skip("no Python project markers")

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
            return self._skip("no Python project markers")

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


class ProjectJsDepsCheck(DoctorCheck):
    name = "project.js_deps"
    description = "JS package manager + node_modules presence"

    def run(self, ctx: DoctorContext) -> DoctorResult:
        root = ctx.project_root
        if not has_package_json(root):
            return self._skip("no package.json")

        pm = detect_js_package_manager(root)
        have_modules = has_node_modules(root)

        data: dict[str, object] = {
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
