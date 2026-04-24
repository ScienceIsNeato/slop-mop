"""Regression coverage for scripts/release.sh."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_RELEASE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "release.sh"
_HAS_BASH = shutil.which("bash") is not None
_HAS_GIT = shutil.which("git") is not None


def _run_release_command(
    cwd: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _checked(
    cwd: Path,
    *args: str,
    label: str,
    env: dict[str, str] | None = None,
) -> str:
    result = _run_release_command(cwd, *args, env=env)
    assert (
        result.returncode == 0
    ), f"{label} failed ({result.returncode}): {result.stderr or result.stdout}"
    return result.stdout.strip()


def _write_pyproject(path: Path, version: str) -> None:
    path.write_text(
        "[project]\n" 'name = "slopmop"\n' f'version = "{version}"\n',
        encoding="utf-8",
    )


def _init_release_repo(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"

    _checked(tmp_path, "git", "init", "--bare", str(origin), label="git init --bare")
    _checked(tmp_path, "git", "clone", str(origin), str(work), label="git clone")
    _checked(work, "git", "checkout", "-b", "main", label="git checkout -b main")
    _checked(
        work,
        "git",
        "config",
        "user.email",
        "release@test.local",
        label="git config email",
    )
    _checked(
        work,
        "git",
        "config",
        "user.name",
        "Release Test",
        label="git config name",
    )

    (work / "scripts").mkdir()
    shutil.copy2(_RELEASE_SCRIPT, work / "scripts" / "release.sh")
    _write_pyproject(work / "pyproject.toml", "0.14.1")

    _checked(
        work, "git", "add", "pyproject.toml", "scripts/release.sh", label="git add"
    )
    _checked(work, "git", "commit", "-m", "initial", label="git commit")
    _checked(work, "git", "push", "-u", "origin", "main", label="git push main")
    return work


def _create_remote_release_branch(work: Path, branch_name: str, version: str) -> str:
    _checked(work, "git", "checkout", "-b", branch_name, label="git checkout release")
    _write_pyproject(work / "pyproject.toml", version)
    _checked(work, "git", "add", "pyproject.toml", label="git add release")
    _checked(
        work,
        "git",
        "commit",
        "-m",
        f"chore: bump version to {version}",
        label="git commit release",
    )
    release_sha = _checked(
        work, "git", "rev-parse", "HEAD", label="git rev-parse release"
    )
    _checked(work, "git", "push", "-u", "origin", branch_name, label="git push release")
    _checked(work, "git", "checkout", "main", label="git checkout main")
    _checked(work, "git", "branch", "-D", branch_name, label="git branch -D")
    return release_sha


def _write_fake_gh(fake_bin: Path) -> None:
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        'printf \'%s\\n\' "$*" >> "$GH_LOG"\n'
        'if [ "${1:-}" = "pr" ] && [ "${2:-}" = "list" ]; then\n'
        '  if [ -n "${GH_EXISTING_PR_URL:-}" ]; then\n'
        "    printf '%s\\n' \"$GH_EXISTING_PR_URL\"\n"
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        'if [ "${1:-}" = "pr" ] && [ "${2:-}" = "create" ]; then\n'
        "  printf '%s\\n' 'https://example.test/pr/123'\n"
        "  exit 0\n"
        "fi\n"
        "printf 'unexpected gh args: %s\\n' \"$*\" >&2\n"
        "exit 1\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)


@pytest.mark.skipif(
    not (_HAS_BASH and _HAS_GIT),
    reason="bash and git are required for release.sh regression coverage",
)
def test_release_script_reuses_existing_remote_branch_on_rerun(tmp_path: Path) -> None:
    work = _init_release_repo(tmp_path)
    release_sha = _create_remote_release_branch(work, "release/v0.15.0", "0.15.0")

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    gh_log = tmp_path / "gh.log"
    _write_fake_gh(fake_bin)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["GH_LOG"] = str(gh_log)

    result = _run_release_command(work, "bash", "scripts/release.sh", "minor", env=env)

    assert result.returncode == 0, result.stderr or result.stdout
    assert "Remote branch release/v0.15.0 already exists. Reusing it" in result.stdout
    assert "https://example.test/pr/123" in result.stdout
    assert "Pushing release/v0.15.0" not in result.stdout

    current_branch = _checked(
        work, "git", "branch", "--show-current", label="git branch --show-current"
    )
    assert current_branch == "main"

    remote_head = _checked(
        work,
        "git",
        "ls-remote",
        "origin",
        "refs/heads/release/v0.15.0",
        label="git ls-remote release",
    ).split()[0]
    assert remote_head == release_sha

    gh_calls = gh_log.read_text(encoding="utf-8").splitlines()
    assert any(call.startswith("pr list ") for call in gh_calls)
    assert any(call.startswith("pr create ") for call in gh_calls)


@pytest.mark.skipif(
    not (_HAS_BASH and _HAS_GIT),
    reason="bash and git are required for release.sh regression coverage",
)
def test_release_script_reuses_existing_open_pr_without_creating_another(
    tmp_path: Path,
) -> None:
    work = _init_release_repo(tmp_path)
    release_sha = _create_remote_release_branch(work, "release/v0.15.0", "0.15.0")

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    gh_log = tmp_path / "gh.log"
    _write_fake_gh(fake_bin)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["GH_LOG"] = str(gh_log)
    env["GH_EXISTING_PR_URL"] = "https://example.test/pr/existing"

    result = _run_release_command(work, "bash", "scripts/release.sh", "minor", env=env)

    assert result.returncode == 0, result.stderr or result.stdout
    assert "https://example.test/pr/existing" in result.stdout
    assert "Reused existing open release PR" in result.stdout
    assert "Pushing release/v0.15.0" not in result.stdout

    current_branch = _checked(
        work, "git", "branch", "--show-current", label="git branch --show-current"
    )
    assert current_branch == "main"

    remote_head = _checked(
        work,
        "git",
        "ls-remote",
        "origin",
        "refs/heads/release/v0.15.0",
        label="git ls-remote release",
    ).split()[0]
    assert remote_head == release_sha

    gh_calls = gh_log.read_text(encoding="utf-8").splitlines()
    assert any(call.startswith("pr list ") for call in gh_calls)
    assert not any(call.startswith("pr create ") for call in gh_calls)
