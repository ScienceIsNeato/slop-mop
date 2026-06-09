"""Type-checking-specific tests split out from test_python_checks.py."""

import json
from unittest.mock import MagicMock, patch

from slopmop.core.result import CheckStatus
from slopmop.subprocess.runner import SubprocessResult


class TestPythonTypeCheckingCheck:
    """Tests for PythonTypeCheckingCheck (pyright type-completeness)."""

    def test_name(self):
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        check = PythonTypeCheckingCheck({})
        assert check.name == "type-blindness.py"

    def test_display_name(self):
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        check = PythonTypeCheckingCheck({})
        assert "Type" in check.display_name
        assert "pyright" in check.display_name

    def test_init_config_discovers_existing_pyrightconfig(self, tmp_path):
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "pyrightconfig.json").write_text("{}")

        check = PythonTypeCheckingCheck({})
        assert check.init_config(str(tmp_path)) == {
            "pyright_config_file": "pyrightconfig.json"
        }

    def test_is_applicable_python_project(self, tmp_path):
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "setup.py").touch()
        check = PythonTypeCheckingCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_non_python(self, tmp_path):
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "package.json").touch()
        check = PythonTypeCheckingCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_skip_reason_delegates_to_mixin(self, tmp_path):
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        check = PythonTypeCheckingCheck({})
        reason = check.skip_reason(str(tmp_path))
        assert "Python" in reason or "python" in reason.lower()

    @patch(
        "slopmop.checks.python.type_checking._find_pyright",
        return_value=None,
    )
    def test_run_pyright_not_installed(self, _mock_find, tmp_path):
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        check = PythonTypeCheckingCheck({})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.WARNED
        assert "pyright" in result.error.lower()

    @patch(
        "slopmop.checks.python.type_checking._find_pyright",
        return_value="/usr/bin/pyright",
    )
    def test_run_success(self, _mock_find, tmp_path):
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        success_output = json.dumps(
            {
                "generalDiagnostics": [],
                "summary": {"errorCount": 0, "filesAnalyzed": 5},
            }
        )

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout=success_output, stderr="", duration=1.0
        )

        check = PythonTypeCheckingCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert "5 files" in result.output

    @patch(
        "slopmop.checks.python.type_checking._find_pyright",
        return_value="/usr/bin/pyright",
    )
    def test_run_with_errors(self, _mock_find, tmp_path):
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        error_output = json.dumps(
            {
                "generalDiagnostics": [
                    {
                        "file": "src/app.py",
                        "severity": 1,
                        "message": 'Type of "x" is "Unknown"',
                        "rule": "reportUnknownVariableType",
                        "range": {"start": {"line": 10, "character": 0}},
                    }
                ],
                "summary": {"errorCount": 1, "filesAnalyzed": 3},
            }
        )

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1, stdout=error_output, stderr="", duration=1.0
        )

        check = PythonTypeCheckingCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "1 type-completeness error" in result.error
        assert result.fix_suggestion is not None
        assert result.why_it_matters is not None
        assert result.findings
        assert result.findings[0].fix_strategy is not None

    @patch(
        "slopmop.checks.python.type_checking._find_pyright",
        return_value="/usr/bin/pyright",
    )
    def test_run_timeout(self, _mock_find, tmp_path):
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=-1,
            stdout="",
            stderr="",
            duration=120.0,
            timed_out=True,
        )

        check = PythonTypeCheckingCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "timed out" in result.error.lower()

    def test_build_pyright_config(self, tmp_path):
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        check = PythonTypeCheckingCheck({})
        config = check._build_pyright_config(str(tmp_path))

        assert "include" in config
        assert "pythonVersion" in config
        assert config["typeCheckingMode"] == "standard"

    def test_build_pyright_config_extends_project_config(self, tmp_path):
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()
        (tmp_path / "venv").mkdir()

        check = PythonTypeCheckingCheck({"pyright_config_file": "pyrightconfig.json"})
        config = check._build_pyright_config(str(tmp_path))

        assert config["extends"] == "pyrightconfig.json"
        assert "include" not in config
        assert config["venvPath"] == str(tmp_path)
        assert config["venv"] == "venv"
        assert "pythonVersion" not in config

    def test_build_pyright_config_prefers_explicit_include_dirs(self, tmp_path):
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "worker.py").write_text("x = 1\n")

        check = PythonTypeCheckingCheck({"include_dirs": ["scripts"]})
        config = check._build_pyright_config(str(tmp_path))

        assert config["include"] == ["scripts"]

    def test_build_pyright_config_extends_project_config_with_explicit_include_dirs(
        self, tmp_path
    ):
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "worker.py").write_text("x = 1\n")
        (tmp_path / ".venv").mkdir()

        check = PythonTypeCheckingCheck(
            {
                "pyright_config_file": "pyrightconfig.json",
                "include_dirs": ["scripts"],
            }
        )
        config = check._build_pyright_config(str(tmp_path))

        assert config["extends"] == "pyrightconfig.json"
        assert config["include"] == ["scripts"]
        assert config["venvPath"] == str(tmp_path)
        assert config["venv"] == ".venv"

    def test_missing_annotations_uses_builtin_why_text(self):
        from slopmop.checks.metadata import builtin_gate_rationale
        from slopmop.checks.python.static_analysis import PythonStaticAnalysisCheck

        check = PythonStaticAnalysisCheck({})
        assert check.why_it_matters == builtin_gate_rationale(
            "overconfidence:missing-annotations.py"
        )

    def test_type_blindness_uses_builtin_why_text(self):
        from slopmop.checks.metadata import builtin_gate_rationale
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        check = PythonTypeCheckingCheck({})
        assert check.why_it_matters == builtin_gate_rationale(
            "overconfidence:type-blindness.py"
        )

    def test_build_pyright_config_strict_mode(self, tmp_path):
        from slopmop.checks.python.type_checking import (
            TYPE_COMPLETENESS_RULES,
            PythonTypeCheckingCheck,
        )

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        check = PythonTypeCheckingCheck({"strict": True})
        config = check._build_pyright_config(str(tmp_path))

        for rule in TYPE_COMPLETENESS_RULES:
            assert rule in config

    def test_strict_honors_project_rule_override(self, tmp_path):
        """A rule the project sets in pyrightconfig.json is not re-forced (#245)."""
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()
        (tmp_path / "pyrightconfig.json").write_text(
            json.dumps({"reportUnknownMemberType": "none"})
        )

        check = PythonTypeCheckingCheck({"strict": True})
        config = check._build_pyright_config(str(tmp_path))

        # Auto-detected project config is extended...
        assert config["extends"] == "pyrightconfig.json"
        # ...and the project's suppression is preserved explicitly, so a later
        # typeCheckingMode: standard can't silently reset it (#245).
        assert config["reportUnknownMemberType"] == "none"
        # Rules the project did NOT set are still enforced.
        assert config["reportUnknownVariableType"] == "error"
        assert config["reportUnknownArgumentType"] == "error"

    def test_per_path_override_keeps_global_enforcement(self, tmp_path):
        """A per-path override must NOT drop the rule globally (#245).

        pyright applies executionEnvironments settings on top of the top-level
        one, so the gate still forces the rule to error globally and the
        project's scoped "none" wins only for its root. Counting the per-path
        entry as global ownership would leave the rule unenforced everywhere
        (standard mode defaults reportUnknown* off).
        """
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()
        (tmp_path / "pyrightconfig.json").write_text(
            json.dumps(
                {
                    "executionEnvironments": [
                        {"root": "src", "reportUnknownArgumentType": "none"}
                    ]
                }
            )
        )

        check = PythonTypeCheckingCheck({"strict": True})
        config = check._build_pyright_config(str(tmp_path))

        # Still enforced globally; the per-path "none" (from the extended
        # config) applies only to its root.
        assert config["reportUnknownArgumentType"] == "error"
        assert config["reportUnknownMemberType"] == "error"

    def test_strict_honors_override_in_jsonc_config(self, tmp_path):
        """A JSONC pyrightconfig (comments + trailing comma) still parses (#245).

        Regression: stripping only // line comments left /* */ blocks and
        trailing commas, so json.loads failed, owned_rules emptied, and every
        rule was forced back to error — silently defeating the fix.
        """
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()
        # Includes glob patterns (src/**, packages/*/dist) whose /* and */ would
        # fool a regex comment-stripper into eating the rule key between them,
        # plus a // inside a string value, a block comment, and a trailing comma.
        (tmp_path / "pyrightconfig.json").write_text(
            "{\n"
            "  /* untyped deps live upstream */\n"
            '  "include": ["src/**"],\n'
            '  "docs": "see http://example.com/style",\n'
            '  "reportUnknownMemberType": "none", // scoped out on purpose\n'
            '  "executionEnvironments": [{"root": "packages/*/dist"}],\n'
            "}\n"
        )

        check = PythonTypeCheckingCheck({"strict": True})
        config = check._build_pyright_config(str(tmp_path))

        assert config["reportUnknownMemberType"] == "none"
        assert config["reportUnknownVariableType"] == "error"

    def test_strict_forces_all_rules_without_project_config(self, tmp_path):
        """With no project pyright config, all completeness rules are enforced."""
        from slopmop.checks.python.type_checking import (
            TYPE_COMPLETENESS_RULES,
            PythonTypeCheckingCheck,
        )

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        check = PythonTypeCheckingCheck({"strict": True})
        config = check._build_pyright_config(str(tmp_path))

        for rule in TYPE_COMPLETENESS_RULES:
            assert config[rule] == "error"

    # --- barnacle #262: venv-sweep via include:["."] ---

    def test_fallback_include_dot_gets_broad_excludes(self, tmp_path):
        """When no source dirs are detected the config gets comprehensive excludes.

        Previously include:['.'] + exclude:['**/__pycache__','**/node_modules']
        allowed pyright to crawl venv/lib/python3.x/site-packages and any
        other non-source tree in the checkout. (#262)
        """
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        # No src/, slopmop/, lib/, app/, and no __init__.py at root → fallback
        check = PythonTypeCheckingCheck({})
        config = check._build_pyright_config(str(tmp_path))

        assert config["include"] == ["."]
        exclude = config["exclude"]
        assert "venv" in exclude
        assert ".venv" in exclude
        assert "build" in exclude
        assert "dist" in exclude
        assert "**/__pycache__" in exclude

    def test_detected_venv_name_appended_to_excludes(self, tmp_path):
        """Non-standard venv name is appended to excludes even if not in defaults."""
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        # Create a venv with a non-standard name — _detect_venv_path won't find
        # it (only checks 'venv' and '.venv') so it won't be in BROAD_SCAN_EXCLUDES.
        # But when it IS detected (via VIRTUAL_ENV env var) it should be appended.
        import os
        import unittest.mock as mock

        myenv = tmp_path / "myenv"
        myenv.mkdir()
        (myenv / "bin").mkdir()
        (myenv / "bin" / "python").write_text("#!/bin/false\n")

        check = PythonTypeCheckingCheck({})

        # Simulate VIRTUAL_ENV pointing at a non-standard name
        with mock.patch.dict(os.environ, {"VIRTUAL_ENV": str(myenv)}):
            config = check._build_pyright_config(str(tmp_path))

        exclude = config["exclude"]
        assert "myenv" in exclude

    def test_scoped_include_also_gets_broad_excludes(self, tmp_path):
        """Even when source dirs are found, the exclude list is comprehensive."""
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        check = PythonTypeCheckingCheck({})
        config = check._build_pyright_config(str(tmp_path))

        assert config["include"] == ["src"]
        # Comprehensive excludes still present — belt-and-suspenders
        assert "venv" in config["exclude"]
        assert ".venv" in config["exclude"]

    def test_extends_with_fallback_include_gets_broad_excludes(self, tmp_path):
        """Extends branch: auto-detected config without 'include' gets broad excludes
        when the fallback kicks in. (#262)
        """
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        # pyrightconfig.json exists but has no 'include' key — so the gate
        # sets include:["."] to scope the run; it must also set broad excludes.
        (tmp_path / "pyrightconfig.json").write_text("{}")
        # No src dirs → fallback include ["."]
        check = PythonTypeCheckingCheck({})
        config = check._build_pyright_config(str(tmp_path))

        assert config["extends"] == "pyrightconfig.json"
        assert config["include"] == ["."]
        exclude = config["exclude"]
        assert "venv" in exclude
        assert ".venv" in exclude
        assert "build" in exclude

    def test_extends_with_explicit_include_no_extra_excludes_forced(self, tmp_path):
        """Extends branch with explicitly configured include_dirs: no override needed."""
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "pyrightconfig.json").write_text("{}")
        (tmp_path / "myapp").mkdir()

        check = PythonTypeCheckingCheck(
            {"pyright_config_file": "pyrightconfig.json", "include_dirs": ["myapp"]}
        )
        config = check._build_pyright_config(str(tmp_path))

        assert config["include"] == ["myapp"]
        # No gate-injected exclude when user already scoped to a dir
        assert "exclude" not in config

    def test_run_uses_generated_overlay_without_mutating_pyrightconfig(self, tmp_path):
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        existing_config = {"typeCheckingMode": "basic", "custom": True}
        config_path = tmp_path / "pyrightconfig.json"
        config_path.write_text(json.dumps(existing_config))

        success_output = json.dumps(
            {
                "generalDiagnostics": [],
                "summary": {"errorCount": 0, "filesAnalyzed": 1},
            }
        )

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout=success_output, stderr="", duration=1.0
        )

        check = PythonTypeCheckingCheck(
            {"pyright_config_file": "pyrightconfig.json"}, runner=mock_runner
        )
        check.run(str(tmp_path))

        command = mock_runner.run.call_args.args[0]
        assert "--project" in command
        assert any(".pyrightconfig.generated.json" in str(part) for part in command)

        assert config_path.exists()
        restored = json.loads(config_path.read_text())
        assert restored == existing_config

        generated = tmp_path / ".pyrightconfig.generated.json"
        assert not generated.exists()
