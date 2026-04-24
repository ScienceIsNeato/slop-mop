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

import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

from slopmop.checks.base import find_tool
from slopmop.cli.detection import REQUIRED_TOOLS
from slopmop.cli.upgrade import UpgradeError, classify_install
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


# ---------------------------------------------------------------------------
# Version-constraint helpers
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?(?:\.\d+)?)")


def _parse_tool_version(tool_path: str) -> Optional[str]:
    """Run ``<tool> --version`` and extract the first semver-like string."""
    try:
        get_validator().validate([tool_path, "--version"])
    except SecurityError:
        return None
    try:
        result = subprocess.run(
            [tool_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = (result.stdout + result.stderr).strip()
        m = _VERSION_RE.search(output)
        return m.group(1) if m else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _check_version_constraint(tool: str, path: str, spec: str) -> Optional[str]:
    """Return an error message if ``tool`` at ``path`` does not satisfy ``spec``.

    Returns ``None`` when the constraint is satisfied or the version cannot
    be determined (conservative: don't warn on unreadable version output).
    """
    try:
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version
    except ImportError:
        return None  # packaging not available — skip silently

    raw = _parse_tool_version(path)
    if raw is None:
        return None  # can't read version — don't false-positive

    try:
        installed = Version(raw)
        if installed not in SpecifierSet(spec):
            return f"found {raw}, requires {spec}"
    except Exception:  # noqa: BLE001
        return None  # malformed spec or version — skip

    return None


class ToolInventoryCheck(DoctorCheck):
    name = "sm_env.tool_inventory"
    description = "Gate-required tools resolvable via find_tool()"

    def _resolve_tools(self, root: str) -> Tuple[
        Dict[str, str],
        List[Tuple[str, str, str]],
        List[Tuple[str, str]],
    ]:
        """Iterate REQUIRED_TOOLS and classify as resolved/missing/rejected."""
        validator = get_validator()
        resolved: Dict[str, str] = {}
        missing: List[Tuple[str, str, str]] = []
        validator_rejects: List[Tuple[str, str]] = []
        seen: set[str] = set()

        for tool_name, check_name, install_cmd in REQUIRED_TOOLS:
            if tool_name in seen:
                continue
            seen.add(tool_name)
            path = find_tool(tool_name, root)
            if not path:
                missing.append((tool_name, check_name, install_cmd))
                continue
            resolved[tool_name] = path
            try:
                validator.validate([path, "--version"])
            except SecurityError as exc:
                validator_rejects.append((tool_name, str(exc).splitlines()[0]))

        return resolved, missing, validator_rejects

    def _collect_version_violations(
        self, resolved: Dict[str, str], root: str
    ) -> List[Tuple[str, str, str]]:
        """Check required_tool_versions constraints for all registered gates."""
        violations: List[Tuple[str, str, str]] = []
        try:
            from slopmop.checks import ensure_checks_registered  # noqa: PLC0415
            from slopmop.core.registry import get_registry  # noqa: PLC0415

            ensure_checks_registered()
            registry = get_registry()
            seen: set[Tuple[str, str]] = set()
            for gate_name in registry.list_checks():
                check_cls = registry._check_classes.get(gate_name)
                if check_cls is None:
                    continue
                for tool, spec in getattr(
                    check_cls, "required_tool_versions", {}
                ).items():
                    key = (tool, spec)
                    if key in seen:
                        continue
                    seen.add(key)
                    path = resolved.get(tool) or find_tool(tool, root)
                    if not path:
                        continue
                    msg = _check_version_constraint(tool, path, spec)
                    if msg:
                        violations.append((tool, gate_name, msg))
        except Exception:  # noqa: BLE001 — advisory only
            pass
        return violations

    def _build_report(
        self,
        resolved: Dict[str, str],
        missing: List[Tuple[str, str, str]],
        validator_rejects: List[Tuple[str, str]],
        version_violations: List[Tuple[str, str, str]],
        data: Dict[str, Any],
    ) -> DoctorResult:
        """Assemble the failure/warning report from collected issues."""
        summary_bits: List[str] = []
        detail_lines: List[str] = []
        fix_lines: List[str] = []

        if validator_rejects:
            summary_bits.append(
                f"{len(validator_rejects)} tool(s) rejected by allowlist"
            )
            detail_lines += [
                "Tools resolved on disk but REJECTED by the subprocess allowlist:",
                "",
            ]
            for tool, err in validator_rejects:
                detail_lines.append(f"  {tool:<16} {resolved[tool]}")
                detail_lines.append(f"                   {err}")
            fix_lines.append(
                "Validator rejects are a slopmop bug — file an issue at "
                "https://github.com/ScienceIsNeato/slopmop/issues"
            )

        if missing:
            summary_bits.append(f"{len(missing)} tool(s) missing")
            if detail_lines:
                detail_lines.append("")
            detail_lines += ["Missing tools block these gates:", ""]
            for tool, gate, _ in missing:
                detail_lines.append(f"  {tool:<16} → {gate}")
            fix_lines.append(_group_install_hints(missing))

        if version_violations:
            summary_bits.append(
                f"{len(version_violations)} version constraint(s) not met"
            )
            if detail_lines:
                detail_lines.append("")
            detail_lines += ["Version constraints not satisfied:", ""]
            for tool, gate, msg in version_violations:
                detail_lines.append(f"  {tool:<16} {msg}  (required by {gate})")

        kw: Dict[str, Any] = {
            "detail": "\n".join(detail_lines),
            "fix_hint": "\n".join(fix_lines) if fix_lines else None,
            "data": data,
        }
        if missing or validator_rejects or version_violations:
            return self._fail("; ".join(summary_bits), **kw)
        return self._warn("; ".join(summary_bits), **kw)

    def run(self, ctx: DoctorContext) -> DoctorResult:
        root = str(ctx.project_root)
        resolved, missing, validator_rejects = self._resolve_tools(root)
        version_violations = self._collect_version_violations(resolved, root)

        data: Dict[str, Any] = {
            "resolved": resolved,
            "missing": [{"tool": t, "gate": g, "install": c} for t, g, c in missing],
            "validator_rejects": [
                {"tool": t, "error": e} for t, e in validator_rejects
            ],
            "version_violations": [
                {"tool": t, "gate": g, "message": m} for t, g, m in version_violations
            ],
        }

        if not missing and not validator_rejects and not version_violations:
            return self._ok(
                f"all {len(resolved)} gate tools resolvable",
                detail="\n".join(f"  {t:<16} {p}" for t, p in sorted(resolved.items())),
                data=data,
            )

        return self._build_report(
            resolved, missing, validator_rejects, version_violations, data
        )


class PypiVersionCheck(DoctorCheck):
    name = "sm_env.pypi_version"
    description = "Installed slopmop version vs latest on PyPI"

    def run(self, ctx: DoctorContext) -> DoctorResult:
        from slopmop.cli.upgrade import (
            _fetch_latest_pypi_version,
            _installed_version,
            _is_editable_install,
            _packaging_version_class,
            _running_from_source_checkout,
        )

        try:
            current = _installed_version()
        except UpgradeError:
            return self._skip("could not determine installed version")

        try:
            latest = _fetch_latest_pypi_version()
        except UpgradeError:
            return self._skip(
                f"slopmop {current} (PyPI unreachable)",
                data={"installed": current, "latest": None},
            )

        data = {"installed": current, "latest": latest}

        try:
            Version = _packaging_version_class()
            is_behind = Version(current) < Version(latest)
        except Exception:
            is_behind = current != latest

        if not is_behind:
            return self._ok(f"slopmop {current} (latest)", data=data)

        # Editable / source-checkout installs can't use ``sm upgrade``
        # — tell the developer the correct path instead.
        is_dev = _running_from_source_checkout() or _is_editable_install()
        if is_dev:
            return self._ok(
                f"slopmop {current} (dev install; {latest} on PyPI)",
                detail=(
                    f"Installed: {current} (editable / source checkout)\n"
                    f"PyPI:      {latest}\n\n"
                    "Version drift is expected in dev mode.  To sync:\n"
                    "  git pull && pip install -e '.[all]'"
                ),
                data=data,
            )

        return self._warn(
            f"slopmop {current} → {latest} available",
            detail=f"Installed: {current}\nLatest:    {latest}",
            fix_hint="sm upgrade",
            data=data,
        )


class GateReadinessCheck(DoctorCheck):
    """Collapsed summary of quality gate readiness.

    Enumerates all registered gates, checks tool availability, and
    reports a single pass/fail/warn result.  Directs the user to
    ``sm doctor --gates`` for the full tree.
    """

    name = "sm_env.gate_readiness"
    description = "Quality gate readiness summary (tool availability)"

    def run(self, ctx: DoctorContext) -> DoctorResult:
        from slopmop.checks import ensure_checks_registered
        from slopmop.checks.base import find_tool
        from slopmop.core.registry import get_registry

        ensure_checks_registered()
        registry = get_registry()
        root = str(ctx.project_root)

        total_gates = 0
        ready_gates = 0
        blocked_gates: List[str] = []
        missing_tools: set[str] = set()

        for name, cls in registry._check_classes.items():
            total_gates += 1
            gate_ok = True
            for tool in cls.required_tools:
                if not find_tool(tool, root):
                    gate_ok = False
                    missing_tools.add(tool)
            if gate_ok:
                ready_gates += 1
            else:
                blocked_gates.append(name)

        data: dict[str, object] = {
            "total_gates": total_gates,
            "ready_gates": ready_gates,
            "blocked_gates": blocked_gates,
            "missing_tools": sorted(missing_tools),
        }

        if not blocked_gates:
            return self._ok(
                f"all {total_gates} gates ready",
                detail=f"Run ``sm doctor --gates`` for the full dependency tree.",
                data=data,
            )

        return self._warn(
            f"{ready_gates}/{total_gates} gates ready, "
            f"{len(blocked_gates)} blocked ({len(missing_tools)} missing tool(s))",
            detail=(
                f"Blocked gates: {', '.join(sorted(blocked_gates)[:5])}"
                + (
                    f" (+{len(blocked_gates) - 5} more)"
                    if len(blocked_gates) > 5
                    else ""
                )
                + f"\nMissing tools: {', '.join(sorted(missing_tools))}"
            ),
            fix_hint="sm doctor --gates   # full dependency tree\n"
            + _group_install_hints(
                [(t, "", cmd) for t, _, cmd in REQUIRED_TOOLS if t in missing_tools]
            ),
            data=data,
        )


class GateDiagnosticsCheck(DoctorCheck):
    """Call each gate's optional ``diagnose()`` hook and surface results.

    Some gates know their own failure modes better than a generic tool-
    presence check does.  For example, a coverage gate might warn that
    there is no ``.coverage`` data file — the most common reason it fails
    even when pytest is installed and working.

    This check iterates all applicable, enabled gates and calls
    ``diagnose(project_root)`` on any that override the default (which
    returns ``[]``).  Results are aggregated by severity: any ``fail``
    returns a FAIL, any ``warn`` returns a WARN, empty → OK.

    Gates that haven't overridden ``diagnose()`` are silently skipped.
    """

    name = "sm_env.gate_diagnostics"
    description = "Gate-specific diagnostics from BaseCheck.diagnose() hooks"

    def run(self, ctx: DoctorContext) -> DoctorResult:
        from slopmop.checks import ensure_checks_registered  # noqa: PLC0415
        from slopmop.checks.base import BaseCheck  # noqa: PLC0415
        from slopmop.checks.custom import register_custom_gates  # noqa: PLC0415
        from slopmop.core.registry import get_registry  # noqa: PLC0415

        ensure_checks_registered()
        config: Dict[str, Any] = {}
        try:
            cfg_path = ctx.project_root / ".sb_config.json"
            if cfg_path.exists():
                import json  # noqa: PLC0415

                loaded: object = json.loads(cfg_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    config = loaded  # type: ignore[assignment]  # narrowed above
        except Exception:  # noqa: BLE001
            pass
        register_custom_gates(config)
        registry = get_registry()

        root = str(ctx.project_root)
        fails: List[Tuple[str, str, str]] = []  # (gate, summary, detail)
        warns: List[Tuple[str, str, str]] = []

        from slopmop.doctor.gate_preflight import _gate_enabled  # noqa: PLC0415

        for gate_name, check_cls in registry._check_classes.items():
            # Only bother calling diagnose() on gates that override it.
            if check_cls.diagnose is BaseCheck.diagnose:
                continue

            # Skip gates disabled in config.
            if not _gate_enabled(config, gate_name):
                continue

            try:
                instance: BaseCheck = check_cls(config=config)
                # Skip gates not applicable to this project.
                if not instance.is_applicable(root):
                    continue
                results = instance.diagnose(root)
            except Exception:  # noqa: BLE001 — gate author error → skip
                continue

            for r in results:
                if r.severity == "fail":
                    fails.append((gate_name, r.summary, r.detail or ""))
                elif r.severity == "warn":
                    warns.append((gate_name, r.summary, r.detail or ""))
                # "ok" and unknown severities are silently ignored

        data: Dict[str, Any] = {
            "fails": [{"gate": g, "summary": s} for g, s, _ in fails],
            "warns": [{"gate": g, "summary": s} for g, s, _ in warns],
        }

        if not fails and not warns:
            return self._ok("no gate-specific diagnostics reported", data=data)

        lines: List[str] = []
        if fails:
            lines.append(f"FAIL ({len(fails)} gate(s)):")
            for gate, summary, detail in fails:
                lines.append(f"  [{gate}] {summary}")
                if detail:
                    for dl in detail.splitlines():
                        lines.append(f"    {dl}")
        if warns:
            if lines:
                lines.append("")
            lines.append(f"WARN ({len(warns)} gate(s)):")
            for gate, summary, detail in warns:
                lines.append(f"  [{gate}] {summary}")
                if detail:
                    for dl in detail.splitlines():
                        lines.append(f"    {dl}")

        if fails:
            return self._fail(
                f"{len(fails)} gate(s) reported diagnostic failures",
                detail="\n".join(lines),
                data=data,
            )
        return self._warn(
            f"{len(warns)} gate(s) reported diagnostic warnings",
            detail="\n".join(lines),
            data=data,
        )
