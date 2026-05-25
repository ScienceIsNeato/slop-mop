"""Tests for the laziness:dead-code.js gate (knip)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from slopmop.checks.javascript.dead_code import JavaScriptDeadCodeCheck
from slopmop.core.result import CheckStatus


class TestJavaScriptDeadCodeCheckMetadata:
    def test_name(self):
        assert JavaScriptDeadCodeCheck({}).name == "dead-code.js"

    def test_full_name(self):
        assert JavaScriptDeadCodeCheck({}).full_name == "laziness:dead-code.js"

    def test_display_name(self):
        assert "Dead Code" in JavaScriptDeadCodeCheck({}).display_name

    def test_depends_on(self):
        assert "laziness:sloppy-formatting.js" in JavaScriptDeadCodeCheck({}).depends_on

    def test_config_schema_has_ignore_patterns(self):
        fields = {f.name for f in JavaScriptDeadCodeCheck({}).config_schema}
        assert "ignore_patterns" in fields

    def test_config_schema_has_ignore_dependencies(self):
        fields = {f.name for f in JavaScriptDeadCodeCheck({}).config_schema}
        assert "ignore_dependencies" in fields


class TestJavaScriptDeadCodeCheckApplicability:
    def test_applicable_with_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "test"}')
        assert JavaScriptDeadCodeCheck({}).is_applicable(str(tmp_path)) is True

    def test_not_applicable_without_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("x = 1")
        assert JavaScriptDeadCodeCheck({}).is_applicable(str(tmp_path)) is False

    def test_skip_reason_is_string(self, tmp_path: Path) -> None:
        reason = JavaScriptDeadCodeCheck({}).skip_reason(str(tmp_path))
        assert isinstance(reason, str) and len(reason) > 0


class TestJavaScriptDeadCodeCheckRun:
    def _make_result(
        self,
        *,
        success: bool,
        stdout: str = "",
        output: str = "",
        timed_out: bool = False,
    ) -> MagicMock:
        r = MagicMock()
        r.success = success
        r.stdout = stdout
        r.output = output or stdout
        r.timed_out = timed_out
        return r

    def test_passes_when_knip_exits_zero(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptDeadCodeCheck({})
        with patch.object(
            check, "_run_command", return_value=self._make_result(success=True)
        ):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_installs_deps_when_node_modules_missing(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        check = JavaScriptDeadCodeCheck({})
        calls = []

        def fake_run(cmd, **_kwargs):
            calls.append(cmd)
            return self._make_result(success=True)

        with patch.object(check, "_run_command", side_effect=fake_run):
            check.run(str(tmp_path))

        assert any("install" in " ".join(c) for c in calls)

    def test_returns_error_when_npm_install_fails(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        check = JavaScriptDeadCodeCheck({})
        npm_fail = self._make_result(success=False, output="npm error")
        with patch.object(check, "_run_command", return_value=npm_fail):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.ERROR

    def test_returns_failed_on_timeout(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptDeadCodeCheck({})
        with patch.object(
            check,
            "_run_command",
            return_value=self._make_result(success=False, timed_out=True),
        ):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert result.findings

    def test_returns_error_when_no_json_output(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptDeadCodeCheck({})
        with patch.object(
            check,
            "_run_command",
            return_value=self._make_result(
                success=False, stdout="", output="knip: config error"
            ),
        ):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.ERROR

    def test_fails_with_findings_on_knip_issues(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "node_modules").mkdir()
        knip_output = json.dumps(
            [{"file": "src/foo.ts", "exports": [{"name": "myFn", "line": 5, "col": 1}]}]
        )
        check = JavaScriptDeadCodeCheck({})
        with patch.object(
            check,
            "_run_command",
            return_value=self._make_result(success=False, stdout=knip_output),
        ):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert result.findings
        assert any("myFn" in f.message for f in result.findings)

    def test_appends_knip_config_flag_when_configured(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptDeadCodeCheck({"knip_config": "knip.ci.json"})
        captured = []

        def fake_run(cmd, **_kwargs):
            captured.append(cmd)
            return self._make_result(success=True)

        with patch.object(check, "_run_command", side_effect=fake_run):
            check.run(str(tmp_path))

        knip_cmd = next(c for c in captured if "knip" in " ".join(c))
        assert "--config" in knip_cmd
        assert "knip.ci.json" in knip_cmd

    def test_ignore_patterns_writes_temp_config(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptDeadCodeCheck(
            {"ignore_patterns": [".detoxrc.js", ".maestro/**"]}
        )
        captured = []

        def fake_run(cmd, **_kwargs):
            captured.append(cmd)
            return self._make_result(success=True)

        with patch.object(check, "_run_command", side_effect=fake_run):
            check.run(str(tmp_path))

        knip_cmd = next(c for c in captured if "knip" in " ".join(c))
        assert "--config" in knip_cmd
        # Temp config is cleaned up after run
        assert not (tmp_path / "_sm_knip.json").exists()

    def test_ignore_dependencies_written_to_temp_config(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptDeadCodeCheck(
            {"ignore_dependencies": ["@jest/globals", "geojson"]}
        )
        captured_configs = []

        def fake_run(cmd, **_kwargs):
            cfg_path = tmp_path / "_sm_knip.json"
            if cfg_path.exists():
                captured_configs.append(json.loads(cfg_path.read_text()))
            return self._make_result(success=True)

        with patch.object(check, "_run_command", side_effect=fake_run):
            check.run(str(tmp_path))

        assert captured_configs
        assert captured_configs[0]["ignoreDependencies"] == ["@jest/globals", "geojson"]

    def test_temp_config_merges_existing_knip_json(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "knip.json").write_text(
            '{"entry": ["index.ts"], "ignore": ["existing/**"]}'
        )
        check = JavaScriptDeadCodeCheck({"ignore_patterns": [".detoxrc.js"]})
        captured_configs = []

        def fake_run(cmd, **_kwargs):
            cfg_path = tmp_path / "_sm_knip.json"
            if cfg_path.exists():
                captured_configs.append(json.loads(cfg_path.read_text()))
            return self._make_result(success=True)

        with patch.object(check, "_run_command", side_effect=fake_run):
            check.run(str(tmp_path))

        assert captured_configs
        cfg = captured_configs[0]
        assert cfg.get("entry") == ["index.ts"]
        assert "existing/**" in cfg["ignore"]
        assert ".detoxrc.js" in cfg["ignore"]
        assert "extends" not in cfg

    def test_temp_config_merges_knip_jsonc(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "knip.jsonc").write_text('{"entry": ["src/index.ts"]}')
        check = JavaScriptDeadCodeCheck({"ignore_patterns": ["scripts/**"]})
        captured_configs = []

        def fake_run(cmd, **_kwargs):
            cfg_path = tmp_path / "_sm_knip.json"
            if cfg_path.exists():
                captured_configs.append(json.loads(cfg_path.read_text()))
            return self._make_result(success=True)

        with patch.object(check, "_run_command", side_effect=fake_run):
            check.run(str(tmp_path))

        assert captured_configs
        cfg = captured_configs[0]
        assert cfg.get("entry") == ["src/index.ts"]
        assert cfg["ignore"] == ["scripts/**"]
        assert "extends" not in cfg

    def test_temp_config_no_merge_when_no_knip_config(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptDeadCodeCheck({"ignore_patterns": [".detoxrc.js"]})
        captured_configs = []

        def fake_run(cmd, **_kwargs):
            cfg_path = tmp_path / "_sm_knip.json"
            if cfg_path.exists():
                captured_configs.append(json.loads(cfg_path.read_text()))
            return self._make_result(success=True)

        with patch.object(check, "_run_command", side_effect=fake_run):
            check.run(str(tmp_path))

        assert captured_configs
        cfg = captured_configs[0]
        assert cfg == {"ignore": [".detoxrc.js"]}
        assert "extends" not in cfg

    def test_knip_config_takes_precedence_over_ignore_fields(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "node_modules").mkdir()
        check = JavaScriptDeadCodeCheck(
            {
                "knip_config": "knip.json",
                "ignore_patterns": [".detoxrc.js"],
            }
        )
        captured = []

        def fake_run(cmd, **_kwargs):
            captured.append(cmd)
            return self._make_result(success=True)

        with patch.object(check, "_run_command", side_effect=fake_run):
            check.run(str(tmp_path))

        knip_cmd = next(c for c in captured if "knip" in " ".join(c))
        # Uses explicit knip_config, not the generated temp file
        assert "knip.json" in knip_cmd
        assert "_sm_knip.json" not in " ".join(knip_cmd)


class TestParseKnipOutput:
    def setup_method(self):
        self.check = JavaScriptDeadCodeCheck({})

    def test_empty_stdout_returns_empty(self):
        assert self.check._parse_knip_output("") == []

    def test_invalid_json_returns_empty(self):
        assert self.check._parse_knip_output("not json {{{") == []

    def test_non_list_json_returns_empty(self):
        # Dict without "issues" key falls back to empty list
        assert self.check._parse_knip_output('{"error": "bad"}') == []

    def test_knip_6_issues_envelope_format(self):
        # knip 5+/6+ wraps results in {"issues": [...]}
        data = {
            "issues": [
                {"file": "src/foo.ts", "exports": [{"name": "fn", "line": 1, "col": 1}]}
            ]
        }
        findings = self.check._parse_knip_output(json.dumps(data))
        assert len(findings) == 1
        assert "fn" in findings[0].message

    def test_knip_6_envelope_empty_issues(self):
        findings = self.check._parse_knip_output(json.dumps({"issues": []}))
        assert findings == []

    def test_unused_file_finding(self):
        data = [{"file": "src/dead.ts", "files": True}]
        findings = self.check._parse_knip_output(json.dumps(data))
        assert len(findings) == 1
        assert "dead.ts" in findings[0].message

    def test_unused_export_finding(self):
        data = [
            {
                "file": "src/foo.ts",
                "exports": [{"name": "myExport", "line": 10, "col": 5}],
            }
        ]
        findings = self.check._parse_knip_output(json.dumps(data))
        assert len(findings) == 1
        assert "myExport" in findings[0].message
        assert findings[0].line == 10
        assert findings[0].column == 5

    def test_unused_type_finding(self):
        data = [
            {"file": "src/bar.ts", "types": [{"name": "MyType", "line": 3, "col": 1}]}
        ]
        findings = self.check._parse_knip_output(json.dumps(data))
        assert len(findings) == 1
        assert "MyType" in findings[0].message

    def test_duplicate_exports_flattened(self):
        data = [
            {
                "file": "src/dup.ts",
                "duplicates": [
                    [
                        {"name": "A", "line": 1, "col": 1},
                        {"name": "B", "line": 2, "col": 1},
                    ]
                ],
            }
        ]
        findings = self.check._parse_knip_output(json.dumps(data))
        assert len(findings) == 2

    def test_enum_members_finding(self):
        data = [
            {
                "file": "src/enums.ts",
                "enumMembers": {
                    "MyEnum": [{"name": "UNUSED_VAL", "line": 7, "col": 3}]
                },
            }
        ]
        findings = self.check._parse_knip_output(json.dumps(data))
        assert len(findings) == 1
        assert "MyEnum.UNUSED_VAL" in findings[0].message

    def test_class_members_finding(self):
        data = [
            {
                "file": "src/cls.ts",
                "classMembers": {
                    "MyClass": [{"name": "unusedMethod", "line": 12, "col": 2}]
                },
            }
        ]
        findings = self.check._parse_knip_output(json.dumps(data))
        assert len(findings) == 1
        assert "MyClass.unusedMethod" in findings[0].message

    def test_multiple_issues_in_one_file(self):
        data = [
            {
                "file": "src/mixed.ts",
                "exports": [{"name": "fn1", "line": 1, "col": 1}],
                "types": [{"name": "T1", "line": 2, "col": 1}],
            }
        ]
        findings = self.check._parse_knip_output(json.dumps(data))
        assert len(findings) == 2

    def test_non_dict_entries_skipped(self):
        data = [
            "not a dict",
            None,
            {"file": "src/ok.ts", "exports": [{"name": "x", "line": 1, "col": 1}]},
        ]
        findings = self.check._parse_knip_output(json.dumps(data))
        assert len(findings) == 1
