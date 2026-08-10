"""Hull grade: the deterministic quality rating for a full validation run.

Every full swab/scour run rates the repo's hull — the nautical answer to
"what grade is this codebase?" Two surfaces, one scale: a traditional
letter grade (the universal API, e.g. for CI annotations and badges) and
the boat-condition name (the brand):

    A+   shipshape    0 failing, 0 warnings
    A    seaworthy    0 failing, 1+ warnings
    B    serviceable  1 gate failing
    C    weathered    2 gates failing
    D    fouled       3 gates failing
    F    scuttled     4+ gates failing
    N/A  dry-dock     repo never initialized (no slop-mop config)

Determinism contract:

- "Failing" counts FAILED and ERROR gates among the gates that ran.
  SKIPPED and NOT_APPLICABLE gates never count toward the grade.
- The grade is computed only for full-suite runs (``sm swab`` /
  ``sm scour`` without ``-g``) — partial runs can't rate the hull.
- Any operational skip (missing tool, fail-fast, time budget) marks the
  grade ``provisional``: the same commit could grade differently on a
  machine where those gates ran. A non-provisional grade is a pure
  function of (commit content, gate config).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Union

#: (grade, level) in best-to-worst order. The index is the number of
#: failing gates that earns the entry (beyond index 3, everything is F).
_GRADE_BY_FAILING = (
    ("A+", "shipshape"),  # 0 failing, no warnings (A if warned)
    ("B", "serviceable"),  # 1 failing
    ("C", "weathered"),  # 2 failing
    ("D", "fouled"),  # 3 failing
    ("F", "scuttled"),  # 4+ failing
)


@dataclass(frozen=True)
class HullGrade:
    """A computed hull rating for one validation run."""

    grade: str  # "A+", "A", "B", "C", "D", "F", "N/A"
    level: str  # "shipshape" ... "scuttled", "dry-dock"
    failing: int
    warned: int
    provisional: bool = False
    #: Total findings across failing gates. The letter only counts FAILING
    #: GATES, so a legacy repo sits at F (4+ failing) through an enormous
    #: amount of real work — clearing 3 gates and 65% of findings can leave
    #: the letter untouched, which reads as "nothing happened" to exactly the
    #: inherited-codebase user `sm refit` exists to serve. This number moves
    #: every pass, so progress is visible before the grade changes.
    findings: int = 0
    #: Findings in the previous run, when a baseline is available, so the
    #: delta can be rendered. ``None`` means "no prior run to compare".
    previous_findings: Optional[int] = None

    @property
    def findings_delta(self) -> Optional[int]:
        """Change in findings vs the previous run (negative is improvement)."""
        if self.previous_findings is None:
            return None
        return self.findings - self.previous_findings

    @property
    def progress_note(self) -> str:
        """Sub-line under the letter, e.g. ``20 findings (down 37)``."""
        if not self.findings and self.previous_findings is None:
            return ""
        noun = "finding" if self.findings == 1 else "findings"
        delta = self.findings_delta
        if delta is None or delta == 0:
            return f"{self.findings} {noun}"
        direction = "down" if delta < 0 else "up"
        return f"{self.findings} {noun} ({direction} {abs(delta)})"

    @property
    def label(self) -> str:
        """Human-facing one-liner, e.g. ``B — serviceable``."""
        suffix = " (provisional)" if self.provisional else ""
        note = self.progress_note
        tail = f" · {note}" if note else ""
        return f"{self.grade} — {self.level}{suffix}{tail}"

    def to_dict(self) -> Dict[str, Union[str, int, bool, None]]:
        payload: Dict[str, Union[str, int, bool, None]] = {
            "grade": self.grade,
            "level": self.level,
            "failing": self.failing,
            "warned": self.warned,
            "provisional": self.provisional,
            "findings": self.findings,
        }
        if self.previous_findings is not None:
            payload["previous_findings"] = self.previous_findings
            payload["findings_delta"] = self.findings_delta
        return payload


def compute_hull_grade(
    failing: int,
    warned: int,
    provisional: bool = False,
    findings: int = 0,
    previous_findings: Optional[int] = None,
) -> HullGrade:
    """Map failing/warned gate counts onto the grade scale.

    ``findings``/``previous_findings`` do not affect the letter — that
    contract is depended on by consumers (the GitHub Action's
    ``minimum-grade`` input). They ride alongside so a run can show motion
    the coarse A–F scale cannot.
    """
    if failing <= 0:
        grade, level = ("A", "seaworthy") if warned > 0 else ("A+", "shipshape")
    else:
        grade, level = _GRADE_BY_FAILING[min(failing, 4)]
    # previous_findings arrives from persisted JSON. bool is a subclass of
    # int and a negative count is corrupt — both would yield a false delta.
    if (
        isinstance(previous_findings, bool)
        or previous_findings is not None
        and (not isinstance(previous_findings, int) or previous_findings < 0)
    ):
        previous_findings = None
    return HullGrade(
        grade=grade,
        level=level,
        failing=max(failing, 0),
        warned=max(warned, 0),
        provisional=provisional,
        findings=max(findings, 0),
        previous_findings=previous_findings,
    )


def dry_dock_grade() -> HullGrade:
    """The not-yet-initialized rating — the boat isn't in the water."""
    return HullGrade(
        grade="N/A", level="dry-dock", failing=0, warned=0, provisional=False
    )


def is_repo_initialized(project_root: str) -> bool:
    """True when the repo has adopted slop-mop configuration.

    Either an ``.sb_config.json`` (written by ``sm init``) or a committed
    ``[tool.slopmop]`` section in pyproject.toml counts — both are real
    adoption signals. Repos with neither grade as dry-dock rather than
    being scuttled by default-gate failures they never opted into.
    """
    root = Path(project_root)
    if (root / ".sb_config.json").exists():
        return True
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text(encoding="utf-8")
            if re.search(r"^\s*\[tool\.slopmop[.\]]", content, re.MULTILINE):
                return True
        except (OSError, UnicodeDecodeError):
            # Unreadable/undecodable pyproject — treat as not initialized
            # rather than crashing report construction.
            pass
    return False
