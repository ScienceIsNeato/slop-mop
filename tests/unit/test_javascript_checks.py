"""Tests for JavaScript quality checks."""

import json
from unittest.mock import MagicMock, patch

from slopmop.checks.javascript.coverage import JavaScriptCoverageCheck
from slopmop.checks.javascript.eslint_quick import FrontendCheck
from slopmop.checks.javascript.lint_format import JavaScriptLintFormatCheck
from slopmop.checks.javascript.tests import JavaScriptTestsCheck
from slopmop.checks.javascript.types import JavaScriptTypesCheck
from slopmop.core.result import CheckStatus


class TestJavaScriptTestsCheck:
    """Tests for JavaScriptTestsCheck."""

    def test_name(self):
        """Test check name."""
        check = JavaScriptTestsCheck({})
        assert check.name == "untested-code.js"

    def test_full_name(self):
        """Test full check name with category."""
        check = JavaScriptTestsCheck({})
        assert check.full_name == "overconfidence:untested-code.js"

    def test_display_name(self):
        """Test display name."""
        check = JavaScriptTestsCheck({})
        assert "Tests" in check.display_name

    def test_depends_on(self):
        """Test dependencies."""
        check = JavaScriptTestsCheck({})
        assert "laziness:sloppy-formatting.js" in check.depends_on

    def test_config_schema(self):
        """Test config schema includes expected fields."""
        check = JavaScriptTestsCheck({})
        schema = check.config_schema
        field_names = [f.name for f in schema]
        assert "test_command" in field_names
        assert "exclude_dirs" in field_names

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
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "smoke.test.js").write_text("test('ok', () => {})")
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
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "smoke.test.js").write_text("test('ok', () => {})")
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
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "smoke.test.js").write_text("test('ok', () => {})")
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
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "smoke.test.js").write_text("test('ok', () => {})")
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptTestsCheck({})

        mock_result = MagicMock()
        mock_result.timed_out = True
        mock_result.output = ""

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED

    def test_run_fails_when_no_test_files(self, tmp_path):
        """Test run() fails when no JS/TS test files are present."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptTestsCheck({})

        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "No JavaScript/TypeScript tests found" in (result.error or "")

    def test_run_no_tests_found_from_jest_output(self, tmp_path):
        """When Jest reports no tests, surface the explicit no-tests message."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "smoke.test.js").write_text("test('ok', () => {})")
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptTestsCheck({})

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.timed_out = False
        mock_result.output = "No tests found, exiting with code 1"

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "No JavaScript/TypeScript tests found" in (result.error or "")

    def test_has_javascript_test_files_skips_excluded_dir_walk_entries(self, tmp_path):
        """Excluded directory entries from os.walk are ignored safely."""
        check = JavaScriptTestsCheck({})
        excluded_root = tmp_path / "node_modules"

        with patch(
            "slopmop.checks.mixins.os.walk",
            return_value=[(str(excluded_root), ["pkg"], ["foo.test.js"])],
        ):
            assert check.has_javascript_test_files(str(tmp_path)) is False

    def test_run_uses_configured_test_command(self, tmp_path):
        """run() should use the configured test_command instead of hardcoded jest."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "smoke.test.js").write_text("test('ok', () => {})")
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptTestsCheck({"test_command": "npm test"})

        commands_run = []

        def capture_command(cmd, **kwargs):
            commands_run.append(cmd)
            mock = MagicMock()
            mock.success = True
            mock.timed_out = False
            mock.output = "Tests passed"
            return mock

        with patch.object(check, "_run_command", side_effect=capture_command):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert commands_run[-1] == ["npm", "test"]

    def test_run_uses_default_jest_when_no_config(self, tmp_path):
        """run() falls back to npx jest when test_command is not configured."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "smoke.test.js").write_text("test('ok', () => {})")
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptTestsCheck({})

        commands_run = []

        def capture_command(cmd, **kwargs):
            commands_run.append(cmd)
            mock = MagicMock()
            mock.success = True
            mock.timed_out = False
            mock.output = "Tests passed"
            return mock

        with patch.object(check, "_run_command", side_effect=capture_command):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert commands_run[-1] == ["npx", "--yes", "jest", "--ci", "--coverage"]

    def test_exclude_dirs_hides_test_files(self, tmp_path):
        """exclude_dirs config prevents test files in those dirs from being found."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        deno_dir = tmp_path / "supabase" / "functions"
        deno_dir.mkdir(parents=True)
        (deno_dir / "handler.test.ts").write_text("Deno.test('x', () => {})")
        check = JavaScriptTestsCheck({"exclude_dirs": ["supabase/functions"]})

        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "No JavaScript/TypeScript tests found" in (result.error or "")

    def test_exclude_dirs_still_finds_non_excluded_tests(self, tmp_path):
        """exclude_dirs skips specified dirs but still finds tests elsewhere."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        deno_dir = tmp_path / "supabase" / "functions"
        deno_dir.mkdir(parents=True)
        (deno_dir / "handler.test.ts").write_text("Deno.test('x', () => {})")
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "app.test.js").write_text("test('ok', () => {})")
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptTestsCheck({"exclude_dirs": ["supabase/functions"]})

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.timed_out = False
        mock_result.output = "Tests passed"

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_skip_reason_pure_deno_project(self, tmp_path):
        """skip_reason explains why a pure Deno project is skipped."""
        (tmp_path / "deno.json").write_text("{}")
        check = JavaScriptTestsCheck({})

        reason = check.skip_reason(str(tmp_path))
        assert "Deno" in reason


