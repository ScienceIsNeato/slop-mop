"""Tests for JS check modules — format, tests, coverage."""

import os
from unittest.mock import patch

from slopbucket.checks.js_coverage import JSCoverageCheck
from slopbucket.checks.js_format import JSFormatCheck
from slopbucket.checks.js_tests import JSTestsCheck
from slopbucket.result import CheckStatus
from slopbucket.subprocess_guard import SubprocessResult


def _ok(stdout: str = "", stderr: str = "") -> SubprocessResult:
    return SubprocessResult(0, stdout, stderr, cmd=[])


def _fail(stdout: str = "", stderr: str = "") -> SubprocessResult:
    return SubprocessResult(1, stdout, stderr, cmd=[])


class TestJSFormatCheck:
    """Validates JS formatting check."""

    def setup_method(self) -> None:
        self.check = JSFormatCheck()

    def test_name_and_description(self) -> None:
        assert self.check.name == "js-format"
        assert (
            "ESLint" in self.check.description or "Prettier" in self.check.description
        )

    def test_skips_without_js_source(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.SKIPPED

    @patch("slopbucket.checks.js_format.run")
    def test_passes_with_clean_code(self, mock_run: object) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            # Create static/ with a .js file so _has_js_source returns True
            static_dir = os.path.join(td, "static")
            os.makedirs(static_dir)
            with open(os.path.join(static_dir, "app.js"), "w") as f:
                f.write("console.log('hi');")
            mock_run.return_value = _ok()  # type: ignore[attr-defined]
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.PASSED

    @patch("slopbucket.checks.js_format.run")
    def test_fails_with_lint_errors(self, mock_run: object) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            static_dir = os.path.join(td, "static")
            os.makedirs(static_dir)
            with open(os.path.join(static_dir, "app.js"), "w") as f:
                f.write("var x = 1;")
            mock_run.return_value = _fail(stdout="2 errors found")  # type: ignore[attr-defined]
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.FAILED


class TestJSTestsCheck:
    """Validates JS test runner check."""

    def setup_method(self) -> None:
        self.check = JSTestsCheck()

    def test_name_and_description(self) -> None:
        assert self.check.name == "js-tests"
        assert "Jest" in self.check.description

    def test_skips_without_package_json(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.SKIPPED

    @patch("slopbucket.checks.js_tests.run")
    def test_passes_with_passing_tests(self, mock_run: object) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "package.json"), "w") as f:
                f.write('{"scripts": {"test": "jest"}}')
            mock_run.return_value = _ok(stdout="Test Suites: 5 passed")  # type: ignore[attr-defined]
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.PASSED

    @patch("slopbucket.checks.js_tests.run")
    def test_fails_with_test_failures(self, mock_run: object) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "package.json"), "w") as f:
                f.write('{"scripts": {"test": "jest"}}')
            mock_run.return_value = _fail(stdout="Test Suites: 1 failed")  # type: ignore[attr-defined]
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.FAILED


class TestJSCoverageCheck:
    """Validates JS coverage threshold check."""

    def setup_method(self) -> None:
        self.check = JSCoverageCheck()

    def test_name_and_description(self) -> None:
        assert self.check.name == "js-coverage"
        assert "80" in self.check.description

    def test_skips_without_package_json(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.SKIPPED

    @patch("slopbucket.checks.js_coverage.run")
    def test_passes_with_sufficient_coverage(self, mock_run: object) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "package.json"), "w") as f:
                f.write('{"scripts": {"test:coverage": "jest --coverage"}}')
            mock_run.return_value = _ok(stdout="Coverage: 85%")  # type: ignore[attr-defined]
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.PASSED

    @patch("slopbucket.checks.js_coverage.run")
    def test_fails_below_threshold(self, mock_run: object) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "package.json"), "w") as f:
                f.write('{"scripts": {"test:coverage": "jest --coverage"}}')
            mock_run.return_value = _fail(stdout="Coverage: 60%")  # type: ignore[attr-defined]
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.FAILED
