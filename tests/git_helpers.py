"""Running git from a test, independent of who launched pytest.

Git hooks export GIT_DIR, GIT_INDEX_FILE and friends so that hooked commands
operate on the repository that invoked them. slop-mop's own pre-commit hook
runs the test suite, so those variables are present for every test it spawns —
and a test that builds its own repository in a tmp directory then has its git
commands quietly redirected at slop-mop's checkout instead.

The symptom is invisible until it isn't: eight worktree tests that pass under
`pytest` fail with exit 128 under `git commit`, and the gate reports
"0 test(s) failed" because pytest errored during setup rather than failing an
assertion.

Same shape as the run-level marker that used to be an environment variable:
anything inherited by a spawned test suite becomes part of its behaviour.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, Optional, Sequence


def clean_git_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """A copy of os.environ with git's repository pointers removed.

    Every ``GIT_*`` variable goes, not just the three that bite today: the
    point is that a test's git commands answer to the test's repository and
    nothing else, whoever started the process.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    if extra:
        env.update(extra)
    return env


def run_git(
    *args: str,
    cwd: Path,
    check: bool = True,
) -> "subprocess.CompletedProcess[bytes]":
    """Run git in *cwd*, isolated from any inherited repository context."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        env=clean_git_env(),
    )


def init_repo(root: Path, *, user: str = "t", email: str = "t@t.t") -> None:
    """Initialise a committable git repo at *root*."""
    run_git("init", "-q", ".", cwd=root)
    run_git("config", "user.email", email, cwd=root)
    run_git("config", "user.name", user, cwd=root)


def commit_all(root: Path, message: str = "init") -> None:
    """Stage everything and commit it."""
    run_git("add", "-A", cwd=root)
    run_git("commit", "-qm", message, cwd=root)


def add_worktree(root: Path, path: Path, branch: str, cwd: Sequence[str] = ()) -> None:
    """Create a linked worktree at *path* on a new *branch*."""
    run_git("worktree", "add", "-q", str(path), "-b", branch, cwd=root)
