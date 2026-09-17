"""A gate must never see a file the repository ignores.

The previous implementation translated the root ``.gitignore`` into exclude
patterns by hand. That caught directory entries and silently missed glob
patterns, nested ``.gitignore`` files, negations and ``.git/info/exclude`` —
so generated files under a scanned source directory were analysed and
reported. These tests pin the cases that were wrong.
"""

import subprocess
from pathlib import Path
from typing import Any, Set

import pytest

from slopmop.checks.base import count_source_scope, iter_project_files


def _git_in_fixture(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo whose ignores exercise every pattern class that was broken."""
    (tmp_path / "src").mkdir()
    (tmp_path / "vendor").mkdir()
    (tmp_path / "deep" / "inner").mkdir(parents=True)
    (tmp_path / ".github" / "workflows").mkdir(parents=True)

    (tmp_path / ".gitignore").write_text(
        "vendor/\n"  # directory entry — the only class that used to work
        "*.generated.py\n"  # glob
        "/anchored.py\n"  # root-anchored
    )
    (tmp_path / "deep" / "inner" / ".gitignore").write_text("nested.py\n")

    (tmp_path / "src" / "app.py").write_text("x = 1\n")
    (tmp_path / "src" / "thing.generated.py").write_text("y = 2\n")
    (tmp_path / "anchored.py").write_text("z = 3\n")
    (tmp_path / "vendor" / "lib.py").write_text("w = 4\n")
    (tmp_path / "deep" / "inner" / "nested.py").write_text("v = 5\n")
    (tmp_path / "deep" / "inner" / "kept.py").write_text("u = 6\n")
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: ci\n")

    _git_in_fixture("init", cwd=tmp_path)
    _git_in_fixture("config", "user.email", "t@t.t", cwd=tmp_path)
    _git_in_fixture("config", "user.name", "t", cwd=tmp_path)
    _git_in_fixture("add", "-A", cwd=tmp_path)
    _git_in_fixture("commit", "-m", "init", cwd=tmp_path)
    return tmp_path


def _names(root: Path, **kwargs: Any) -> Set[str]:
    return {
        p.relative_to(root).as_posix() for p in iter_project_files(str(root), **kwargs)
    }


class TestIgnoredFilesAreNeverReturned:
    def test_directory_entry(self, repo: Path) -> None:
        assert "vendor/lib.py" not in _names(repo)

    def test_glob_pattern(self, repo: Path) -> None:
        """The case that shipped broken: a glob inside a scanned source dir."""
        found = _names(repo)
        assert "src/thing.generated.py" not in found
        assert "src/app.py" in found

    def test_root_anchored_pattern(self, repo: Path) -> None:
        assert "anchored.py" not in _names(repo)

    def test_nested_gitignore(self, repo: Path) -> None:
        """Only the root .gitignore used to be read at all."""
        found = _names(repo)
        assert "deep/inner/nested.py" not in found
        assert "deep/inner/kept.py" in found

    def test_scope_counting_agrees(self, repo: Path) -> None:
        """Scope metrics must not count files the gate cannot scan."""
        scope = count_source_scope(str(repo), extensions={".py"})
        # Only src/app.py and deep/inner/kept.py survive the ignores.
        assert scope.files == 2


class TestTrackedFilesSurvive:
    def test_tracked_dot_directory_is_kept(self, repo: Path) -> None:
        """.github is a dot-dir but tracked — dropping it breaks CI scanning."""
        assert ".github/workflows/ci.yml" in _names(repo)

    def test_extension_filter_still_applies(self, repo: Path) -> None:
        assert _names(repo, extensions={".yml"}) == {".github/workflows/ci.yml"}

    def test_include_dirs_scope(self, repo: Path) -> None:
        assert _names(repo, extensions={".py"}, include_dirs=["src"]) == {"src/app.py"}

    def test_caller_exclude_dirs_still_apply(self, repo: Path) -> None:
        assert "deep/inner/kept.py" not in _names(repo, exclude_dirs={"deep"})


class TestNonGitFallback:
    def test_plain_directory_still_scanned(self, tmp_path: Path) -> None:
        """Not every project is a git repo; the walk fallback must still work."""
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "mod.py").write_text("a = 1\n")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "junk.py").write_text("b = 2\n")

        found = _names(tmp_path, extensions={".py"})
        assert "pkg/mod.py" in found
        # The fallback prunes known-noise trees as it descends.
        assert "node_modules/junk.py" not in found
