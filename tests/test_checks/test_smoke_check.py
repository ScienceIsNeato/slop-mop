"""Tests for smoke_check.py — Selenium smoke tests against live server."""

import os
from unittest.mock import patch

from slopbucket.checks.smoke_check import SmokeCheck
from slopbucket.result import CheckStatus


class TestSmokeCheck:
    """Validates smoke check skip/pass/fail/error logic."""

    def setup_method(self) -> None:
        self.check = SmokeCheck()

    def test_name_and_description(self) -> None:
        assert self.check.name == "smoke"
        assert (
            "Selenium" in self.check.description or "server" in self.check.description
        )

    def test_skips_when_no_smoke_dir(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.SKIPPED
            assert "tests/smoke" in result.output

    @patch.dict(os.environ, {}, clear=True)
    def test_skips_when_no_port_configured(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            smoke_dir = os.path.join(td, "tests", "smoke")
            os.makedirs(smoke_dir)
            # Create a minimal test file so pytest would find it
            with open(os.path.join(smoke_dir, "test_basic.py"), "w") as f:
                f.write("def test_placeholder(): pass\n")
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.SKIPPED
            assert "port" in result.output.lower()

    @patch.dict(os.environ, {"TEST_PORT": "3001"})
    @patch("slopbucket.checks.smoke_check.run")
    def test_passes_when_tests_succeed(self, mock_run: object) -> None:
        import tempfile

        from slopbucket.subprocess_guard import SubprocessResult

        with tempfile.TemporaryDirectory() as td:
            smoke_dir = os.path.join(td, "tests", "smoke")
            os.makedirs(smoke_dir)
            with open(os.path.join(smoke_dir, "test_basic.py"), "w") as f:
                f.write("def test_placeholder(): pass\n")
            mock_run.return_value = SubprocessResult(  # type: ignore[attr-defined]
                returncode=0,
                stdout="1 passed\n",
                stderr="",
                cmd=[],
            )
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.PASSED

    @patch.dict(os.environ, {"TEST_PORT": "3001"})
    @patch("slopbucket.checks.smoke_check.run")
    def test_fails_when_tests_fail(self, mock_run: object) -> None:
        import tempfile

        from slopbucket.subprocess_guard import SubprocessResult

        with tempfile.TemporaryDirectory() as td:
            smoke_dir = os.path.join(td, "tests", "smoke")
            os.makedirs(smoke_dir)
            with open(os.path.join(smoke_dir, "test_basic.py"), "w") as f:
                f.write("def test_placeholder(): pass\n")
            mock_run.return_value = SubprocessResult(  # type: ignore[attr-defined]
                returncode=1,
                stdout="FAILED test_basic.py::test_placeholder\n",
                stderr="",
                cmd=[],
            )
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.FAILED
            assert (
                "smoke" in result.fix_hint.lower()
                or "server" in result.fix_hint.lower()
            )

    @patch.dict(os.environ, {"TEST_PORT": "3001"})
    @patch("slopbucket.checks.smoke_check.run")
    def test_error_on_collection_failure(self, mock_run: object) -> None:
        import tempfile

        from slopbucket.subprocess_guard import SubprocessResult

        with tempfile.TemporaryDirectory() as td:
            smoke_dir = os.path.join(td, "tests", "smoke")
            os.makedirs(smoke_dir)
            with open(os.path.join(smoke_dir, "test_basic.py"), "w") as f:
                f.write("def test_placeholder(): pass\n")
            mock_run.return_value = SubprocessResult(  # type: ignore[attr-defined]
                returncode=2,
                stdout="",
                stderr="ImportError: No module named 'selenium'\n",
                cmd=[],
            )
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.ERROR
            assert "selenium" in result.output.lower()
