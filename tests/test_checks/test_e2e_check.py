"""Tests for e2e_check.py — Playwright E2E tests."""

import os
from unittest.mock import patch

from slopbucket.checks.e2e_check import E2ECheck
from slopbucket.result import CheckStatus


class TestE2ECheck:
    """Validates E2E check skip/pass/fail/error logic."""

    def setup_method(self) -> None:
        self.check = E2ECheck()

    def test_name_and_description(self) -> None:
        assert self.check.name == "e2e"
        assert (
            "Playwright" in self.check.description
            or "browser" in self.check.description.lower()
        )

    def test_skips_when_no_e2e_dir(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.SKIPPED
            assert "tests/e2e" in result.output

    @patch.dict(os.environ, {}, clear=True)
    def test_skips_when_no_port_configured(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            e2e_dir = os.path.join(td, "tests", "e2e")
            os.makedirs(e2e_dir)
            with open(os.path.join(e2e_dir, "test_basic.py"), "w") as f:
                f.write("def test_placeholder(): pass\n")
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.SKIPPED
            assert "port" in result.output.lower()

    @patch.dict(os.environ, {"LOOPCLOSER_DEFAULT_PORT_E2E": "3002"})
    @patch("slopbucket.checks.e2e_check.run")
    def test_error_when_playwright_missing(self, mock_run: object) -> None:
        import tempfile

        from slopbucket.subprocess_guard import SubprocessResult

        with tempfile.TemporaryDirectory() as td:
            e2e_dir = os.path.join(td, "tests", "e2e")
            os.makedirs(e2e_dir)
            with open(os.path.join(e2e_dir, "test_basic.py"), "w") as f:
                f.write("def test_placeholder(): pass\n")
            # First call is the playwright probe, which fails
            mock_run.return_value = SubprocessResult(  # type: ignore[attr-defined]
                returncode=1,
                stdout="",
                stderr="ModuleNotFoundError\n",
                cmd=[],
            )
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.ERROR
            assert "Playwright" in result.output

    @patch.dict(os.environ, {"LOOPCLOSER_DEFAULT_PORT_E2E": "3002"})
    @patch("slopbucket.checks.e2e_check.run")
    def test_passes_when_tests_succeed(self, mock_run: object) -> None:
        import tempfile

        from slopbucket.subprocess_guard import SubprocessResult

        with tempfile.TemporaryDirectory() as td:
            e2e_dir = os.path.join(td, "tests", "e2e")
            os.makedirs(e2e_dir)
            with open(os.path.join(e2e_dir, "test_basic.py"), "w") as f:
                f.write("def test_placeholder(): pass\n")
            # First call: playwright probe succeeds; second call: tests pass
            mock_run.side_effect = [  # type: ignore[attr-defined]
                SubprocessResult(returncode=0, stdout="", stderr="", cmd=[]),
                SubprocessResult(
                    returncode=0,
                    stdout="2 passed\n",
                    stderr="",
                    cmd=[],
                ),
            ]
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.PASSED

    @patch.dict(os.environ, {"LOOPCLOSER_DEFAULT_PORT_E2E": "3002"})
    @patch("slopbucket.checks.e2e_check.run")
    def test_fails_when_tests_fail(self, mock_run: object) -> None:
        import tempfile

        from slopbucket.subprocess_guard import SubprocessResult

        with tempfile.TemporaryDirectory() as td:
            e2e_dir = os.path.join(td, "tests", "e2e")
            os.makedirs(e2e_dir)
            with open(os.path.join(e2e_dir, "test_basic.py"), "w") as f:
                f.write("def test_placeholder(): pass\n")
            mock_run.side_effect = [  # type: ignore[attr-defined]
                SubprocessResult(returncode=0, stdout="", stderr="", cmd=[]),
                SubprocessResult(
                    returncode=1,
                    stdout="FAILED test_login.py::test_flow\n",
                    stderr="",
                    cmd=[],
                ),
            ]
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.FAILED
