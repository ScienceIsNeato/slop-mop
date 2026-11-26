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

import os
import subprocess  # nosec B404 - this module exists to wrap it safely
from typing import Any, List, Optional, cast

from slopmop.checks.timeouts import SLOW_TOOL_TIMEOUT

__all__ = ["bounded_run", "git_env"]

# GIT_* variables that only restrict where git may look. Keeping them is
# strictly safer than dropping them: the risk being guarded against is a
# probe resolving to the wrong repository, and these make that less likely,
# not more. Everything else is a pointer and goes.
_GIT_SCOPE_NARROWING_VARS = frozenset({"GIT_CEILING_DIRECTORIES"})


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


def git_env(base: Optional[dict[str, str]] = None) -> dict[str, str]:
    """An environment with git's repository pointers removed.

    Git sets GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE and friends for the
    commands it invokes, so that a hook operates on the repository that
    triggered it. slop-mop runs *from* a hook, and then runs git against
    whatever project it is scanning — which is not necessarily that
    repository.

    Inheriting those pointers makes the answer wrong rather than absent:
    asking `git -C <other-repo> rev-parse --git-common-dir` under a leaked
    GIT_DIR returns the launching checkout, so worktree detection can borrow
    a completely different project's virtualenv and report success.

    Every ``GIT_*`` variable goes except those that only *narrow* where git
    may look. The distinction matters: dropping a pointer stops git being
    redirected, but dropping a restriction lets it search further than the
    user allowed. ``GIT_CEILING_DIRECTORIES`` is the live case — remove it
    and the probe can walk up into an ancestor checkout, so a project that
    is in no repository at all resolves to one and borrows its virtualenv.
    """
    env = dict(base if base is not None else os.environ)
    return {
        k: v
        for k, v in env.items()
        if not k.startswith("GIT_") or k in _GIT_SCOPE_NARROWING_VARS
    }