class TestJavaScriptCoverageCheckBranches:
    """Branch-focused tests for JS coverage orchestration."""

    def test_run_returns_dependency_result_when_install_fails(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "smoke.test.js").write_text("test('ok', () => {})")
        check = JavaScriptCoverageCheck({})

        dep_result = check._create_result(
            status=CheckStatus.ERROR,
            duration=0.1,
            error="npm install failed",
        )
        with (
            patch.object(check, "has_javascript_test_files", return_value=True),
            patch.object(check, "_ensure_dependencies", return_value=dep_result),
        ):
            result = check.run(str(tmp_path))

        assert result is dep_result

    def test_run_uses_console_fallback_result_when_available(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "smoke.test.js").write_text("test('ok', () => {})")
        check = JavaScriptCoverageCheck({"threshold": 80})

        run_result = MagicMock()
        run_result.success = True
        run_result.output = "coverage output"
        fallback = check._create_result(status=CheckStatus.PASSED, duration=0.1)

        with (
            patch.object(check, "has_javascript_test_files", return_value=True),
            patch.object(check, "_ensure_dependencies", return_value=None),
            patch.object(check, "_run_command", return_value=run_result),
            patch.object(check, "_parse_coverage_json", return_value=None),
            patch.object(check, "_parse_coverage_output", return_value=95.0),
            patch.object(check, "_evaluate_console_coverage", return_value=fallback),
        ):
            result = check.run(str(tmp_path))

        assert result is fallback

    def test_run_no_tests_found_when_coverage_unavailable(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "smoke.test.js").write_text("test('ok', () => {})")
        check = JavaScriptCoverageCheck({})

        run_result = MagicMock()
        run_result.success = False
        run_result.output = "No tests found, exiting"

        with (
            patch.object(check, "has_javascript_test_files", return_value=True),
            patch.object(check, "_ensure_dependencies", return_value=None),
            patch.object(check, "_run_command", return_value=run_result),
            patch.object(check, "_parse_coverage_json", return_value=None),
            patch.object(check, "_parse_coverage_output", return_value=None),
            patch.object(check, "_evaluate_console_coverage", return_value=None),
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "No JavaScript/TypeScript tests found" in (result.error or "")


class TestJavaScriptLintFormatCheck:
    """Tests for JavaScriptLintFormatCheck."""

    def test_name(self):
        """Test check name."""
        check = JavaScriptLintFormatCheck({})
        assert check.name == "sloppy-formatting.js"

    def test_full_name(self):
        """Test full check name with category."""
        check = JavaScriptLintFormatCheck({})
        assert check.full_name == "laziness:sloppy-formatting.js"

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

    # ------------------------------------------------------------------
    # Deno project tests
    # ------------------------------------------------------------------

    def test_is_applicable_deno_project(self, tmp_path):
        """Test is_applicable returns True for Deno projects."""
        (tmp_path / "deno.json").write_text("{}")
        check = JavaScriptLintFormatCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_deno_jsonc(self, tmp_path):
        """Test is_applicable returns True for Deno projects with deno.jsonc."""
        (tmp_path / "deno.jsonc").write_text("{}")
        check = JavaScriptLintFormatCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_run_deno_project_uses_deno_lint_and_fmt(self, tmp_path):
        """Deno project run() calls deno lint + deno fmt, not npx."""
        (tmp_path / "deno.json").write_text("{}")
        check = JavaScriptLintFormatCheck({})

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = ""

        with patch.object(check, "_run_command", return_value=mock_result) as mock_run:
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        commands = [call.args[0] for call in mock_run.call_args_list]
        assert ["deno", "lint", "--json"] in commands
        assert ["deno", "fmt", "--check"] in commands
        # Must NOT invoke npx
        for cmd in commands:
            assert cmd[0] != "npx", f"npx called in Deno project: {cmd}"

    def test_run_deno_lint_fails(self, tmp_path):
        """Deno project run() reports lint failures."""
        (tmp_path / "deno.json").write_text("{}")
        check = JavaScriptLintFormatCheck({})

        lint_result = MagicMock()
        lint_result.success = False
        lint_result.output = "error"
        lint_result.stdout = json.dumps(
            {
                "diagnostics": [
                    {
                        "message": "no-unused-vars",
                        "code": "no-unused-vars",
                        "filename": "main.ts",
                        "range": {"start": {"line": 1}},
                    }
                ]
            }
        )

        fmt_result = MagicMock()
        fmt_result.success = True
        fmt_result.output = ""

        with patch.object(check, "_run_command", side_effect=[lint_result, fmt_result]):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED

    def test_run_deno_lint_unparseable_json_produces_finding(self, tmp_path):
        """When deno lint stdout cannot be parsed as JSON, a Finding is returned."""
        (tmp_path / "deno.json").write_text("{}")
        check = JavaScriptLintFormatCheck({})

        lint_result = MagicMock()
        lint_result.success = False
        lint_result.stdout = "not valid json at all"
        lint_result.output = "not valid json at all"

        fmt_result = MagicMock()
        fmt_result.success = True
        fmt_result.output = ""

        with patch.object(check, "_run_command", side_effect=[lint_result, fmt_result]):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        # Must have at least one Finding (not an empty list)
        assert result.findings, "Expected findings for unparseable JSON output"
        assert any(
            "could not be parsed" in f.message for f in result.findings
        ), "Expected 'could not be parsed' in finding message"

    def test_run_deno_lint_line_numbers_offset_to_1indexed(self, tmp_path):
        """deno lint --json emits 0-indexed lines; Finding.line must be 1-indexed."""
        (tmp_path / "deno.json").write_text("{}")
        check = JavaScriptLintFormatCheck({})

        lint_result = MagicMock()
        lint_result.success = False
        lint_result.output = "error"
        lint_result.stdout = json.dumps(
            {
                "diagnostics": [
                    {
                        "message": "no-console",
                        "code": "no-console",
                        "filename": "main.ts",
                        "range": {"start": {"line": 0}},  # 0-indexed
                    }
                ]
            }
        )

        fmt_result = MagicMock()
        fmt_result.success = True
        fmt_result.output = ""

        with patch.object(check, "_run_command", side_effect=[lint_result, fmt_result]):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert result.findings, "Expected at least one Finding"
        # 0-indexed 0 should become 1-indexed 1
        assert (
            result.findings[0].line == 1
        ), f"Expected line=1 (1-indexed), got {result.findings[0].line}"

    def test_auto_fix_deno_project(self, tmp_path):
        """Deno project auto_fix() calls deno lint --fix + deno fmt."""
        (tmp_path / "deno.json").write_text("{}")
        check = JavaScriptLintFormatCheck({})

        mock_result = MagicMock()
        mock_result.success = True

        with patch.object(check, "_run_command", return_value=mock_result) as mock_run:
            result = check.auto_fix(str(tmp_path))

        assert result is True
        commands = [call.args[0] for call in mock_run.call_args_list]
        assert ["deno", "lint", "--fix"] in commands
        assert ["deno", "fmt"] in commands
        for cmd in commands:
            assert cmd[0] != "npx", f"npx called in Deno project: {cmd}"

    def test_node_project_still_uses_eslint_prettier(self, tmp_path):
        """Node project (no deno.json) still uses ESLint + Prettier path."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptLintFormatCheck({})

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = ""

        with patch.object(check, "_run_command", return_value=mock_result) as mock_run:
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        commands = [call.args[0] for call in mock_run.call_args_list]
        # Node path should use npx eslint/prettier
        npx_commands = [cmd for cmd in commands if cmd[0] == "npx"]
        assert len(npx_commands) >= 1
        # Must NOT invoke deno
        for cmd in commands:
            assert cmd[0] != "deno", f"deno called in Node project: {cmd}"

    def test_run_hybrid_both_pass(self, tmp_path):
        """Hybrid repo (deno.json + package.json) runs both stacks and passes."""
        (tmp_path / "deno.json").write_text("{}")
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptLintFormatCheck({})

        pass_result = MagicMock()
        pass_result.success = True
        pass_result.output = ""
        pass_result.stdout = ""

        with patch.object(check, "_run_command", return_value=pass_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_hybrid_node_fails(self, tmp_path):
        """Hybrid repo returns FAILED when node stack fails."""
        (tmp_path / "deno.json").write_text("{}")
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptLintFormatCheck({})

        deno_pass = MagicMock()
        deno_pass.success = True
        deno_pass.output = ""
        deno_pass.stdout = ""

        node_fail = MagicMock()
        node_fail.success = False
        node_fail.output = "1 error"
        node_fail.stdout = "[]"

        # _run_deno calls: deno lint, deno fmt. _run_node calls: npx eslint, npx prettier.
        def side_effect(cmd, **kwargs):
            if cmd[0] == "deno":
                return deno_pass
            return node_fail

        with patch.object(check, "_run_command", side_effect=side_effect):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED

    def test_run_hybrid_node_error_propagates(self, tmp_path):
        """Hybrid repo returns ERROR (not PASSED) when node stack errors."""
        (tmp_path / "deno.json").write_text("{}")
        (tmp_path / "package.json").write_text('{"name": "test"}')
        # No node_modules — triggers npm install ERROR path
        check = JavaScriptLintFormatCheck({})

        deno_pass = MagicMock()
        deno_pass.success = True
        deno_pass.output = ""
        deno_pass.stdout = ""

        npm_fail = MagicMock()
        npm_fail.success = False
        npm_fail.output = "npm install failed"

        def side_effect(cmd, **kwargs):
            if cmd[0] == "deno":
                return deno_pass
            return npm_fail

        with patch.object(check, "_run_command", side_effect=side_effect):
            result = check.run(str(tmp_path))

        # npm install failure returns ERROR, not PASSED
        assert result.status != CheckStatus.PASSED

    def test_auto_fix_hybrid_runs_both(self, tmp_path):
        """Hybrid repo auto_fix() runs both deno and node fix commands."""
        (tmp_path / "deno.json").write_text("{}")
        (tmp_path / "package.json").write_text('{"name": "test"}')
        check = JavaScriptLintFormatCheck({})

        mock_result = MagicMock()
        mock_result.success = True

        with patch.object(check, "_run_command", return_value=mock_result) as mock_run:
            result = check.auto_fix(str(tmp_path))

        assert result is True
        commands = [call.args[0] for call in mock_run.call_args_list]
        # Must call both deno and npx
        assert any(cmd[0] == "deno" for cmd in commands)
        assert any(cmd[0] == "npx" for cmd in commands)

    def test_get_deno_target_dirs_scoped(self, tmp_path):
        """_get_deno_target_dirs extracts path from deno lint script."""
        subdir = tmp_path / "functions"
        subdir.mkdir()
        pkg = {"scripts": {"lint": f"deno lint {subdir.name}/"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))

        targets = JavaScriptLintFormatCheck._get_deno_target_dirs(str(tmp_path))
        assert f"{subdir.name}/" in targets

    def test_get_deno_target_dirs_no_package_json(self, tmp_path):
        """_get_deno_target_dirs returns [] when no package.json."""
        targets = JavaScriptLintFormatCheck._get_deno_target_dirs(str(tmp_path))
        assert targets == []


class TestJavaScriptCoverageCheck:
    """Tests for JavaScriptCoverageCheck."""

    def test_name(self):
        """Test check name."""
        check = JavaScriptCoverageCheck({})
        assert check.name == "coverage-gaps.js"

    def test_full_name(self):
        """Test full check name with category."""
        check = JavaScriptCoverageCheck({})
        assert check.full_name == "overconfidence:coverage-gaps.js"

    def test_display_name(self):
        """Test display name."""
        check = JavaScriptCoverageCheck({})
        assert "Coverage" in check.display_name

    def test_depends_on(self):
        """Test dependencies."""
        check = JavaScriptCoverageCheck({})
        assert "overconfidence:untested-code.js" in check.depends_on

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

    def test_run_fails_when_no_test_files(self, tmp_path):
        """Coverage gate fails when no JS/TS test files are present."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptCoverageCheck({})

        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "No JavaScript/TypeScript tests found" in (result.error or "")


class TestFrontendCheck:
    """Tests for FrontendCheck."""

    def test_name(self):
        """Test check name."""
        check = FrontendCheck({})
        assert check.name == "sloppy-frontend.js"

    def test_full_name(self):
        """Test full check name with category."""
        check = FrontendCheck({})
        assert check.full_name == "laziness:sloppy-frontend.js"

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


class TestJavaScriptTypesCheck:
    """Tests for JavaScriptTypesCheck."""

    def test_name(self):
        """Test check name."""
        check = JavaScriptTypesCheck({})
        assert check.name == "type-blindness.js"

    def test_full_name(self):
        """Test full check name with category."""
        check = JavaScriptTypesCheck({})
        assert check.full_name == "overconfidence:type-blindness.js"

    def test_display_name(self):
        """Test display name."""
        check = JavaScriptTypesCheck({})
        assert "TypeScript" in check.display_name

    def test_depends_on(self):
        """Test dependencies."""
        check = JavaScriptTypesCheck({})
        assert "laziness:sloppy-formatting.js" in check.depends_on

    def test_config_schema(self):
        """Test config schema includes expected fields."""
        check = JavaScriptTypesCheck({})
        schema = check.config_schema
        field_names = [f.name for f in schema]
        assert "tsconfig" in field_names
        # type_check_command should NOT be in schema (it was removed)
        assert "type_check_command" not in field_names

    def test_init_config_prefers_tsconfig_ci(self, tmp_path):
        """Gate-owned init hook should surface tsconfig.ci.json when present."""
        (tmp_path / "tsconfig.ci.json").write_text('{"compilerOptions": {}}')
        check = JavaScriptTypesCheck({})

        assert check.init_config(str(tmp_path)) == {"tsconfig": "tsconfig.ci.json"}

    def test_is_applicable_with_tsconfig(self, tmp_path):
        """Test is_applicable returns True for TS projects with tsconfig.json."""
        (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {}}')
        check = JavaScriptTypesCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_with_tsconfig_ci(self, tmp_path):
        """Test is_applicable returns True for TS projects with tsconfig.ci.json."""
        (tmp_path / "tsconfig.ci.json").write_text('{"compilerOptions": {}}')
        check = JavaScriptTypesCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_with_custom_tsconfig(self, tmp_path):
        """Test is_applicable returns True when custom tsconfig exists."""
        (tmp_path / "tsconfig.prod.json").write_text('{"compilerOptions": {}}')
        check = JavaScriptTypesCheck({"tsconfig": "tsconfig.prod.json"})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_no_tsconfig(self, tmp_path):
        """Test is_applicable returns False when no tsconfig exists."""
        (tmp_path / "app.js").write_text("console.log('hello')")
        check = JavaScriptTypesCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_run_passes(self, tmp_path):
        """Test run() when type checking passes."""
        (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {}}')
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptTypesCheck({})

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.timed_out = False
        mock_result.output = ""

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_with_errors(self, tmp_path):
        """Test run() when type errors are found."""
        (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {}}')
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptTypesCheck({})

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.timed_out = False
        mock_result.output = (
            "error TS2345: Something is wrong\nerror TS2322: Another error"
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "2 TypeScript error(s)" in result.error
        # Check fix_suggestion includes verify command
        assert "sm swab -g" in result.fix_suggestion

    def test_run_timeout(self, tmp_path):
        """Test run() when type checking times out."""
        (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {}}')
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptTypesCheck({})

        mock_result = MagicMock()
        mock_result.timed_out = True
        mock_result.output = ""

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "timed out" in result.error

    def test_run_installs_deps_when_missing(self, tmp_path):
        """Test run() installs deps when node_modules missing."""
        (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {}}')
        check = JavaScriptTypesCheck({})

        npm_result = MagicMock()
        npm_result.success = True

        tsc_result = MagicMock()
        tsc_result.success = True
        tsc_result.timed_out = False
        tsc_result.output = ""

        with patch.object(check, "_run_command", side_effect=[npm_result, tsc_result]):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_npm_install_fails(self, tmp_path):
        """Test run() when npm install fails."""
        (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {}}')
        check = JavaScriptTypesCheck({})

        npm_result = MagicMock()
        npm_result.success = False
        npm_result.output = "npm ERR!"

        with patch.object(check, "_run_command", return_value=npm_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.ERROR
        assert "npm install failed" in result.error

    def test_run_respects_user_configured_tsconfig(self, tmp_path):
        """Test run() uses user-configured tsconfig over CI fallback."""
        (tmp_path / "tsconfig.prod.json").write_text('{"compilerOptions": {}}')
        (tmp_path / "tsconfig.ci.json").write_text('{"compilerOptions": {}}')
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptTypesCheck({"tsconfig": "tsconfig.prod.json"})

        commands_run = []

        def capture_command(cmd, **kwargs):
            commands_run.append(cmd)
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.timed_out = False
            mock_result.output = ""
            return mock_result

        with patch.object(check, "_run_command", side_effect=capture_command):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        # Verify the correct tsconfig was used
        tsc_cmd = commands_run[0]
        assert "tsconfig.prod.json" in tsc_cmd

    def test_run_uses_ci_tsconfig_as_fallback(self, tmp_path):
        """Test run() falls back to tsconfig.ci.json when no user config."""
        (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {}}')
        (tmp_path / "tsconfig.ci.json").write_text('{"compilerOptions": {}}')
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptTypesCheck({})  # No explicit tsconfig config

        commands_run = []

        def capture_command(cmd, **kwargs):
            commands_run.append(cmd)
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.timed_out = False
            mock_result.output = ""
            return mock_result

        with patch.object(check, "_run_command", side_effect=capture_command):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        # Verify tsconfig.ci.json was used
        tsc_cmd = commands_run[0]
        assert "tsconfig.ci.json" in tsc_cmd
