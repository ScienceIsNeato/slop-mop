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
    def test_run_pyright_not_installed(self, mock_find, tmp_path):
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
    def test_run_success(self, mock_find, tmp_path):
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
    def test_run_with_errors(self, mock_find, tmp_path):
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
    def test_run_timeout(self, mock_find, tmp_path):
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
        from slopmop.checks.metadata import builtin_gate_why
        from slopmop.checks.python.static_analysis import PythonStaticAnalysisCheck

        check = PythonStaticAnalysisCheck({})
        assert check.why_it_matters == builtin_gate_why(
            "overconfidence:missing-annotations.py"
        )

    def test_type_blindness_uses_builtin_why_text(self):
        from slopmop.checks.metadata import builtin_gate_why
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        check = PythonTypeCheckingCheck({})
        assert check.why_it_matters == builtin_gate_why(
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
