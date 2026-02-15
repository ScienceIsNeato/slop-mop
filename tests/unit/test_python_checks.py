"""Tests for Python check implementations."""

from unittest.mock import MagicMock, patch

from slopmop.checks.python.coverage import PythonCoverageCheck
from slopmop.checks.python.lint_format import PythonLintFormatCheck
from slopmop.checks.python.static_analysis import PythonStaticAnalysisCheck
from slopmop.checks.python.tests import PythonTestsCheck
from slopmop.core.result import CheckStatus
from slopmop.subprocess.runner import SubprocessResult


class TestPythonLintFormatCheck:
    """Tests for PythonLintFormatCheck."""

    def test_name(self):
        """Test check name."""
        check = PythonLintFormatCheck({})
        assert check.name == "lint-format"

    def test_display_name(self):
        """Test check display name."""
        check = PythonLintFormatCheck({})
        assert "Lint" in check.display_name
        assert "Format" in check.display_name
        assert "black" in check.display_name

    def test_is_applicable_python_project(self, tmp_path):
        """Test is_applicable returns True for Python project."""
        (tmp_path / "setup.py").touch()
        check = PythonLintFormatCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_non_python(self, tmp_path):
        """Test is_applicable returns False for non-Python project."""
        (tmp_path / "package.json").touch()
        check = PythonLintFormatCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_can_auto_fix(self):
        """Test can_auto_fix returns True."""
        check = PythonLintFormatCheck({})
        assert check.can_auto_fix() is True

    def test_auto_fix_success(self, tmp_path):
        """Test auto_fix runs black and isort."""
        (tmp_path / "slopmop").mkdir()
        (tmp_path / "slopmop" / "__init__.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="", stderr="", duration=1.0
        )

        check = PythonLintFormatCheck({}, runner=mock_runner)
        result = check.auto_fix(str(tmp_path))

        assert result is True
        # Should have called black and isort
        assert mock_runner.run.call_count >= 2

    def test_run_success(self, tmp_path):
        """Test run with passing checks."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        mock_runner = MagicMock()
        # All checks pass
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="", stderr="", duration=1.0
        )

        check = PythonLintFormatCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_black_fails(self, tmp_path):
        """Test run when black fails."""
        (tmp_path / "test.py").touch()

        mock_runner = MagicMock()
        # Black fails on format check
        mock_runner.run.return_value = SubprocessResult(
            returncode=1, stdout="would reformat test.py", stderr="", duration=1.0
        )

        check = PythonLintFormatCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED

    def test_get_python_targets_excludes_special_dirs(self, tmp_path):
        """Test _get_python_targets excludes venv, .git, etc."""
        # Create excluded directories
        (tmp_path / "venv").mkdir()
        (tmp_path / "venv" / "__init__.py").touch()
        (tmp_path / ".hidden").mkdir()
        (tmp_path / ".hidden" / "__init__.py").touch()
        (tmp_path / "node_modules").mkdir()

        # Create valid target
        (tmp_path / "mypackage").mkdir()
        (tmp_path / "mypackage" / "__init__.py").touch()

        check = PythonLintFormatCheck({})
        targets = check._get_python_targets(str(tmp_path))

        assert "mypackage" in targets
        assert "venv" not in targets
        assert ".hidden" not in targets
        assert "node_modules" not in targets

    def test_get_python_targets_includes_standard_dirs(self, tmp_path):
        """Test _get_python_targets includes src, tests, lib dirs."""
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()

        check = PythonLintFormatCheck({})
        targets = check._get_python_targets(str(tmp_path))

        assert "src" in targets
        assert "tests" in targets

    def test_auto_fix_falls_back_to_current_dir(self, tmp_path):
        """Test auto_fix uses '.' when no targets found."""
        # Empty directory
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="", stderr="", duration=1.0
        )

        check = PythonLintFormatCheck({}, runner=mock_runner)
        result = check.auto_fix(str(tmp_path))

        assert result is True

    def test_check_black_no_targets(self, tmp_path):
        """Test _check_black returns None when no targets."""
        # Empty directory
        check = PythonLintFormatCheck({})
        result = check._check_black(str(tmp_path))

        assert result is None

    def test_check_black_fails_returns_actual_output(self, tmp_path):
        """Test _check_black returns actual black output on failure."""
        (tmp_path / "test.py").touch()

        mock_runner = MagicMock()
        # Black fails with an error message
        mock_runner.run.return_value = SubprocessResult(
            returncode=1, stdout="oh no an error occurred", stderr="", duration=1.0
        )

        check = PythonLintFormatCheck({}, runner=mock_runner)
        result = check._check_black(str(tmp_path))

        # Returns actual output from black
        assert result == "oh no an error occurred"

    def test_check_black_fails_returns_raw_file_paths(self, tmp_path):
        """Test _check_black returns raw black output including file paths."""
        (tmp_path / "test.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1,
            stdout="would reformat src/foo.py\nwould reformat src/bar.py",
            stderr="",
            duration=1.0,
        )

        check = PythonLintFormatCheck({}, runner=mock_runner)
        result = check._check_black(str(tmp_path))

        assert result is not None
        # Returns raw black output
        assert "would reformat src/foo.py" in result
        assert "src/bar.py" in result

    def test_check_black_fails_returns_all_output(self, tmp_path):
        """Test _check_black returns all black output without artificial truncation."""
        (tmp_path / "test.py").touch()

        files = [f"would reformat file{i}.py" for i in range(8)]
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1,
            stdout="\n".join(files),
            stderr="",
            duration=1.0,
        )

        check = PythonLintFormatCheck({}, runner=mock_runner)
        result = check._check_black(str(tmp_path))

        assert result is not None
        # Returns raw output - all files included (reporter handles truncation)
        assert "file0.py" in result
        assert "file4.py" in result
        assert "file7.py" in result  # All files returned, not truncated here

    def test_check_isort_fails_shows_file_paths(self, tmp_path):
        """Test _check_isort shows actual file paths when isort fails."""
        (tmp_path / "test.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1,
            stdout="ERROR: src/foo.py Imports are incorrectly sorted",
            stderr="",
            duration=1.0,
        )

        check = PythonLintFormatCheck({}, runner=mock_runner)
        result = check._check_isort(str(tmp_path))

        assert result is not None
        assert "Import order issues:" in result
        assert "src/foo.py" in result

    def test_check_isort_fails_truncates_many_files(self, tmp_path):
        """Test _check_isort truncates list when >5 files have issues."""
        (tmp_path / "test.py").touch()

        errors = [f"ERROR: file{i}.py Imports are incorrectly sorted" for i in range(8)]
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1,
            stdout="\n".join(errors),
            stderr="",
            duration=1.0,
        )

        check = PythonLintFormatCheck({}, runner=mock_runner)
        result = check._check_isort(str(tmp_path))

        assert result is not None
        assert "Import order issues:" in result
        assert "file0.py" in result
        assert "file4.py" in result
        assert "file5.py" not in result  # Should be truncated
        assert "... and 3 more" in result

    def test_check_isort_fails_no_error_lines(self, tmp_path):
        """Test _check_isort returns generic message when no ERROR: lines."""
        (tmp_path / "test.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1,
            stdout="Something went wrong",
            stderr="",
            duration=1.0,
        )

        check = PythonLintFormatCheck({}, runner=mock_runner)
        result = check._check_isort(str(tmp_path))

        assert result == "Import order issues found"


class TestPythonTestsCheck:
    """Tests for PythonTestsCheck."""

    def test_name(self):
        """Test check name."""
        check = PythonTestsCheck({})
        assert check.name == "tests"

    def test_display_name(self):
        """Test check display name."""
        check = PythonTestsCheck({})
        assert "Tests" in check.display_name or "test" in check.display_name.lower()

    def test_is_applicable_python_project(self, tmp_path):
        """Test is_applicable returns True for Python project with test files."""
        (tmp_path / "pyproject.toml").touch()
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_example.py").write_text("def test_one(): pass")
        check = PythonTestsCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_depends_on(self):
        """Test check dependencies."""
        check = PythonTestsCheck({})
        # Tests depend on lint-format being run first
        assert "python:lint-format" in check.depends_on

    def test_run_success(self, tmp_path):
        """Test run with passing tests."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="10 passed in 0.5s", stderr="", duration=1.0
        )

        check = PythonTestsCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_tests_fail(self, tmp_path):
        """Test run when tests fail."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1,
            stdout="FAILED tests/test_foo.py::test_bar - AssertionError",
            stderr="",
            duration=1.0,
        )

        check = PythonTestsCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED

    def test_run_coverage_fail_only(self, tmp_path):
        """Test run passes when only coverage fails (not tests)."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1,
            stdout="10 passed\nFail Required test coverage of 80%",
            stderr="",
            duration=1.0,
        )

        check = PythonTestsCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        # Should pass because tests passed, only coverage failed
        assert result.status == CheckStatus.PASSED


