"""Which invocation the current gates are running under.

A few gates are worth checking on every commit but should only *block* before
a PR goes out. They need to know whether this is a swab or a scour, and that
is known in exactly one place — the CLI entry point — and nowhere along the
registry → executor → check path.

Deliberately process-local rather than an environment variable. Gates spawn
subprocesses, including the project's own test suite, and an env marker is
inherited by all of them: a repo whose tests exercise such a gate would get
different behaviour depending on which slop-mop command launched pytest. That
is a real bug, not a test artefact, and it is avoided entirely by keeping the
value out of the environment.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

__all__ = ["current_run_level", "run_level", "set_run_level"]

_RUN_LEVEL: Optional[str] = None


def set_run_level(level: Optional[str]) -> None:
    """Record the invocation level, or clear it when there isn't one."""
    global _RUN_LEVEL
    _RUN_LEVEL = level


def current_run_level() -> Optional[str]:
    """The invocation level, or None for a targeted ``-g`` run.

    None means "no level was declared", and callers should take the stricter
    reading: a targeted invocation must never report more softly than the
    scour it stands in for.
    """
    return _RUN_LEVEL


@contextmanager
def run_level(level: Optional[str]) -> Iterator[None]:
    """Scope the run level to a block, restoring whatever was set before."""
    previous = _RUN_LEVEL
    set_run_level(level)
    try:
        yield
    finally:
        set_run_level(previous)
