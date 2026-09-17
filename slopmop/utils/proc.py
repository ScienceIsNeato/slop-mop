"""Bounded subprocess execution for CLI helpers.

Gate checks go through ``SubprocessRunner``, which has always applied a
timeout. The CLI helpers call :func:`subprocess.run` directly and did not,
so any one of them could wait forever: ``sm upgrade`` ran a full swab of
whatever directory you happened to be standing in and, from a home
directory, hung until the user killed it thirteen minutes later.

A command that never returns is worse than one that fails. Nothing here
decides *what* is reasonable for a given command — the caller still picks
the bound — but there is no longer a way to forget one entirely.
"""

from __future__ import annotations

import subprocess  # nosec B404 - this module exists to wrap it safely
from typing import Any, List, Optional, cast

from slopmop.checks.timeouts import SLOW_TOOL_TIMEOUT

__all__ = ["bounded_run"]


def bounded_run(
    command: List[str],
    *,
    timeout: Optional[int] = None,
    **kwargs: Any,
) -> "subprocess.CompletedProcess[str]":
    """``subprocess.run`` that cannot hang forever.

    ``timeout`` defaults to :data:`SLOW_TOOL_TIMEOUT`, which suits the git and
    ``gh`` invocations these helpers mostly make. Commands that legitimately
    take longer — a package install, a full validation run — pass their own.

    A timeout raises :class:`subprocess.TimeoutExpired` rather than being
    swallowed: callers that can carry on say so explicitly, and the rest get
    a real error instead of silence.
    """
    # **kwargs is untyped by construction, so the concrete CompletedProcess
    # parameter has to be restated rather than inferred.
    return cast(
        "subprocess.CompletedProcess[str]",
        subprocess.run(  # nosec B603 - callers pass a fixed argv, never a shell string
            command,
            timeout=timeout if timeout is not None else SLOW_TOOL_TIMEOUT,
            **kwargs,
        ),
    )