class TestPythonCoverageCheck:
    """Tests for PythonCoverageCheck."""

    def test_name(self):
        """Test check name."""
        check = PythonCoverageCheck({})
        assert check.name == "coverage"

    def test_display_name(self):
        """Test check display name."""
        check = PythonCoverageCheck({})
        assert "Coverage" in check.display_name

    def test_depends_on(self):
        """Test check dependencies."""
        check = PythonCoverageCheck({})
        assert "python:tests" in check.depends_on

    def test_is_applicable_python_project(self, tmp_path):
        """Test is_applicable returns True for Python project with tests."""
        (tmp_path / "requirements.txt").touch()
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_example.py").write_text("def test_one(): pass")
        check = PythonCoverageCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_run_coverage_above_threshold(self, tmp_path):
        """Test run when coverage is above threshold."""
        # Create coverage.xml file
        (tmp_path / "coverage.xml").write_text("<coverage></coverage>")

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="TOTAL    1000    100    90%", stderr="", duration=1.0
        )

        check = PythonCoverageCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_coverage_below_threshold(self, tmp_path):
        """Test run when coverage is below threshold."""
        # Create coverage.xml file
        (tmp_path / "coverage.xml").write_text("<coverage></coverage>")

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="TOTAL    1000    500    50%", stderr="", duration=1.0
        )

        check = PythonCoverageCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED

    def test_run_no_coverage_data(self, tmp_path):
        """Test run when no coverage data exists."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1, stdout="No data to report", stderr="", duration=1.0
        )

        check = PythonCoverageCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED


class TestPythonStaticAnalysisCheck:
    """Tests for PythonStaticAnalysisCheck."""

    def test_name(self):
        """Test check name."""
        check = PythonStaticAnalysisCheck({})
        assert check.name == "static-analysis"

    def test_display_name_strict(self):
        """Test display name shows strict when enabled (default)."""
        check = PythonStaticAnalysisCheck({})
        assert "strict" in check.display_name
        assert "mypy" in check.display_name

    def test_display_name_basic(self):
        """Test display name shows basic when strict disabled."""
        check = PythonStaticAnalysisCheck({"strict_typing": False})
        assert "basic" in check.display_name
        assert "mypy" in check.display_name

    def test_config_schema_has_strict_typing(self):
        """Test config schema includes strict_typing field."""
        check = PythonStaticAnalysisCheck({})
        field_names = [f.name for f in check.config_schema]
        assert "strict_typing" in field_names

    def test_strict_typing_default_on(self):
        """Test strict_typing defaults to True."""
        check = PythonStaticAnalysisCheck({})
        assert check._is_strict() is True

    def test_strict_typing_configurable(self):
        """Test strict_typing can be disabled."""
        check = PythonStaticAnalysisCheck({"strict_typing": False})
        assert check._is_strict() is False

    def test_depends_on(self):
        """Test check dependencies."""
        check = PythonStaticAnalysisCheck({})
        assert "python:lint-format" in check.depends_on

    def test_is_applicable_python_project(self, tmp_path):
        """Test is_applicable returns True for Python project with source dirs."""
        (tmp_path / "main.py").touch()
        pkg = tmp_path / "mypackage"
        pkg.mkdir()
        (pkg / "__init__.py").touch()
        (pkg / "core.py").write_text("x = 1")
        check = PythonStaticAnalysisCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    # --- Command building ---

    def test_build_command_strict(self, tmp_path):
        """Test command includes strict flags by default."""
        check = PythonStaticAnalysisCheck({})
        cmd = check._build_command(["src"])
        assert "--disallow-untyped-defs" in cmd
        assert "--disallow-any-generics" in cmd
        assert "--ignore-missing-imports" in cmd

    def test_build_command_basic(self, tmp_path):
        """Test command excludes strict flags when disabled."""
        check = PythonStaticAnalysisCheck({"strict_typing": False})
        cmd = check._build_command(["src"])
        assert "--disallow-untyped-defs" not in cmd
        assert "--disallow-any-generics" not in cmd
        assert "--ignore-missing-imports" in cmd

    # --- Source directory detection ---

    def test_detect_source_dirs_standard(self, tmp_path):
        """Test detecting standard source directories."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("x = 1")
        check = PythonStaticAnalysisCheck({})
        dirs = check._detect_source_dirs(str(tmp_path))
        assert "src" in dirs

    def test_detect_source_dirs_fallback(self, tmp_path):
        """Test fallback to '.' when no source dirs found."""
        check = PythonStaticAnalysisCheck({})
        dirs = check._detect_source_dirs(str(tmp_path))
        assert dirs == ["."]

    def test_detect_source_dirs_python_package(self, tmp_path):
        """Test detecting Python packages."""
        (tmp_path / "mypackage").mkdir()
        (tmp_path / "mypackage" / "__init__.py").touch()
        check = PythonStaticAnalysisCheck({})
        dirs = check._detect_source_dirs(str(tmp_path))
        assert "mypackage" in dirs

    def test_detect_source_dirs_skips_dir_without_python_files(self, tmp_path):
        """Test that src/ is skipped when it contains no .py files (mixed-lang project)."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "App.tsx").write_text("export default function App() {}")
        (src / "index.ts").write_text("import App from './App'")
        check = PythonStaticAnalysisCheck({})
        dirs = check._detect_source_dirs(str(tmp_path))
        assert "src" not in dirs

    def test_detect_source_dirs_uses_config_include_dirs(self, tmp_path):
        """Test that include_dirs from config takes priority over heuristic."""
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "deploy.py").write_text("x = 1")
        check = PythonStaticAnalysisCheck({"include_dirs": ["scripts"]})
        dirs = check._detect_source_dirs(str(tmp_path))
        assert dirs == ["scripts"]

    def test_is_applicable_with_config_dot_include_dir(self, tmp_path):
        """include_dirs: ['.'] from config should NOT silently skip the check.

        Regression: is_applicable() used `source_dirs != ['.']` to detect
        heuristic fallback, but this also matched when the user explicitly
        configured `include_dirs: ['.']`, causing a silent skip.
        """
        (tmp_path / "setup.py").write_text("x = 1")
        check = PythonStaticAnalysisCheck({"include_dirs": ["."]})
        assert check.is_applicable(str(tmp_path)) is True

    def test_detect_source_dirs_ignores_non_list_include_dirs(self, tmp_path):
        """Test that a string include_dirs value doesn't unpack into characters."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("x = 1")
        # String value should be ignored, falling back to heuristic
        check = PythonStaticAnalysisCheck({"include_dirs": "src"})
        dirs = check._detect_source_dirs(str(tmp_path))
        # Should find src via heuristic, not via the string config
        assert dirs == ["src"]
        # Crucially, should NOT be ["s", "r", "c"]
        assert len(dirs) == 1

    # --- Output dedup ---

    def test_dedup_output_strips_notes(self):
        """Test dedup removes note lines."""
        raw = (
            "foo.py:10: error: Missing return  [no-untyped-def]\n"
            "foo.py:10: note: Use -> None if function does not return\n"
            "Found 1 error in 1 file (checked 5 source files)\n"
        )
        errors, codes = PythonStaticAnalysisCheck._dedup_output(raw)
        assert len(errors) == 1
        assert "note:" not in errors[0]
        assert codes == {"no-untyped-def": 1}

    def test_dedup_output_counts_by_code(self):
        """Test dedup groups errors by code."""
        raw = (
            "a.py:1: error: Missing type  [type-arg]\n"
            "b.py:2: error: Missing type  [type-arg]\n"
            "c.py:3: error: Missing return  [no-untyped-def]\n"
        )
        errors, codes = PythonStaticAnalysisCheck._dedup_output(raw)
        assert len(errors) == 3
        assert codes == {"type-arg": 2, "no-untyped-def": 1}

    def test_dedup_output_skips_summary_line(self):
        """Test dedup strips mypy's own summary line."""
        raw = (
            "a.py:1: error: Bad  [type-arg]\n"
            "Found 1 error in 1 file (checked 5 source files)\n"
        )
        errors, _ = PythonStaticAnalysisCheck._dedup_output(raw)
        assert len(errors) == 1
        assert not any("Found " in e for e in errors)

    # --- Output formatting ---

    def test_format_summary_capped(self):
        """Test format_summary caps output at 20 errors."""
        errors = [f"f{i}.py:{i}: error: Bad  [type-arg]" for i in range(25)]
        codes = {"type-arg": 25}
        output = PythonStaticAnalysisCheck._format_summary(errors, codes)
        assert "... and 5 more" in output
        assert "25 type error(s)" in output

    def test_format_summary_breakdown(self):
        """Test format_summary includes code breakdown."""
        errors = ["a.py:1: error: Bad  [type-arg]"]
        codes = {"type-arg": 2, "no-untyped-def": 1}
        output = PythonStaticAnalysisCheck._format_summary(errors, codes)
        assert "3 type error(s)" in output
        assert "[no-untyped-def]" in output
        assert "[type-arg]" in output

    # --- Run integration ---

    def test_run_success(self, tmp_path):
        """Test run with no type errors."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="Success: no issues found", stderr="", duration=1.0
        )

        check = PythonStaticAnalysisCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_type_errors(self, tmp_path):
        """Test run with type errors."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1,
            stdout=(
                "src/main.py:10: error: Incompatible types  [assignment]\n"
                "Found 1 error in 1 file (checked 5 source files)\n"
            ),
            stderr="",
            duration=1.0,
        )

        check = PythonStaticAnalysisCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "1 type error(s)" in result.error

    def test_run_type_arg_errors_include_fix_suggestion(self, tmp_path):
        """Test fix_suggestion mentions type-arg when present."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1,
            stdout='src/main.py:5: error: Missing type params for generic "Dict"  [type-arg]\n',
            stderr="",
            duration=1.0,
        )

        check = PythonStaticAnalysisCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "type-arg" in result.fix_suggestion
        assert "Dict[str, Any]" in result.fix_suggestion

    def test_run_strict_includes_flags_in_command(self, tmp_path):
        """Test that strict mode passes the right flags to mypy."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="Success: no issues found", stderr="", duration=1.0
        )

        check = PythonStaticAnalysisCheck({}, runner=mock_runner)
        check.run(str(tmp_path))

        call_args = mock_runner.run.call_args[0][0]
        assert "--disallow-untyped-defs" in call_args
        assert "--disallow-any-generics" in call_args

    def test_run_basic_omits_strict_flags(self, tmp_path):
        """Test that basic mode omits strict flags."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="Success: no issues found", stderr="", duration=1.0
        )

        check = PythonStaticAnalysisCheck({"strict_typing": False}, runner=mock_runner)
        check.run(str(tmp_path))

        call_args = mock_runner.run.call_args[0][0]
        assert "--disallow-untyped-defs" not in call_args
        assert "--disallow-any-generics" not in call_args

    def test_run_timeout(self, tmp_path):
        """Test run handles timeout."""
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

        check = PythonStaticAnalysisCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "timed out" in result.error.lower()


class TestPythonTypeCheckingCheck:
    """Tests for PythonTypeCheckingCheck (pyright type-completeness)."""

    def test_name(self):
        """Test check name."""
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        check = PythonTypeCheckingCheck({})
        assert check.name == "type-checking"

    def test_display_name(self):
        """Test check display name."""
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        check = PythonTypeCheckingCheck({})
        assert "Type" in check.display_name
        assert "pyright" in check.display_name

    def test_is_applicable_python_project(self, tmp_path):
        """Test is_applicable returns True for Python project."""
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "setup.py").touch()
        check = PythonTypeCheckingCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_non_python(self, tmp_path):
        """Test is_applicable returns False for non-Python project."""
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "package.json").touch()
        check = PythonTypeCheckingCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_skip_reason_delegates_to_mixin(self, tmp_path):
        """Test skip_reason returns PythonCheckMixin's skip reason."""
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        # No Python files or markers
        check = PythonTypeCheckingCheck({})
        reason = check.skip_reason(str(tmp_path))
        assert "Python" in reason or "python" in reason.lower()

    @patch(
        "slopmop.checks.python.type_checking._find_pyright",
        return_value=None,
    )
    def test_run_pyright_not_installed(self, mock_find, tmp_path):
        """Test run handles missing pyright."""
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
        """Test run with clean pyright output."""
        import json

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
        """Test run with pyright type errors."""
        import json

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

    @patch(
        "slopmop.checks.python.type_checking._find_pyright",
        return_value="/usr/bin/pyright",
    )
    def test_run_timeout(self, mock_find, tmp_path):
        """Test run handles timeout."""
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
        """Test _build_pyright_config generates correct config."""
        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        check = PythonTypeCheckingCheck({})
        config = check._build_pyright_config(str(tmp_path))

        assert "include" in config
        assert "pythonVersion" in config
        assert config["typeCheckingMode"] == "standard"

    def test_build_pyright_config_strict_mode(self, tmp_path):
        """Test _build_pyright_config includes type-completeness rules in strict mode."""
        from slopmop.checks.python.type_checking import (
            TYPE_COMPLETENESS_RULES,
            PythonTypeCheckingCheck,
        )

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        check = PythonTypeCheckingCheck({"strict": True})
        config = check._build_pyright_config(str(tmp_path))

        # Should include type-completeness rules
        for rule in TYPE_COMPLETENESS_RULES:
            assert rule in config

    def test_preserves_existing_pyrightconfig(self, tmp_path):
        """Test run backs up and restores existing pyrightconfig.json."""
        import json

        from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        # Create existing config
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

        check = PythonTypeCheckingCheck({}, runner=mock_runner)
        check.run(str(tmp_path))

        # Original config should be restored
        assert config_path.exists()
        restored = json.loads(config_path.read_text())
        assert restored == existing_config
