"""Tests for JavaScriptExpectCheck (eslint-plugin-jest expect-expect)."""

import json
import os
from unittest.mock import MagicMock, patch

from slopmop.checks.javascript.eslint_expect import JavaScriptExpectCheck
from slopmop.core.result import CheckStatus


class TestJavaScriptExpectCheck:
    """Tests for JavaScriptExpectCheck (eslint-plugin-jest expect-expect)."""

    def test_name(self):
        """Test check name."""
        check = JavaScriptExpectCheck({})
        assert check.name == "hand-wavy-tests.js"

    def test_full_name(self):
        """Test full check name with category."""
        check = JavaScriptExpectCheck({})
        assert check.full_name == "deceptiveness:hand-wavy-tests.js"

    def test_display_name(self):
        """Test display name."""
        check = JavaScriptExpectCheck({})
        assert "Expect" in check.display_name
        assert "expect-expect" in check.display_name

    def test_config_schema(self):
        """Test config schema includes expected fields."""
        check = JavaScriptExpectCheck({})
        schema = check.config_schema
        field_names = [f.name for f in schema]
        assert "additional_assert_functions" in field_names
        assert "exclude_dirs" in field_names
        assert "max_violations" in field_names

    def test_is_applicable_with_test_files(self, tmp_path):
        """Test is_applicable returns True for JS projects with test files."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.test.js").write_text("test('x', () => {})")
        check = JavaScriptExpectCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_no_package_json(self, tmp_path):
        """Test is_applicable returns False without package.json."""
        (tmp_path / "app.test.js").write_text("test('x', () => {})")
        check = JavaScriptExpectCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_is_applicable_no_test_files(self, tmp_path):
        """Test is_applicable returns False when no test files exist."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "index.js").write_text("module.exports = {}")
        check = JavaScriptExpectCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_is_applicable_with_spec_files(self, tmp_path):
        """Test is_applicable detects .spec.ts files."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "app.spec.ts").write_text("it('works', () => {})")
        check = JavaScriptExpectCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_run_passes_all_tests_have_assertions(self, tmp_path):
        """Test run() passes when all tests have assertions."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "app.test.js").write_text(
            "test('works', () => { expect(1).toBe(1); })"
        )
        check = JavaScriptExpectCheck({})

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.timed_out = False
        mock_result.returncode = 0
        mock_result.stdout = json.dumps([{"filePath": "/app.test.js", "messages": []}])

        with (
            patch.object(check, "_install_eslint_deps", return_value=None),
            patch.object(check, "_run_command", return_value=mock_result),
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert "1 test file(s) have assertions" in result.output

    def test_run_fails_tests_without_assertions(self, tmp_path):
        """Test run() fails when tests lack assertions."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        test_file = tmp_path / "app.test.js"
        test_file.write_text("test('no assert', () => { console.log('hi'); })")
        check = JavaScriptExpectCheck({})

        eslint_output = json.dumps(
            [
                {
                    "filePath": str(test_file),
                    "messages": [
                        {
                            "ruleId": "jest/expect-expect",
                            "line": 1,
                            "message": "Test has no assertions",
                        }
                    ],
                }
            ]
        )

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.timed_out = False
        mock_result.returncode = 1
        mock_result.stdout = eslint_output

        with (
            patch.object(check, "_install_eslint_deps", return_value=None),
            patch.object(check, "_run_command", return_value=mock_result),
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "1 test(s) without assertions" in result.error

    def test_run_respects_max_violations(self, tmp_path):
        """Test run() passes when violations <= max_violations."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        test_file = tmp_path / "app.test.js"
        test_file.write_text("test('no assert', () => {})")
        check = JavaScriptExpectCheck({"max_violations": 1})

        eslint_output = json.dumps(
            [
                {
                    "filePath": str(test_file),
                    "messages": [
                        {
                            "ruleId": "jest/expect-expect",
                            "line": 1,
                            "message": "Test has no assertions",
                        }
                    ],
                }
            ]
        )

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.timed_out = False
        mock_result.returncode = 1
        mock_result.stdout = eslint_output

        with (
            patch.object(check, "_install_eslint_deps", return_value=None),
            patch.object(check, "_run_command", return_value=mock_result),
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert "max allowed: 1" in result.output

    def test_run_timeout(self, tmp_path):
        """Test run() handles eslint timeout."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "app.test.js").write_text("test('x', () => {})")
        check = JavaScriptExpectCheck({})

        mock_result = MagicMock()
        mock_result.timed_out = True
        mock_result.output = ""

        with (
            patch.object(check, "_install_eslint_deps", return_value=None),
            patch.object(check, "_run_command", return_value=mock_result),
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.ERROR
        assert "timed out" in result.error

    def test_run_config_error(self, tmp_path):
        """Test run() handles eslint config error (exit code 2)."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "app.test.js").write_text("test('x', () => {})")
        check = JavaScriptExpectCheck({})

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.timed_out = False
        mock_result.returncode = 2
        mock_result.output = "ESLint configuration error"

        with (
            patch.object(check, "_install_eslint_deps", return_value=None),
            patch.object(check, "_run_command", return_value=mock_result),
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.ERROR
        assert "configuration error" in result.error

    def test_run_skips_no_test_files(self, tmp_path):
        """Test run() skips when no test files found."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "index.js").write_text("module.exports = {}")
        check = JavaScriptExpectCheck({})

        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.SKIPPED
        assert "No test files" in result.output

    def test_run_passes_additional_assert_functions(self, tmp_path):
        """Test run() includes custom assertion function names in command."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "app.test.js").write_text("test('x', () => { customAssert(); })")
        check = JavaScriptExpectCheck(
            {"additional_assert_functions": ["customAssert", "expectSaga"]}
        )

        commands_run = []

        def capture_command(cmd, **kwargs):
            commands_run.append(cmd)
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.timed_out = False
            mock_result.returncode = 0
            mock_result.stdout = json.dumps([])
            return mock_result

        with (
            patch.object(check, "_install_eslint_deps", return_value=None),
            patch.object(check, "_run_command", side_effect=capture_command),
        ):
            check.run(str(tmp_path))

        assert len(commands_run) == 1
        cmd = commands_run[0]
        rule_idx = cmd.index("--rule")
        rule_value = cmd[rule_idx + 1]
        assert "customAssert" in rule_value
        assert "expectSaga" in rule_value

    def test_run_excludes_node_modules(self, tmp_path):
        """Test _find_test_files excludes node_modules."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.test.js").write_text("test('x', () => {})")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "dep.test.js").write_text("test('x', () => {})")
        check = JavaScriptExpectCheck({})

        files = check._find_test_files(str(tmp_path))

        assert len(files) == 1
        assert files[0].endswith("src/app.test.js") or "src" in files[0]

    def test_run_excludes_configured_dirs(self, tmp_path):
        """Test _find_test_files respects exclude_dirs config."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.test.js").write_text("test('x', () => {})")
        (tmp_path / "generated").mkdir()
        (tmp_path / "generated" / "gen.test.js").write_text("test('x', () => {})")
        check = JavaScriptExpectCheck({"exclude_dirs": ["generated"]})

        files = check._find_test_files(str(tmp_path))

        assert len(files) == 1
        assert files[0].endswith("src/app.test.js") or "src" in files[0]

    def test_extract_violations_parses_json(self):
        """Test _extract_violations correctly parses ESLint JSON output."""
        check = JavaScriptExpectCheck({})
        project_root = "/project"
        output = json.dumps(
            [
                {
                    "filePath": "/project/src/app.test.js",
                    "messages": [
                        {
                            "ruleId": "jest/expect-expect",
                            "line": 5,
                            "message": "Test has no assertions",
                        },
                        {
                            "ruleId": "no-unused-vars",
                            "line": 1,
                            "message": "x is unused",
                        },
                    ],
                }
            ]
        )

        violations, parse_errors = check._extract_violations(output, project_root)

        assert violations is not None
        assert len(violations) == 1
        assert violations[0]["file"] == "src/app.test.js"
        assert violations[0]["line"] == 5
        assert parse_errors == []

    def test_extract_violations_separates_fatal_parse_errors(self):
        """Test _extract_violations returns fatal parse errors separately."""
        check = JavaScriptExpectCheck({})
        project_root = "/project"
        output = json.dumps(
            [
                {
                    "filePath": "/project/src/broken.test.js",
                    "messages": [
                        {
                            "ruleId": None,
                            "fatal": True,
                            "line": 11,
                            "message": "Parsing error: Unexpected token )",
                        }
                    ],
                }
            ]
        )

        violations, parse_errors = check._extract_violations(output, project_root)

        assert violations == []
        assert len(parse_errors) == 1
        assert parse_errors[0]["file"] == "src/broken.test.js"
        assert parse_errors[0]["line"] == 11
        assert "Parse error" in parse_errors[0]["message"]
        assert "Unexpected token" in parse_errors[0]["message"]

    def test_extract_violations_handles_invalid_json(self):
        """Test _extract_violations returns (None, None) for non-JSON output."""
        check = JavaScriptExpectCheck({})
        violations, parse_errors = check._extract_violations("not json", "/project")
        assert violations is None
        assert parse_errors is None

    def test_run_non_parseable_success(self, tmp_path):
        """Test run() treats non-JSON exit-0 as passed."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "app.test.js").write_text("test('x', () => { expect(1).toBe(1); })")
        check = JavaScriptExpectCheck({})

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.timed_out = False
        mock_result.returncode = 0
        mock_result.stdout = "All good"

        with (
            patch.object(check, "_install_eslint_deps", return_value=None),
            patch.object(check, "_run_command", return_value=mock_result),
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_non_parseable_failure(self, tmp_path):
        """Test run() reports error for non-JSON non-zero exit."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "app.test.js").write_text("test('x', () => {})")
        check = JavaScriptExpectCheck({})

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.timed_out = False
        mock_result.returncode = 1
        mock_result.stdout = "Something went wrong"

        with (
            patch.object(check, "_install_eslint_deps", return_value=None),
            patch.object(check, "_run_command", return_value=mock_result),
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.ERROR
        assert "Could not parse" in result.error

    def test_run_npm_install_fails(self, tmp_path):
        """Test run() reports error when eslint dep install fails."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "app.test.js").write_text("test('x', () => {})")
        check = JavaScriptExpectCheck({})

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.output = "npm ERR! code E404"

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.ERROR
        assert "install eslint" in result.error.lower()

    def test_run_uses_absolute_parser_path_for_typescript(self, tmp_path):
        """Test run() passes absolute path to @typescript-eslint/parser for .ts files."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "app.test.ts").write_text(
            "test('works', () => { expect(1).toBe(1); })"
        )
        check = JavaScriptExpectCheck({})

        commands_run: list = []

        def capture_command(cmd, **kwargs):
            commands_run.append(cmd)
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.timed_out = False
            mock_result.returncode = 0
            mock_result.stdout = json.dumps([])
            return mock_result

        with (
            patch.object(check, "_install_eslint_deps", return_value=None),
            patch.object(check, "_run_command", side_effect=capture_command),
        ):
            check.run(str(tmp_path))

        assert len(commands_run) == 1
        cmd = commands_run[0]
        parser_idx = cmd.index("--parser")
        parser_value = cmd[parser_idx + 1]
        assert os.path.isabs(
            parser_value
        ), f"Parser should be absolute path, got: {parser_value}"
        assert parser_value.endswith(
            os.path.join("@typescript-eslint", "parser", "dist", "index.js")
        )

    def test_run_omits_parser_for_plain_js(self, tmp_path):
        """Test run() does not include --parser when only .js test files exist."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "app.test.js").write_text(
            "test('works', () => { expect(1).toBe(1); })"
        )
        check = JavaScriptExpectCheck({})

        commands_run: list = []

        def capture_command(cmd, **kwargs):
            commands_run.append(cmd)
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.timed_out = False
            mock_result.returncode = 0
            mock_result.stdout = json.dumps([])
            return mock_result

        with (
            patch.object(check, "_install_eslint_deps", return_value=None),
            patch.object(check, "_run_command", side_effect=capture_command),
        ):
            check.run(str(tmp_path))

        assert len(commands_run) == 1
        cmd = commands_run[0]
        assert "--parser" not in cmd
