"""Tests for integration_check.py — database integration tests."""

import os
from unittest.mock import patch

from slopbucket.checks.integration_check import IntegrationCheck
from slopbucket.result import CheckStatus


class TestIntegrationCheck:
    """Validates integration check skip/pass/fail/error logic."""

    def setup_method(self) -> None:
        self.check = IntegrationCheck()

    def test_name_and_description(self) -> None:
        assert self.check.name == "integration"
        assert "integration" in self.check.description.lower()

    def test_skips_when_no_integration_dir(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.SKIPPED
            assert "tests/integration" in result.output

    @patch.dict(os.environ, {}, clear=True)
    def test_skips_when_no_database_url(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            int_dir = os.path.join(td, "tests", "integration")
            os.makedirs(int_dir)
            with open(os.path.join(int_dir, "test_basic.py"), "w") as f:
                f.write("def test_placeholder(): pass\n")
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.SKIPPED
            assert "DATABASE_URL" in result.output

    @patch.dict(os.environ, {"DATABASE_URL": "sqlite:///test.db"})
    @patch("slopbucket.checks.integration_check.run")
    def test_passes_when_tests_succeed(self, mock_run: object) -> None:
        import tempfile

        from slopbucket.subprocess_guard import SubprocessResult

        with tempfile.TemporaryDirectory() as td:
            int_dir = os.path.join(td, "tests", "integration")
            os.makedirs(int_dir)
            with open(os.path.join(int_dir, "test_basic.py"), "w") as f:
                f.write("def test_placeholder(): pass\n")
            mock_run.return_value = SubprocessResult(  # type: ignore[attr-defined]
                returncode=0,
                stdout="3 passed\n",
                stderr="",
                cmd=[],
            )
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.PASSED

    @patch.dict(os.environ, {"DATABASE_URL": "sqlite:///test.db"})
    @patch("slopbucket.checks.integration_check.run")
    def test_fails_when_tests_fail(self, mock_run: object) -> None:
        import tempfile

        from slopbucket.subprocess_guard import SubprocessResult

        with tempfile.TemporaryDirectory() as td:
            int_dir = os.path.join(td, "tests", "integration")
            os.makedirs(int_dir)
            with open(os.path.join(int_dir, "test_basic.py"), "w") as f:
                f.write("def test_placeholder(): pass\n")
            mock_run.return_value = SubprocessResult(  # type: ignore[attr-defined]
                returncode=1,
                stdout="FAILED test_db.py::test_insert\n",
                stderr="",
                cmd=[],
            )
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.FAILED

    @patch.dict(os.environ, {"DATABASE_URL": "sqlite:///test.db"})
    @patch("slopbucket.checks.integration_check.run")
    def test_error_on_collection_failure(self, mock_run: object) -> None:
        import tempfile

        from slopbucket.subprocess_guard import SubprocessResult

        with tempfile.TemporaryDirectory() as td:
            int_dir = os.path.join(td, "tests", "integration")
            os.makedirs(int_dir)
            with open(os.path.join(int_dir, "test_basic.py"), "w") as f:
                f.write("def test_placeholder(): pass\n")
            mock_run.return_value = SubprocessResult(  # type: ignore[attr-defined]
                returncode=2,
                stdout="",
                stderr="SyntaxError in conftest\n",
                cmd=[],
            )
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.ERROR
