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
# not more.
_GIT_SCOPE_NARROWING_VARS = frozenset({"GIT_CEILING_DIRECTORIES"})

# GIT_CONFIG_* carries configuration, not location. GIT_CONFIG_COUNT with
# GIT_CONFIG_KEY_n/GIT_CONFIG_VALUE_n is git's documented way to pass
# `-c key=value` through the environment, and GIT_CONFIG_GLOBAL /
# GIT_CONFIG_SYSTEM choose which config files are read at all.
#
# Dropping them breaks two live cases in opposite directions. A container
# that grants `safe.directory` this way loses that trust, so a worktree owned
# by another user stops resolving and the probe returns nothing — the gate
# then skips while reporting a pass, which is the #367 failure coming back by
# another road. And this repo's own test suite points GIT_CONFIG_GLOBAL /
# GIT_CONFIG_SYSTEM at empty files precisely to keep a machine-wide
# core.hooksPath out of test repositories, so scrubbing them hands the
# developer's real ~/.gitconfig to tests that asked to be isolated from it.
#
# Keeping them cannot reintroduce the leak this scrubber exists to stop: git
# never exports GIT_CONFIG_* to hooks. That leak arrives as GIT_DIR and
# friends, which still go.
_GIT_CONFIG_PREFIX = "GIT_CONFIG_"


def _survives_scrub(name: str) -> bool:
    """Whether *name* is kept in an environment used to probe git.

    Anything that is not a ``GIT_*`` variable is none of this function's
    business. Among the ``GIT_*`` ones, those that restrict discovery or
    carry configuration stay; the default for everything else is still
    deny, so a variable git grows tomorrow is dropped until it is listed.
    """
    if not name.startswith("GIT_"):
        return True
    return name in _GIT_SCOPE_NARROWING_VARS or name.startswith(_GIT_CONFIG_PREFIX)


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

    Every ``GIT_*`` variable goes except those that *narrow* where git may
    look or *configure* how it behaves once it gets there. The distinction
    matters in both directions: dropping a pointer stops git being
    redirected, but dropping a restriction lets it search further than the
    caller allowed, and dropping configuration takes away trust and
    isolation the caller deliberately granted. See the two keep-lists above
    for the cases that made each of those concrete.
    """
    env = dict(base if base is not None else os.environ)
    return {k: v for k, v in env.items() if _survives_scrub(k)}
