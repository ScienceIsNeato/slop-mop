"""Functional tests for drain_formatting_before_commit using real git + formatters.

These tests create real git repos in tmp_path and invoke black/isort via the
actual PythonLintFormatCheck.auto_fix path — no mocks.  They prove drain fires
and produces correctly separated commits in an environment that mirrors what the
iterate pipeline sees at runtime.

No Docker required.  These tests are self-contained and run in the normal test
suite.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from slopmop.cli._refit_formatting import drain_formatting_before_commit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BADLY_FORMATTED = """\
def foo(x,y):
 return x+y
"""

_ALREADY_FORMATTED = """\
def bar(x: int, y: int) -> int:
    return x + y
"""

_COMMIT_MARKER = "[slop-mop refit]"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return result


def _git_checked(cwd: Path, *args: str, label: str) -> str:
    result = _git(cwd, *args)
    assert (
        result.returncode == 0
    ), f"{label} failed ({result.returncode}): {result.stderr or result.stdout}"
    return result.stdout.strip()


def _init_repo(tmp_path: Path) -> None:
    """Initialise a minimal git repo suitable for drain testing."""
    _git_checked(tmp_path, "init", label="git init")
    _git_checked(
        tmp_path, "config", "user.email", "drain@test.local", label="git config email"
    )
    _git_checked(tmp_path, "config", "user.name", "Drain Test", label="git config name")
    # Suppress detached-HEAD advice and divergence noise
    _git_checked(
        tmp_path, "config", "advice.detachedHead", "false", label="git config advice"
    )


def _commit_all(cwd: Path, message: str) -> str:
    _git_checked(cwd, "add", "-A", label="git add")
    _git_checked(cwd, "commit", "-m", message, label="git commit")
    return _git_checked(cwd, "rev-parse", "HEAD", label="git rev-parse")


def _log_subjects(cwd: Path, base_sha: str) -> list[str]:
    raw = _git_checked(cwd, "log", "--format=%s", f"{base_sha}..HEAD", label="git log")
    return raw.splitlines() if raw else []


def _default_args(**kw: object) -> argparse.Namespace:
    ns = argparse.Namespace(json_output=False)
    ns.__dict__.update(kw)
    return ns


def _is_python_project_present() -> bool:
    """Guard: skip if black/isort are not importable (stripped CI image)."""
    try:
        import black  # noqa: F401
        import isort  # noqa: F401

        return True
    except ImportError:
        return False


_needs_formatters = pytest.mark.skipif(
    not _is_python_project_present(),
    reason="black/isort not available in this environment",
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDrainFormattingFunctional:
    """Functional tests: drain_formatting_before_commit with real git + formatters."""

    @_needs_formatters
    def test_drain_fires_and_produces_style_commit(self, tmp_path: Path) -> None:
        """Drain should commit formatter-only files separately from the gate fix."""
        _init_repo(tmp_path)

        # pyproject.toml triggers is_applicable but is NOT a Python file so
        # black never reformats it — avoids spurious entries in formatting_only_paths
        (tmp_path / "pyproject.toml").write_text(
            '[build-system]\nrequires = ["setuptools"]\n'
        )
        # Gate-fix file — already formatted, will be the "agent's change"
        (tmp_path / "gate_fix.py").write_text(_ALREADY_FORMATTED)
        # Formatter target — badly formatted, NOT part of the gate fix
        (tmp_path / "unrelated.py").write_text(_BADLY_FORMATTED)

        base_sha = _commit_all(tmp_path, "initial")

        # Simulate the agent making a change to gate_fix.py (add a line)
        (tmp_path / "gate_fix.py").write_text(_ALREADY_FORMATTED + "\nx = 1\n")

        # gate_fix_status = what _worktree_status captured before calling drain:
        # gate_fix.py is modified but not yet staged
        gate_fix_status = [" M gate_fix.py"]

        result = drain_formatting_before_commit(
            _default_args(), tmp_path, "python:lint", gate_fix_status
        )

        assert result is True

        subjects = _log_subjects(tmp_path, base_sha)
        # There should be exactly one style commit from drain
        style_subjects = [s for s in subjects if _COMMIT_MARKER in s]
        assert style_subjects, f"Expected a style commit from drain but got: {subjects}"

        # The drain commit should contain unrelated.py but NOT gate_fix.py
        drain_commit_sha = _git_checked(
            tmp_path,
            "log",
            "--format=%H",
            "-F",
            "--grep",
            _COMMIT_MARKER,
            label="find drain commit sha",
        ).splitlines()[0]
        committed_files = _git_checked(
            tmp_path,
            "show",
            "--name-only",
            "--format=",
            drain_commit_sha,
            label="show drain commit files",
        ).splitlines()
        assert (
            "unrelated.py" in committed_files
        ), f"Expected unrelated.py in drain commit, got: {committed_files}"
        assert (
            "gate_fix.py" not in committed_files
        ), f"Drain commit should not contain gate_fix.py (it is the gate fix)"

        # gate_fix.py should still have modifications (committed separately later)
        fix_status = _git(
            tmp_path, "status", "--porcelain", "gate_fix.py"
        ).stdout.strip()
        assert fix_status, f"gate_fix.py should still have modifications after drain"

    @_needs_formatters
    def test_drain_no_op_when_all_dirty_files_are_gate_fix(
        self, tmp_path: Path
    ) -> None:
        """No style commit when formatters only touch gate-fix files."""
        _init_repo(tmp_path)

        (tmp_path / "pyproject.toml").write_text(
            '[build-system]\nrequires = ["setuptools"]\n'
        )
        # This file will be the gate fix AND will attract formatter attention
        (tmp_path / "only_file.py").write_text(_BADLY_FORMATTED)

        base_sha = _commit_all(tmp_path, "initial")

        # The agent "fixed" only_file.py — it's the gate fix file
        # (black will also reformat it, but it's in gate_fix_status so drain skips it)
        gate_fix_status = [" M only_file.py"]

        result = drain_formatting_before_commit(
            _default_args(), tmp_path, "python:lint", gate_fix_status
        )

        assert result is True

        subjects = _log_subjects(tmp_path, base_sha)
        style_subjects = [s for s in subjects if _COMMIT_MARKER in s]
        assert not style_subjects, (
            f"Expected no drain commit when all dirty files are in the gate fix,"
            f" but got: {subjects}"
        )

    @_needs_formatters
    def test_drain_separates_multiple_formatter_only_files(
        self, tmp_path: Path
    ) -> None:
        """Drain commits all formatter-only files in a single style commit."""
        _init_repo(tmp_path)

        (tmp_path / "pyproject.toml").write_text(
            '[build-system]\nrequires = ["setuptools"]\n'
        )
        (tmp_path / "gate_fix.py").write_text(_ALREADY_FORMATTED)
        # Three additional files that need formatting (none part of the gate fix)
        for name in ("a.py", "b.py", "c.py"):
            (tmp_path / name).write_text(_BADLY_FORMATTED)

        base_sha = _commit_all(tmp_path, "initial")

        # Simulate gate fix modifying one file
        (tmp_path / "gate_fix.py").write_text(_ALREADY_FORMATTED + "\nVALUE = 42\n")
        gate_fix_status = [" M gate_fix.py"]

        result = drain_formatting_before_commit(
            _default_args(), tmp_path, "python:lint", gate_fix_status
        )

        assert result is True

        subjects = _log_subjects(tmp_path, base_sha)
        style_subjects = [s for s in subjects if _COMMIT_MARKER in s]
        # One batch style commit for all three formatter-only files
        assert (
            len(style_subjects) == 1
        ), f"Expected exactly one style commit, got: {subjects}"

    @_needs_formatters
    def test_drain_no_op_when_all_files_already_formatted(self, tmp_path: Path) -> None:
        """No style commit when there is nothing for the formatter to change."""
        _init_repo(tmp_path)

        (tmp_path / "pyproject.toml").write_text(
            '[build-system]\nrequires = ["setuptools"]\n'
        )
        # All files are already well-formatted
        (tmp_path / "gate_fix.py").write_text(_ALREADY_FORMATTED)
        (tmp_path / "bystander.py").write_text(_ALREADY_FORMATTED)

        base_sha = _commit_all(tmp_path, "initial")

        (tmp_path / "gate_fix.py").write_text(_ALREADY_FORMATTED + "\nVALUE = 1\n")
        gate_fix_status = [" M gate_fix.py"]

        result = drain_formatting_before_commit(
            _default_args(), tmp_path, "python:lint", gate_fix_status
        )

        assert result is True

        subjects = _log_subjects(tmp_path, base_sha)
        style_subjects = [s for s in subjects if _COMMIT_MARKER in s]
        assert not style_subjects, (
            f"Expected no drain commit when nothing needs reformatting,"
            f" but got: {subjects}"
        )
