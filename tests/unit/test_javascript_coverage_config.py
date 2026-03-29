"""Tests for configurable JavaScript coverage workflows."""

from unittest.mock import MagicMock, patch

from slopmop.checks.javascript.coverage import JavaScriptCoverageCheck
from slopmop.core.result import CheckStatus


class TestJavaScriptCoverageConfig:
    """Tests for coverage_command / coverage_report_path support."""

    def test_config_schema_includes_coverage_workflow_fields(self):
        check = JavaScriptCoverageCheck({})
        schema = check.config_schema
        field_names = [f.name for f in schema]

        assert "coverage_command" in field_names
        assert "coverage_report_path" in field_names
        assert "coverage_format" in field_names

    def test_init_config_discovers_supabase_deno_coverage_workflow(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "deno.json").write_text("{}")
        deno_test = (
            tmp_path / "supabase" / "functions" / "teams" / "validation.unit.test.ts"
        )
        deno_test.parent.mkdir(parents=True)
        deno_test.write_text("Deno.test('ok', () => {})")

        check = JavaScriptCoverageCheck({})

        assert check.init_config(str(tmp_path)) == {
            "coverage_command": "deno test --allow-all --no-check "
            "--coverage=coverage/raw supabase/functions/**/*.unit.test.ts",
            "coverage_report_path": "coverage/raw",
            "coverage_format": "deno",
        }

    def test_run_uses_configured_coverage_command(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "smoke.test.js").write_text("test('ok', () => {})")
        report_path = tmp_path / "coverage" / "coverage-summary.json"
        report_path.parent.mkdir()
        report_path.write_text(
            '{"total": {"lines": {"pct": 95}}, "src/app.ts": {"lines": {"pct": 95}}}'
        )

        check = JavaScriptCoverageCheck(
            {
                "coverage_command": "deno test --coverage=coverage/raw",
                "coverage_report_path": "coverage/coverage-summary.json",
            }
        )
        run_result = MagicMock()
        run_result.success = True
        run_result.output = "ok"

        with (
            patch.object(check, "has_javascript_test_files", return_value=True),
            patch.object(check, "_run_command", return_value=run_result) as mock_run,
            patch.object(check, "_ensure_dependencies") as mock_ensure,
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert mock_run.call_args.args[0] == ["deno", "test", "--coverage=coverage/raw"]
        mock_ensure.assert_not_called()

    def test_parse_lcov_report_converts_to_summary_shape(self, tmp_path):
        check = JavaScriptCoverageCheck({})
        report_path = tmp_path / "coverage" / "lcov.info"
        report_path.parent.mkdir()
        source_file = tmp_path / "src" / "app.ts"
        source_file.parent.mkdir()
        source_file.write_text("export const x = 1;\n")
        report_path.write_text(
            "\n".join(
                [
                    f"SF:{source_file}",
                    "DA:1,1",
                    "DA:2,0",
                    "end_of_record",
                ]
            )
        )

        summary = check._parse_lcov_report(str(tmp_path), report_path)

        assert summary is not None
        assert summary["total"]["lines"]["total"] == 2
        assert summary["total"]["lines"]["covered"] == 1
        assert summary["src/app.ts"]["lines"]["pct"] == 50.0

    def test_parse_lcov_report_relative_sf_resolves_from_project_root(self, tmp_path):
        """Relative SF: paths resolve from project root regardless of report depth."""
        check = JavaScriptCoverageCheck({})
        # Report is nested 3 levels deep — old .parent.parent would be wrong
        report_path = tmp_path / "output" / "coverage" / "lcov.info"
        report_path.parent.mkdir(parents=True)
        source_file = tmp_path / "src" / "app.ts"
        source_file.parent.mkdir()
        source_file.write_text("export const x = 1;\n")
        report_path.write_text(
            "\n".join(
                [
                    "SF:src/app.ts",
                    "DA:1,1",
                    "DA:2,0",
                    "end_of_record",
                ]
            )
        )

        summary = check._parse_lcov_report(str(tmp_path), report_path)

        assert summary is not None, "relative SF path should resolve from project root"
        assert "src/app.ts" in summary
        assert summary["src/app.ts"]["lines"]["pct"] == 50.0

    def test_parse_deno_report_uses_deno_coverage_lcov(self, tmp_path):
        check = JavaScriptCoverageCheck({"coverage_format": "deno"})
        report_path = tmp_path / "coverage" / "raw"
        report_path.mkdir(parents=True)
        source_file = tmp_path / "src" / "app.ts"
        source_file.parent.mkdir()
        source_file.write_text("export const x = 1;\n")

        lcov_output = "\n".join(
            [
                f"SF:{source_file}",
                "DA:1,1",
                "DA:2,0",
                "end_of_record",
            ]
        )
        run_result = MagicMock()
        run_result.success = True
        run_result.stdout = lcov_output

        with patch.object(check, "_run_command", return_value=run_result) as mock_run:
            summary = check._parse_deno_report(str(tmp_path), report_path)

        assert summary is not None
        assert summary["src/app.ts"]["lines"]["pct"] == 50.0
        assert mock_run.call_args.args[0] == [
            "deno",
            "coverage",
            "--lcov",
            str(report_path),
        ]

    def test_parse_deno_report_relative_sf_resolves_from_project_root(self, tmp_path):
        """SF: relative paths in deno lcov output resolve from project root, not
        report_path.parent (which would be coverage/ — one dir too deep)."""
        check = JavaScriptCoverageCheck({"coverage_format": "deno"})
        report_path = tmp_path / "coverage" / "raw"
        report_path.mkdir(parents=True)
        source_file = tmp_path / "src" / "app.ts"
        source_file.parent.mkdir()
        source_file.write_text("export const x = 1;\n")

        # Relative SF path — Deno typically emits these relative to project root
        lcov_output = "\n".join(
            [
                "SF:src/app.ts",
                "DA:1,1",
                "DA:2,0",
                "end_of_record",
            ]
        )
        run_result = MagicMock()
        run_result.success = True
        run_result.stdout = lcov_output

        with patch.object(check, "_run_command", return_value=run_result):
            summary = check._parse_deno_report(str(tmp_path), report_path)

        assert summary is not None, "relative SF path should resolve successfully"
        assert "src/app.ts" in summary, "key should be relative to project root"
        assert summary["src/app.ts"]["lines"]["pct"] == 50.0
