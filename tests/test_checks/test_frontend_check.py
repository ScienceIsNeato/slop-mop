"""Tests for frontend_check.py — quick ESLint frontend validation."""

import os
from unittest.mock import patch

from slopbucket.checks.frontend_check import FrontendCheck
from slopbucket.result import CheckStatus


class TestFrontendCheck:
    """Validates frontend check skip/pass/fail/error logic."""

    def setup_method(self) -> None:
        self.check = FrontendCheck()

    def test_name_and_description(self) -> None:
        assert self.check.name == "frontend-check"
        assert (
            "ESLint" in self.check.description
            or "frontend" in self.check.description.lower()
        )

    def test_skips_when_no_package_json(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.SKIPPED
            assert "package.json" in result.output

    def test_skips_when_no_js_source_dirs(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            # Create package.json but no JS source dirs
            with open(os.path.join(td, "package.json"), "w") as f:
                f.write('{"name": "test"}\n')
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.SKIPPED
            assert "JavaScript" in result.output

    @patch("slopbucket.checks.frontend_check.run")
    def test_passes_when_eslint_clean(self, mock_run: object) -> None:
        import tempfile

        from slopbucket.subprocess_guard import SubprocessResult

        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "package.json"), "w") as f:
                f.write('{"name": "test"}\n')
            static_dir = os.path.join(td, "static")
            os.makedirs(static_dir)
            with open(os.path.join(static_dir, "app.js"), "w") as f:
                f.write("console.log('hello');\n")
            mock_run.return_value = SubprocessResult(  # type: ignore[attr-defined]
                returncode=0,
                stdout="",
                stderr="",
                cmd=[],
            )
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.PASSED

    @patch("slopbucket.checks.frontend_check.run")
    def test_fails_when_eslint_errors(self, mock_run: object) -> None:
        import tempfile

        from slopbucket.subprocess_guard import SubprocessResult

        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "package.json"), "w") as f:
                f.write('{"name": "test"}\n')
            static_dir = os.path.join(td, "static")
            os.makedirs(static_dir)
            with open(os.path.join(static_dir, "app.js"), "w") as f:
                f.write("console.log('hello');\n")
            mock_run.return_value = SubprocessResult(  # type: ignore[attr-defined]
                returncode=1,
                stdout="static/app.js:1:1  error  'x' is not defined  no-undef\n",
                stderr="",
                cmd=[],
            )
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.FAILED

    @patch("slopbucket.checks.frontend_check.run")
    def test_error_on_eslint_config_failure(self, mock_run: object) -> None:
        import tempfile

        from slopbucket.subprocess_guard import SubprocessResult

        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "package.json"), "w") as f:
                f.write('{"name": "test"}\n')
            static_dir = os.path.join(td, "static")
            os.makedirs(static_dir)
            with open(os.path.join(static_dir, "app.js"), "w") as f:
                f.write("console.log('hello');\n")
            mock_run.return_value = SubprocessResult(  # type: ignore[attr-defined]
                returncode=2,
                stdout="",
                stderr="Error: Cannot find module '.eslintrc'\n",
                cmd=[],
            )
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.ERROR
