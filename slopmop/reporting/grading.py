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
from typing import Dict, Union

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

    @property
    def label(self) -> str:
        """Human-facing one-liner, e.g. ``B — serviceable``."""
        suffix = " (provisional)" if self.provisional else ""
        return f"{self.grade} — {self.level}{suffix}"

    def to_dict(self) -> Dict[str, Union[str, int, bool]]:
        return {
            "grade": self.grade,
            "level": self.level,
            "failing": self.failing,
            "warned": self.warned,
            "provisional": self.provisional,
        }


def compute_hull_grade(
    failing: int, warned: int, provisional: bool = False
) -> HullGrade:
    """Map failing/warned gate counts onto the grade scale."""
    if failing <= 0:
        grade, level = ("A", "seaworthy") if warned > 0 else ("A+", "shipshape")
    else:
        grade, level = _GRADE_BY_FAILING[min(failing, 4)]
    return HullGrade(
        grade=grade,
        level=level,
        failing=max(failing, 0),
        warned=max(warned, 0),
        provisional=provisional,
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
