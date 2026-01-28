"""Tests for python_tests.py — Pytest runner + coverage gen."""

import os
from unittest.mock import patch

from slopbucket.checks.python_tests import PythonTestsCheck, _find_source_packages
from slopbucket.result import CheckStatus
from slopbucket.subprocess_guard import SubprocessResult


def _ok(stdout: str = "", stderr: str = "") -> SubprocessResult:
    return SubprocessResult(0, stdout, stderr, cmd=[])


def _fail(stdout: str = "", stderr: str = "") -> SubprocessResult:
    return SubprocessResult(1, stdout, stderr, cmd=[])


class TestFindSourcePackages:
    """Unit tests for auto-discovery helper."""

    def test_finds_src_directory(self, tmp_path: object) -> None:
        src = tmp_path / "src"  # type: ignore[operator]
        src.mkdir()
        result = _find_source_packages(str(tmp_path))
        assert result == ["src"]

    def test_finds_top_level_packages(self, tmp_path: object) -> None:
        pkg = tmp_path / "mylib"  # type: ignore[operator]
        pkg.mkdir()
        (pkg / "__init__.py").touch()
        result = _find_source_packages(str(tmp_path))
        assert "mylib" in result

    def test_excludes_tests_and_venv(self, tmp_path: object) -> None:
        for name in ["tests", "venv", ".venv"]:
            d = tmp_path / name  # type: ignore[operator]
            d.mkdir()
            (d / "__init__.py").touch()
        result = _find_source_packages(str(tmp_path))
        assert result == []

    def test_src_takes_priority(self, tmp_path: object) -> None:
        """If src/ exists, only src is returned even if other packages exist."""
        src = tmp_path / "src"  # type: ignore[operator]
        src.mkdir()
        pkg = tmp_path / "mylib"  # type: ignore[operator]
        pkg.mkdir()
        (pkg / "__init__.py").touch()
        result = _find_source_packages(str(tmp_path))
        assert result == ["src"]


class TestPythonTestsCheck:
    """Validates test runner check pass/fail/skip logic."""

    def setup_method(self) -> None:
        self.check = PythonTestsCheck()

    def test_name_and_description(self) -> None:
        assert self.check.name == "python-tests"
        assert "Pytest" in self.check.description

    @patch("slopbucket.checks.python_tests.run")
    def test_skips_when_no_test_dirs(self, mock_run: object) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.SKIPPED

    @patch("slopbucket.checks.python_tests.run")
    def test_passes_with_successful_tests(self, mock_run: object) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "tests"))
            mock_run.return_value = _ok(stdout="5 passed in 1.2s")  # type: ignore[attr-defined]
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.PASSED

    @patch("slopbucket.checks.python_tests.run")
    def test_fails_with_test_failures(self, mock_run: object) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "tests"))
            mock_run.return_value = _fail(stdout="1 failed, 4 passed")  # type: ignore[attr-defined]
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.FAILED
