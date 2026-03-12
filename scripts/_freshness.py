"""Shared freshness-check helpers for generated-doc scripts.

Used by ``gen_workflow_diagrams.py`` and ``generate_readme_tables.py`` to
avoid duplicating the stale/up-to-date reporting strings.
"""

from __future__ import annotations

from pathlib import Path

MSG_UP_TO_DATE = "UP TO DATE"
MSG_STALE = "STALE"


def report_up_to_date(path: Path) -> None:
    print(f"{MSG_UP_TO_DATE}: {path}")


def report_stale(path: Path) -> None:
    print(f"{MSG_STALE}: {path} is out of date")


def report_missing(path: Path) -> None:
    print(f"{MSG_STALE}: {path} does not exist")
