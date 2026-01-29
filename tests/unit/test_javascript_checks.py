"""Tests for JavaScript quality checks."""

from unittest.mock import MagicMock, patch

from slopmop.checks.javascript.coverage import JavaScriptCoverageCheck
from slopmop.checks.javascript.eslint_quick import FrontendCheck
from slopmop.checks.javascript.lint_format import JavaScriptLintFormatCheck
from slopmop.checks.javascript.tests import JavaScriptTestsCheck
from slopmop.core.result import CheckStatus


class TestJavaScriptTestsCheck:
    """Tests for JavaScriptTestsCheck."""

    def test_name(self):
        """Test check name."""
        check = JavaScriptTestsCheck({})
        assert check.name == "tests"

    def test_full_name(self):
        """Test full check name with category."""
        check = JavaScriptTestsCheck({})
        assert check.full_name == "javascript:tests"

    def test_display_name(self):
        """Test display name."""
        check = JavaScriptTestsCheck({})
        assert "Tests" in check.display_name
        assert "Jest" in check.display_name

    def test_depends_on(self):
        """Test dependencies."""
        check = JavaScriptTestsCheck({})
        assert "javascript:lint-format" in check.depends_on

    def test_config_schema(self):
        """Test config schema includes expected fields."""
        check = JavaScriptTestsCheck({})
        schema = check.config_schema
        field_names = [f.name for f in schema]
        assert "test_command" in field_names

    def test_is_applicable_with_package_json(self, tmp_path):
        """Test is_applicable returns True for JS projects."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        check = JavaScriptTestsCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_no_js(self, tmp_path):
        """Test is_applicable returns False for non-JS projects."""
        (tmp_path / "app.py").write_text("print('hello')")
        check = JavaScriptTestsCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_run_with_node_modules(self, tmp_path):
        """Test run() when node_modules exists."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptTestsCheck({})

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.timed_out = False
        mock_result.output = "Tests passed"

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_without_node_modules_installs(self, tmp_path):
        """Test run() installs deps when node_modules missing."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        check = JavaScriptTestsCheck({})

        npm_install_result = MagicMock()
        npm_install_result.success = True

        jest_result = MagicMock()
        jest_result.success = True
        jest_result.timed_out = False
        jest_result.output = "Tests passed"

        with patch.object(
            check, "_run_command", side_effect=[npm_install_result, jest_result]
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_npm_install_fails(self, tmp_path):
        """Test run() when npm install fails."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        check = JavaScriptTestsCheck({})

        npm_install_result = MagicMock()
        npm_install_result.success = False
        npm_install_result.output = "npm ERR! install failed"

        with patch.object(check, "_run_command", return_value=npm_install_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.ERROR
        assert "npm install failed" in result.error

    def test_run_tests_timeout(self, tmp_path):
        """Test run() when tests timeout."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptTestsCheck({})

        mock_result = MagicMock()
        mock_result.timed_out = True
        mock_result.output = ""

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED


class TestJavaScriptLintFormatCheck:
    """Tests for JavaScriptLintFormatCheck."""

    def test_name(self):
        """Test check name."""
        check = JavaScriptLintFormatCheck({})
        assert check.name == "lint-format"

    def test_full_name(self):
        """Test full check name with category."""
        check = JavaScriptLintFormatCheck({})
        assert check.full_name == "javascript:lint-format"

    def test_display_name(self):
        """Test display name."""
        check = JavaScriptLintFormatCheck({})
        assert "Lint" in check.display_name

    def test_is_applicable_with_package_json(self, tmp_path):
        """Test is_applicable returns True for JS projects."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        check = JavaScriptLintFormatCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_no_js(self, tmp_path):
        """Test is_applicable returns False for non-JS projects."""
        (tmp_path / "app.py").write_text("print('hello')")
        check = JavaScriptLintFormatCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_can_auto_fix(self):
        """Test can_auto_fix returns True."""
        check = JavaScriptLintFormatCheck({})
        assert check.can_auto_fix() is True

    def test_auto_fix_with_node_modules(self, tmp_path):
        """Test auto_fix() runs eslint and prettier."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptLintFormatCheck({})

        mock_result = MagicMock()
        mock_result.success = True

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.auto_fix(str(tmp_path))

        assert result is True

    def test_auto_fix_installs_deps(self, tmp_path):
        """Test auto_fix() installs deps when node_modules missing."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        check = JavaScriptLintFormatCheck({})

        mock_result = MagicMock()
        mock_result.success = True

        with patch.object(check, "_run_command", return_value=mock_result) as mock_run:
            result = check.auto_fix(str(tmp_path))

        # Should call npm install, eslint --fix, prettier --write
        assert mock_run.call_count == 3
        assert result is True

    def test_auto_fix_eslint_fails_prettier_succeeds(self, tmp_path):
        """Test auto_fix() returns True if prettier succeeds even if eslint fails."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptLintFormatCheck({})

        eslint_result = MagicMock()
        eslint_result.success = False
        prettier_result = MagicMock()
        prettier_result.success = True

        with patch.object(
            check, "_run_command", side_effect=[eslint_result, prettier_result]
        ):
            result = check.auto_fix(str(tmp_path))

        assert result is True

    def test_run_without_node_modules_installs(self, tmp_path):
        """Test run() installs deps when node_modules missing."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        check = JavaScriptLintFormatCheck({})

        npm_result = MagicMock()
        npm_result.success = True

        lint_result = MagicMock()
        lint_result.success = True
        lint_result.output = ""

        with patch.object(
            check, "_run_command", side_effect=[npm_result, lint_result, lint_result]
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_npm_install_fails(self, tmp_path):
        """Test run() when npm install fails."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        check = JavaScriptLintFormatCheck({})

        npm_result = MagicMock()
        npm_result.success = False
        npm_result.output = "npm ERR! install failed"

        with patch.object(check, "_run_command", return_value=npm_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.ERROR
        assert "npm install failed" in result.error

    def test_run_lint_passes(self, tmp_path):
        """Test run() when lint passes."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptLintFormatCheck({})

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "No errors"

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_lint_fails(self, tmp_path):
        """Test run() when lint fails."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptLintFormatCheck({})

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.output = "5 errors found"

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED


class TestJavaScriptCoverageCheck:
    """Tests for JavaScriptCoverageCheck."""

    def test_name(self):
        """Test check name."""
        check = JavaScriptCoverageCheck({})
        assert check.name == "coverage"

    def test_full_name(self):
        """Test full check name with category."""
        check = JavaScriptCoverageCheck({})
        assert check.full_name == "javascript:coverage"

    def test_display_name(self):
        """Test display name."""
        check = JavaScriptCoverageCheck({})
        assert "Coverage" in check.display_name

    def test_depends_on(self):
        """Test dependencies."""
        check = JavaScriptCoverageCheck({})
        assert "javascript:tests" in check.depends_on

    def test_config_schema(self):
        """Test config schema includes expected fields."""
        check = JavaScriptCoverageCheck({})
        schema = check.config_schema
        field_names = [f.name for f in schema]
        assert "threshold" in field_names

    def test_is_applicable_with_package_json(self, tmp_path):
        """Test is_applicable returns True for JS projects."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        check = JavaScriptCoverageCheck({})
        assert check.is_applicable(str(tmp_path)) is True


class TestFrontendCheck:
    """Tests for FrontendCheck."""

    def test_name(self):
        """Test check name."""
        check = FrontendCheck({})
        assert check.name == "frontend"

    def test_full_name(self):
        """Test full check name with category."""
        check = FrontendCheck({})
        assert check.full_name == "javascript:frontend"

    def test_display_name(self):
        """Test display name."""
        check = FrontendCheck({})
        assert "Frontend" in check.display_name

    def test_is_applicable_with_frontend_dirs(self, tmp_path):
        """Test is_applicable returns True when frontend_dirs exist."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "static").mkdir()
        check = FrontendCheck({"frontend_dirs": ["static"]})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_no_frontend_dirs(self, tmp_path):
        """Test is_applicable returns False when no frontend_dirs configured."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        check = FrontendCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_is_applicable_no_js(self, tmp_path):
        """Test is_applicable returns False for non-JS projects."""
        (tmp_path / "app.py").write_text("print('hello')")
        check = FrontendCheck({"frontend_dirs": ["static"]})
        assert check.is_applicable(str(tmp_path)) is False

    def test_run_build_passes(self, tmp_path):
        """Test run() when build passes."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "static").mkdir()
        check = FrontendCheck({"frontend_dirs": ["static"]})

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "Build complete"

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_build_fails(self, tmp_path):
        """Test run() when build fails."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "static").mkdir()
        check = FrontendCheck({"frontend_dirs": ["static"]})

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.output = "Build failed: compilation errors"

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
