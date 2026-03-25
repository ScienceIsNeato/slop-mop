"""``sm doctor`` — environment diagnostics with a narrow repair surface.

The point is to collapse the "why isn't slop-mop doing what I expect"
debugging loop into a single command that reports reality: which sm
binary is running, which tools it can see, whether the project has the
dependency environment it needs, and whether ``.slopmop/`` state is
healthy.

Every check reuses the same resolution logic the gates use at runtime
(``find_tool()``, project-python discovery, lock-stale detection) so
doctor reports what the gates will actually experience — not a parallel
interpretation of the environment.

``--fix`` is deliberately narrow.  It only repairs state that slop-mop
itself owns: stale lock files, a missing or non-writable ``.slopmop/``
directory, a corrupted config with a backup available.  It never
installs packages, never creates project venvs, never touches
``node_modules``.  Hints for those are printed, not executed.

Check contract
--------------
Checks subclass :class:`DoctorCheck`, declare a stable dotted ``name``
(e.g. ``"state.lock"``), and implement ``run()``.  Checks that can
self-heal set ``can_fix = True`` and implement ``fix()``.  Results are
data only — status, a one-line summary, optional detail, an optional
copy-pastable fix hint, and a ``data`` dict for ``--json``.

The registry is explicit, not discovery-based: every check is imported
and listed in ``ALL_CHECKS`` below.  New checks get added there and
nowhere else.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

from slopmop.doctor.base import (
    DoctorCheck,
    DoctorContext,
    DoctorResult,
    DoctorStatus,
)
from slopmop.doctor.project_env import (
    ProjectJsDepsCheck,
    ProjectPipCheck,
    ProjectVenvCheck,
)
from slopmop.doctor.runtime import PlatformCheck, SmResolutionCheck
from slopmop.doctor.sm_env import (
    GateReadinessCheck,
    InstallModeCheck,
    PypiVersionCheck,
    SmPipCheck,
    ToolInventoryCheck,
)
from slopmop.doctor.state import (
    StateConfigCheck,
    StateDirCheck,
    StateLockCheck,
)

__all__ = [
    "DoctorCheck",
    "DoctorContext",
    "DoctorResult",
    "DoctorStatus",
    "ALL_CHECKS",
    "CHECKS_BY_NAME",
    "select_checks",
    "run_checks",
    "run_fixes",
]

# Explicit registry.  Order = default execution order: cheap local
# checks first, then those that may shell out.
ALL_CHECKS: List[type[DoctorCheck]] = [
    PlatformCheck,
    SmResolutionCheck,
    InstallModeCheck,
    PypiVersionCheck,
    SmPipCheck,
    ToolInventoryCheck,
    GateReadinessCheck,
    ProjectVenvCheck,
    ProjectPipCheck,
    ProjectJsDepsCheck,
    StateLockCheck,
    StateDirCheck,
    StateConfigCheck,
]

CHECKS_BY_NAME: Dict[str, type[DoctorCheck]] = {c.name: c for c in ALL_CHECKS}


def select_checks(patterns: Sequence[str] | None) -> List[type[DoctorCheck]]:
    """Return check classes matching *patterns* (fnmatch), or all when empty."""
    if not patterns:
        return list(ALL_CHECKS)
    from fnmatch import fnmatch

    selected: List[type[DoctorCheck]] = []
    for cls in ALL_CHECKS:
        if any(fnmatch(cls.name, p) for p in patterns):
            selected.append(cls)
    return selected


def run_checks(
    ctx: DoctorContext, patterns: Sequence[str] | None = None
) -> List[DoctorResult]:
    """Run selected checks and return their results.

    Each check is wrapped in a broad except so a single crashing check
    doesn't take down the whole report — the crash becomes a ``FAIL``
    result with the exception text in ``detail``.
    """
    results: List[DoctorResult] = []
    for cls in select_checks(patterns):
        check = cls()
        try:
            results.append(check.run(ctx))
        except Exception as exc:  # noqa: BLE001 — doctor must survive check crashes
            results.append(
                DoctorResult(
                    name=cls.name,
                    status=DoctorStatus.FAIL,
                    summary="check crashed",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
    return results


def run_fixes(
    ctx: DoctorContext, results: Sequence[DoctorResult]
) -> Dict[str, DoctorResult]:
    """Attempt ``fix()`` for every fixable, non-OK result.

    Returns a mapping ``{check_name: post_fix_result}``.  Checks that
    are already OK or can't fix are skipped.  A fix that raises becomes
    a FAIL result — the broken state is still broken.
    """
    fixed: Dict[str, DoctorResult] = {}
    for result in results:
        if result.status == DoctorStatus.OK or not result.can_fix:
            continue
        cls = CHECKS_BY_NAME.get(result.name)
        if cls is None or not cls.can_fix:
            continue
        check = cls()
        try:
            fixed[result.name] = check.fix(ctx)
        except Exception as exc:  # noqa: BLE001
            fixed[result.name] = DoctorResult(
                name=result.name,
                status=DoctorStatus.FAIL,
                summary="fix crashed",
                detail=f"{type(exc).__name__}: {exc}",
            )
    return fixed
