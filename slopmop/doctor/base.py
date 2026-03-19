"""Base types for ``sm doctor`` — status, result, context, check ABC.

Lives in its own module so concrete check modules
(``runtime.py``, ``state.py``, …) can import these without tripping a
circular import through ``doctor/__init__.py``, which needs to import
the concrete checks to build the registry.
"""

from __future__ import annotations

import abc
import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Dict


class DoctorStatus(str, enum.Enum):
    """Outcome of a single check.

    ``OK``   — healthy, nothing to do.
    ``WARN`` — suboptimal but not blocking; exit code stays 0.
    ``FAIL`` — broken; contributes exit code 1.
    ``SKIP`` — not applicable to this project (e.g. no ``package.json``).
    """

    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


# Sort/display order — worst first in the summary table.
_STATUS_ORDER = {
    DoctorStatus.FAIL: 0,
    DoctorStatus.WARN: 1,
    DoctorStatus.OK: 2,
    DoctorStatus.SKIP: 3,
}


@dataclass
class DoctorResult:
    """What a check returns.

    ``summary`` is a single line, always present, shown in the table.
    ``detail`` is multi-line, shown only for non-OK results in human
    output and always in ``--json``.  ``fix_hint`` is a copy-pastable
    next step — usually a shell command.  ``data`` carries structured
    context for ``--json`` consumers and for the ``--fix`` re-run.
    """

    name: str
    status: DoctorStatus
    summary: str
    detail: str | None = None
    fix_hint: str | None = None
    can_fix: bool = False
    data: Dict[str, Any] = field(default_factory=lambda: {})

    def sort_key(self) -> tuple[int, str]:
        return (_STATUS_ORDER[self.status], self.name)


@dataclass(frozen=True)
class DoctorContext:
    """Immutable per-run state handed to every check.

    No config dependency — doctor has to work when config is broken.
    """

    project_root: Path
    apply_fix: bool = False


class DoctorCheck(abc.ABC):
    """Base class for a named diagnostic.

    ``name`` is the stable identifier used on the CLI
    (``sm doctor state.lock``) and in JSON output.  It never changes
    once published — treat it as API.

    ``description`` is a short human sentence shown by
    ``sm doctor --list-checks``.

    ``can_fix`` gates whether ``fix()`` is ever called — checks that
    only report (no repair) leave it False and inherit the default
    ``fix()`` that raises.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    can_fix: ClassVar[bool] = False

    @abc.abstractmethod
    def run(self, ctx: DoctorContext) -> DoctorResult:  # pragma: no cover — abstract
        ...

    def fix(self, ctx: DoctorContext) -> DoctorResult:
        """Attempt repair.  Only called when ``can_fix`` is True.

        Must return a fresh result reflecting the post-repair state.
        A return of ``FAIL`` means the fix itself failed; ``OK`` means
        the problem is gone.
        """
        raise NotImplementedError(f"{self.name} does not support --fix")

    # Convenience constructors to keep check bodies terse ---------------

    def _ok(self, summary: str, **kw: Any) -> DoctorResult:
        return DoctorResult(self.name, DoctorStatus.OK, summary, **kw)

    def _warn(self, summary: str, **kw: Any) -> DoctorResult:
        return DoctorResult(
            self.name, DoctorStatus.WARN, summary, can_fix=self.can_fix, **kw
        )

    def _fail(self, summary: str, **kw: Any) -> DoctorResult:
        return DoctorResult(
            self.name, DoctorStatus.FAIL, summary, can_fix=self.can_fix, **kw
        )

    def _skip(self, summary: str, **kw: Any) -> DoctorResult:
        return DoctorResult(self.name, DoctorStatus.SKIP, summary, **kw)
