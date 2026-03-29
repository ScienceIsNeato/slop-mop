"""Tests for configurable JS/TS runner workflows."""

from unittest.mock import MagicMock, patch

from slopmop.checks.javascript.tests import JavaScriptTestsCheck
from slopmop.core.result import CheckStatus


class TestJavaScriptRunnerConfig:
    """Tests for gate-owned JS runner configuration discovery."""

    def test_init_config_discovers_supabase_deno_test_command(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "deno.json").write_text("{}")
        deno_test = (
            tmp_path / "supabase" / "functions" / "teams" / "validation.unit.test.ts"
        )
        deno_test.parent.mkdir(parents=True)
        deno_test.write_text("Deno.test('ok', () => {})")

        check = JavaScriptTestsCheck({})

        assert check.init_config(str(tmp_path)) == {
            "test_command": "deno test --allow-all --no-check "
            "supabase/functions/**/*.unit.test.ts"
        }

    def test_custom_test_command_skips_npm_install(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "smoke.test.js").write_text("test('ok', () => {})")
        check = JavaScriptTestsCheck(
            {"test_command": "deno test --allow-all --no-check tests/smoke.test.js"}
        )

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.timed_out = False
        mock_result.output = "Tests passed"

        with patch.object(check, "_run_command", return_value=mock_result) as mock_run:
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert mock_run.call_count == 1
        assert mock_run.call_args.args[0] == [
            "deno",
            "test",
            "--allow-all",
            "--no-check",
            "tests/smoke.test.js",
        ]
