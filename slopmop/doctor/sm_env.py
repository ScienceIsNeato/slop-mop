"""slop-mop's own environment health.

Three checks, all about the Python that *slop-mop itself* runs in —
not the user's project.

``sm_env.install_mode`` — pipx, venv, editable, system?  Reported for
the user's benefit and so we know which upgrade path applies.

``sm_env.pip_check`` — does slop-mop's own dependency set resolve
cleanly?  A FAIL here means the slopmop install itself is broken
(conflicting pins, partial install).  We don't offer ``--fix`` —
reinstalling inside a pipx-managed env via raw ``pip install`` is a
footgun.  The hint points to the right reinstall command.

``sm_env.tool_inventory`` — the check that actually tells you why gates
are skipping.  Reuses ``REQUIRED_TOOLS`` and ``find_tool()`` so it
reports exactly what the gates will see.  Also sanity-tests each
resolved path against the subprocess validator so the very bug that
prompted this feature (Windows ``.exe`` rejected by the allowlist)
surfaces as a FAIL here rather than a silent gate skip.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Dict, List, Tuple

from slopmop.checks.base import find_tool
from slopmop.cli.detection import REQUIRED_TOOLS
from slopmop.cli.upgrade import classify_install
from slopmop.doctor.base import DoctorCheck, DoctorContext, DoctorResult
from slopmop.subprocess.validator import SecurityError, get_validator


class InstallModeCheck(DoctorCheck):
    name = "sm_env.install_mode"
    description = "How slopmop was installed (pipx/venv/editable/system)"

    _MODE_BLURB = {
        "pipx": "pipx-managed — use ``pipx upgrade slopmop`` or ``sm upgrade``",
        "venv": "virtualenv install — use ``sm upgrade`` or ``pip install -U slopmop``",
        "editable": "editable source checkout — ``sm upgrade`` unavailable; ``git pull``",
        "system": (
            "system Python — ``sm upgrade`` unavailable; consider pipx "
            "for cleaner isolation"
        ),
        "unknown": "install mode could not be determined",
    }

    def run(self, ctx: DoctorContext) -> DoctorResult:
        mode = classify_install()
        data = {"install_mode": mode, "sys_executable": sys.executable}
        blurb = self._MODE_BLURB.get(mode, "")
        summary = f"install mode: {mode}"
        detail = f"Mode:       {mode}\nExecutable: {sys.executable}\n{blurb}"

        if mode in ("pipx", "venv", "editable"):
            return self._ok(summary, detail=detail, data=data)

        # system or unknown: upgrade won't work, but gates still run.
        return self._warn(
            summary,
            detail=detail,
            fix_hint="pipx install slopmop  # recommended install method",
            data=data,
        )


class SmPipCheck(DoctorCheck):
    name = "sm_env.pip_check"
    description = "Dependency integrity of slopmop's own Python env"

    def run(self, ctx: DoctorContext) -> DoctorResult:
        # Direct subprocess rather than SubprocessRunner — doctor must
        # work even when the runner's own config is broken, and
        # ``pip check`` has no side effects worth sandboxing.
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "check"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except FileNotFoundError:
            return self._skip("pip not available")
        except subprocess.TimeoutExpired:
            return self._warn(
                "pip check timed out (>60s)",
                detail="Dependency resolution is taking too long — environment may be very large or broken.",
            )

        data: dict[str, object] = {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }

        if proc.returncode == 0:
            return self._ok("pip check passed", data=data)

        output = (proc.stdout or "") + (proc.stderr or "")
        output = output.strip() or "(no output)"
        return self._fail(
            "pip check found conflicts",
            detail=(
                "slopmop's own Python environment has broken dependencies:\n\n"
                f"{output}\n"
            ),
            fix_hint=_reinstall_hint(),
            data=data,
        )


def _reinstall_hint() -> str:
    mode = classify_install()
    if mode == "pipx":
        return "pipx reinstall slopmop"
    if mode == "editable":
        return "pip install -e '.[all]' --force-reinstall"
    return "pip install --force-reinstall 'slopmop[all]'"


def _group_install_hints(missing: List[Tuple[str, str, str]]) -> str:
    """Collapse per-tool install commands into a single line when possible.

    ``REQUIRED_TOOLS`` repeats the same install command for every tool
    in an extras group.  We dedup here so the user gets one line per
    group instead of six copies of ``pipx install slopmop[security]``.
    """
    unique: List[str] = []
    seen: set[str] = set()
    for _, _, cmd in missing:
        if cmd not in seen:
            seen.add(cmd)
            unique.append(cmd)
    return "\n".join(unique)


class ToolInventoryCheck(DoctorCheck):
    name = "sm_env.tool_inventory"
    description = "Gate-required tools resolvable via find_tool()"

    def run(self, ctx: DoctorContext) -> DoctorResult:
        root = str(ctx.project_root)
        validator = get_validator()

        resolved: Dict[str, str] = {}
        missing: List[Tuple[str, str, str]] = []
        validator_rejects: List[Tuple[str, str]] = []
        seen_tools: set[str] = set()

        for tool_name, check_name, install_cmd in REQUIRED_TOOLS:
            if tool_name in seen_tools:
                # Same tool guards multiple gates — record once.
                if (
                    tool_name not in resolved
                    and (tool_name, check_name, install_cmd) not in missing
                ):
                    missing.append((tool_name, check_name, install_cmd))
                continue
            seen_tools.add(tool_name)

            path = find_tool(tool_name, root)
            if not path:
                missing.append((tool_name, check_name, install_cmd))
                continue

            resolved[tool_name] = path
            # Does the validator actually accept this resolved path?
            # This is the Windows .exe tripwire.
            try:
                validator.validate([path, "--version"])
            except SecurityError as exc:
                validator_rejects.append((tool_name, str(exc).splitlines()[0]))

        data: Dict[str, Any] = {
            "resolved": resolved,
            "missing": [{"tool": t, "gate": g, "install": c} for t, g, c in missing],
            "validator_rejects": [
                {"tool": t, "error": e} for t, e in validator_rejects
            ],
        }

        if validator_rejects:
            detail_lines = [
                "Tools resolved on disk but REJECTED by the subprocess "
                "allowlist — gates will fail at invocation:",
                "",
            ]
            for tool, err in validator_rejects:
                detail_lines.append(f"  {tool:<16} {resolved[tool]}")
                detail_lines.append(f"                   {err}")
            return self._fail(
                f"{len(validator_rejects)} resolved tool(s) rejected by allowlist",
                detail="\n".join(detail_lines),
                fix_hint=(
                    "This is a slopmop bug — please file an issue with this "
                    "output at https://github.com/ScienceIsNeato/slopmop/issues"
                ),
                data=data,
            )

        if missing:
            detail_lines = [
                "Missing tools block these gates:",
                "",
            ]
            for tool, gate, cmd in missing:
                detail_lines.append(f"  {tool:<16} → {gate}")
            return self._fail(
                f"{len(missing)} gate tool(s) missing",
                detail="\n".join(detail_lines),
                fix_hint=_group_install_hints(missing),
                data=data,
            )

        return self._ok(
            f"all {len(resolved)} gate tools resolvable",
            detail="\n".join(f"  {t:<16} {p}" for t, p in sorted(resolved.items())),
            data=data,
        )
