"""Runtime/platform introspection checks.

``runtime.platform`` — pure information dump: Python version, OS, arch,
the slopmop version running, where ``sys.executable`` points.  Always
OK; its value is the detail block in a bug report.

``runtime.sm_resolution`` — answers "which ``sm`` would a bare ``sm``
invocation hit, and is that the same binary doctor is running from?"
The classic failure here is a development ``.envrc`` that prepends the
repo's venv to PATH, shadowing a pipx install — or the reverse.  We
walk ``PATH`` entry-by-entry (not just ``shutil.which``) so we can list
*all* ``sm`` candidates, not just the first.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path
from typing import List

from slopmop import __version__
from slopmop.doctor.base import DoctorCheck, DoctorContext, DoctorResult


class PlatformCheck(DoctorCheck):
    name = "runtime.platform"
    description = "Python/OS/arch and slopmop version summary"

    def run(self, ctx: DoctorContext) -> DoctorResult:
        py_version = platform.python_version()
        py_impl = platform.python_implementation()
        os_name = platform.system()
        os_release = platform.release()
        machine = platform.machine()

        summary = (
            f"Python {py_version} ({py_impl}) on {os_name} {os_release} "
            f"{machine} — slopmop {__version__}"
        )

        detail_lines = [
            f"Python:      {py_version} ({py_impl})",
            f"Executable:  {sys.executable}",
            f"OS:          {os_name} {os_release}",
            f"Arch:        {machine}",
            f"slopmop:     {__version__}",
            f"Cwd:         {Path.cwd()}",
            f"Project:     {ctx.project_root}",
        ]

        return self._ok(
            summary,
            detail="\n".join(detail_lines),
            data={
                "python_version": py_version,
                "python_implementation": py_impl,
                "python_executable": sys.executable,
                "os": os_name,
                "os_release": os_release,
                "machine": machine,
                "slopmop_version": __version__,
                "project_root": str(ctx.project_root),
            },
        )


def _find_all_on_path(name: str) -> List[str]:
    """Return every ``name`` (or ``name.exe``/``.cmd``/``.bat``) on ``PATH``."""
    found: List[str] = []
    seen: set[str] = set()
    raw_path = os.environ.get("PATH", "")
    exts = [""] if os.name != "nt" else ["", ".exe", ".cmd", ".bat"]
    for entry in raw_path.split(os.pathsep):
        if not entry:
            continue
        for ext in exts:
            candidate = Path(entry) / f"{name}{ext}"
            if candidate.is_file() and os.access(candidate, os.X_OK):
                resolved = str(candidate.resolve())
                if resolved not in seen:
                    seen.add(resolved)
                    found.append(resolved)
    return found


class SmResolutionCheck(DoctorCheck):
    name = "runtime.sm_resolution"
    description = "Active sm binary and PATH collision detection"

    def _check_sm_collision(
        self,
        first: str,
        all_sm: List[str],
        project_root: "Path",
        data: "dict[str, object]",
    ) -> DoctorResult:
        def _is_project_owned(p: str) -> bool:
            rp = Path(p).resolve()
            try:
                return rp.is_relative_to(project_root)
            except (TypeError, ValueError):
                return False

        active_is_project = _is_project_owned(first)
        detail_lines = ["Multiple ``sm`` entries on PATH (first wins):"]
        for i, path in enumerate(all_sm):
            marker = " ← active" if i == 0 else ""
            detail_lines.append(f"  {i+1}. {path}{marker}")

        if active_is_project:
            detail_lines += [
                "",
                "Active binary is in the project venv — other entries are shadowed.",
            ]
            return self._ok(
                f"sm resolves to {first} (project venv)",
                detail="\n".join(detail_lines),
                data=data,
            )

        detail_lines += [
            "",
            "If this isn't the ``sm`` you expect, adjust PATH ordering or remove the shadowing install.",
        ]
        return self._warn(
            f"{len(all_sm)} sm binaries on PATH",
            detail="\n".join(detail_lines),
            fix_hint=(
                "type -a sm  # POSIX\n"
                "where.exe sm  # Windows\n"
                "Remove or reorder the unwanted entry."
            ),
            data=data,
        )

    def run(self, ctx: DoctorContext) -> DoctorResult:
        # Compute all candidates first so we can fall back to _find_all_on_path
        # on Windows where shutil.which() ignores extensionless scripts.
        all_sm = _find_all_on_path("sm")
        first = shutil.which("sm") or (all_sm[0] if all_sm else None)

        import slopmop

        pkg_root = Path(slopmop.__file__).resolve().parent

        data: dict[str, object] = {
            "which_sm": first,
            "all_sm_on_path": all_sm,
            "slopmop_package": str(pkg_root),
            "sys_executable": sys.executable,
        }

        if not first:
            from slopmop.cli.upgrade import _running_from_source_checkout

            if _running_from_source_checkout():
                return self._warn(
                    "sm not on PATH (source checkout)",
                    detail=(
                        "Running from a source checkout — ``sm`` is not on PATH.\n"
                        "Invoke via ``python -m slopmop.sm`` or install with "
                        "``pip install -e .`` to get the ``sm`` entry point."
                    ),
                    data=data,
                )
            return self._fail(
                "sm not found on PATH",
                detail=(
                    "No ``sm`` executable on PATH.  Users cannot run "
                    "``sm swab``/``sm scour``."
                ),
                fix_hint="pipx install slopmop  # or  pip install slopmop",
                data=data,
            )

        if len(all_sm) > 1:
            return self._check_sm_collision(first, all_sm, ctx.project_root, data)

        return self._ok(
            f"sm resolves to {first}",
            detail=f"Single ``sm`` on PATH: {first}\nPackage:   {pkg_root}",
            data=data,
        )
