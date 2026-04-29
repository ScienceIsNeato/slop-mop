"""Tests for Python check implementations."""

from unittest.mock import MagicMock, patch

from slopmop.checks.python.coverage import (
    PythonCoverageCheck,
    PythonDiffCoverageCheck,
    _build_diff_coverage_findings,
    _characterise_block,
    _compact_line_ranges,
    _compute_diff_coverage,
    _DiffCoverageReport,
    _FileDiffCov,
    _first_range,
    _format_diff_coverage_output,
    _get_compare_branch,
    _parse_coverage_xml_lines,
    _parse_unified_diff,
    _resolve_uncovered_range,
    _test_file_for,
)
from slopmop.checks.python.static_analysis import PythonStaticAnalysisCheck
from slopmop.checks.python.tests import (
    PythonTestsCheck,
    _is_failed_summary_line,
    _parse_failed_lines,
)
from slopmop.core.result import CheckStatus
from slopmop.subprocess.runner import SubprocessResult


class TestPythonProjectVenvWarning:
    def test_missing_project_venv_warns_locally_but_suppresses_sarif(self, tmp_path):
        check = PythonTestsCheck({})

        with patch.object(check, "has_project_venv", return_value=False):
            result = check.check_project_venv_or_warn(str(tmp_path), start_time=0.0)

        assert result is not None
        assert result.status == CheckStatus.WARNED
        assert result.error == "No project virtual environment found"
        assert result.suppress_sarif is True
        assert result.fix_suggestion is not None
        assert "Create a venv" in result.fix_suggestion


class TestPythonTestsCheck:
    """Tests for PythonTestsCheck."""

    def test_name(self):
        """Test check name."""
        check = PythonTestsCheck({})
        assert check.name == "untested-code.py"

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
        assert "laziness:sloppy-formatting.py" in check.depends_on

    def test_run_success(self, tmp_path):
        """Test run with passing tests."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_example.py").write_text(
            "def test_ok():\n    pass\n"
        )
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="10 passed in 0.5s", stderr="", duration=1.0
        )

        check = PythonTestsCheck({}, runner=mock_runner)
        # These tests exercise the post-venv-gate logic (how the check
        # interprets pytest output), but tmp_path has no venv.  The
        # runner is already mocked — the venv gate is incidental
        # plumbing, not the thing under test.  Without this patch the
        # test only passes when the developer's shell has VIRTUAL_ENV
        # set, which the mixin falls back to.  A clean env (no
        # activation, no project venv) short-circuits to WARNED before
        # the mocked runner is ever called.
        with patch.object(check, "check_project_venv_or_warn", return_value=None):
            with patch.object(check, "_testmon_available", return_value=True):
                result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_tests_fail(self, tmp_path):
        """Test run when tests fail."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_example.py").write_text(
            "def test_ok():\n    pass\n"
        )
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1,
            stdout="FAILED tests/test_foo.py::test_bar - AssertionError: expected 2, got 3",
            stderr="",
            duration=1.0,
        )

        check = PythonTestsCheck({}, runner=mock_runner)
        with patch.object(check, "check_project_venv_or_warn", return_value=None):
            with patch.object(check, "_testmon_available", return_value=True):
                result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert result.findings
        assert result.findings[0].fix_strategy is not None
        assert "AssertionError: expected 2, got 3" in result.findings[0].fix_strategy

    def test_run_coverage_fail_only(self, tmp_path):
        """Test run passes when only coverage fails (not tests)."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_example.py").write_text(
            "def test_ok():\n    pass\n"
        )
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1,
            stdout="10 passed\nFail Required test coverage of 80%",
            stderr="",
            duration=1.0,
        )

        check = PythonTestsCheck({}, runner=mock_runner)
        with patch.object(check, "check_project_venv_or_warn", return_value=None):
            with patch.object(check, "_testmon_available", return_value=True):
                result = check.run(str(tmp_path))

        # Should pass because tests passed, only coverage failed
        assert result.status == CheckStatus.PASSED

    def test_skip_reason_python_project_not_applicable_message(self, tmp_path):
        """Skip reason uses the generic applicable message for Python projects."""
        (tmp_path / "pyproject.toml").touch()
        check = PythonTestsCheck({})
        assert check.skip_reason(str(tmp_path)) == "Python tests check not applicable"

    def test_run_fails_when_no_python_tests_exist(self, tmp_path):
        """No test files should fail with explicit fix guidance."""
        (tmp_path / "pyproject.toml").touch()
        check = PythonTestsCheck({})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "No Python test files" in (result.error or "")
        assert result.fix_suggestion is not None

    def test_parse_failed_lines_ignores_embedded_failed_token(self):
        """Regex should not match when line doesn't start with FAILED."""
        lines = [
            "INFO: previous output FAILED tests/test_foo.py::test_bar - AssertionError"
        ]

        findings = _parse_failed_lines(lines)

        assert len(findings) == 1
        assert findings[0].fix_strategy is None

    def test_failed_summary_line_rejects_progress_output(self):
        """Progress lines like 'FAILED [ 31%]' are not short-summary failures."""
        assert (
            _is_failed_summary_line(
                "tests/unit/test_dashboard_service.py::test_foo FAILED [ 31%]"
            )
            is False
        )
        assert (
            _is_failed_summary_line(
                "FAILED tests/unit/test_dashboard_service.py::test_foo - AssertionError"
            )
            is True
        )

    def test_run_tests_fail_ignores_progress_markers(self, tmp_path):
        """Only short-summary FAILED lines should become findings."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_example.py").write_text(
            "def test_ok():\n    pass\n"
        )
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1,
            stdout=(
                "tests/unit/test_dashboard_service.py::test_foo FAILED [ 31%]\n"
                "FAILED tests/unit/test_dashboard_service.py::test_foo - "
                "AssertionError: expected 2, got 3"
            ),
            stderr="",
            duration=1.0,
        )

        check = PythonTestsCheck({}, runner=mock_runner)
        with patch.object(check, "check_project_venv_or_warn", return_value=None):
            with patch.object(check, "_testmon_available", return_value=True):
                result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert result.findings is not None
        assert len(result.findings) == 1
        assert result.findings[0].file == "tests/unit/test_dashboard_service.py"
        assert "test_foo failed" in result.findings[0].message
        assert "[ 31%]" not in (result.error or "")

    # ------------------------------------------------------------------
    # cache_inputs
    # ------------------------------------------------------------------

    def test_cache_inputs_returns_scoped_fingerprint(self, tmp_path):
        """cache_inputs returns a 64-char SHA-256 hex string (not None)."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_foo.py").write_text("def test_ok(): pass")
        check = PythonTestsCheck({})
        fp = check.cache_inputs(str(tmp_path))
        assert fp is not None
        assert isinstance(fp, str)
        assert len(fp) == 64

    def test_cache_inputs_stable_with_non_py_change(self, tmp_path):
        """cache_inputs fingerprint is stable when only non-Python files change."""
        (tmp_path / "main.py").write_text("x = 1")
        check = PythonTestsCheck({})
        fp1 = check.cache_inputs(str(tmp_path))
        (tmp_path / "config.yaml").write_text("key: value")
        (tmp_path / "README.md").write_text("# docs")
        fp2 = check.cache_inputs(str(tmp_path))
        assert fp1 == fp2

    def test_cache_inputs_changes_with_py_change(self, tmp_path):
        """cache_inputs fingerprint changes when a Python file is modified."""
        f = tmp_path / "main.py"
        f.write_text("x = 1")
        check = PythonTestsCheck({})
        fp1 = check.cache_inputs(str(tmp_path))
        f.write_text("x = 2")
        fp2 = check.cache_inputs(str(tmp_path))
        assert fp1 != fp2

    # ------------------------------------------------------------------
    # testmon fast path
    # ------------------------------------------------------------------

    def test_run_uses_testmon_when_available(self, tmp_path):
        """When testmon is installed and .testmondata+coverage.xml exist, use --testmon."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_example.py").write_text("def test_ok(): pass")
        (tmp_path / ".testmondata").touch()
        (tmp_path / "coverage.xml").write_text("<coverage></coverage>")

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="1 passed in 0.1s", stderr="", duration=0.1
        )

        check = PythonTestsCheck({}, runner=mock_runner)
        with patch.object(check, "check_project_venv_or_warn", return_value=None):
            with patch.object(check, "_testmon_available", return_value=True):
                result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        cmd = mock_runner.run.call_args[0][0]
        assert "--testmon" in cmd
        assert "--cov=." not in cmd

    def test_run_uses_full_path_when_no_testmondata(self, tmp_path):
        """When .testmondata is absent, fall back to full pytest with coverage."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_example.py").write_text("def test_ok(): pass")
        # No .testmondata — fast path should NOT activate

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="1 passed in 0.1s", stderr="", duration=1.0
        )

        check = PythonTestsCheck({}, runner=mock_runner)
        with patch.object(check, "check_project_venv_or_warn", return_value=None):
            with patch.object(check, "_testmon_available", return_value=True):
                result = check.run(str(tmp_path))

        cmd = mock_runner.run.call_args[0][0]
        assert "--cov=." in cmd
        assert "--testmon" not in cmd

    def test_run_uses_full_path_when_no_coverage_xml(self, tmp_path):
        """When coverage.xml is absent, fall back to full pytest run."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_example.py").write_text("def test_ok(): pass")
        (tmp_path / ".testmondata").touch()
        # No coverage.xml — fast path should NOT activate

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="1 passed in 0.1s", stderr="", duration=1.0
        )

        check = PythonTestsCheck({}, runner=mock_runner)
        with patch.object(check, "check_project_venv_or_warn", return_value=None):
            with patch.object(check, "_testmon_available", return_value=True):
                result = check.run(str(tmp_path))

        cmd = mock_runner.run.call_args[0][0]
        assert "--cov=." in cmd
        assert "--testmon" not in cmd

    def test_run_testmon_exit_5_is_pass(self, tmp_path):
        """pytest exit 5 (no tests collected) while using testmon = all deselected = pass."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_example.py").write_text("def test_ok(): pass")
        (tmp_path / ".testmondata").touch()
        (tmp_path / "coverage.xml").write_text("<coverage></coverage>")

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=5, stdout="", stderr="", duration=0.05
        )

        check = PythonTestsCheck({}, runner=mock_runner)
        with patch.object(check, "check_project_venv_or_warn", return_value=None):
            with patch.object(check, "_testmon_available", return_value=True):
                result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_testmon_not_available_hard_fails(self, tmp_path):
        """When testmon is not installed, the check fails immediately."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_example.py").write_text("def test_ok(): pass")
        (tmp_path / ".testmondata").touch()
        (tmp_path / "coverage.xml").write_text("<coverage></coverage>")

        check = PythonTestsCheck({})
        with patch.object(check, "check_project_venv_or_warn", return_value=None):
            with patch.object(check, "_testmon_available", return_value=False):
                result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "pytest-testmon is required" in (result.error or "")


class TestPythonCoverageCheck:
    """Tests for PythonCoverageCheck."""

    def test_name(self):
        """Test check name."""
        check = PythonCoverageCheck({})
        assert check.name == "coverage-gaps.py"

    def test_display_name(self):
        """Test check display name."""
        check = PythonCoverageCheck({})
        assert "Coverage" in check.display_name

    def test_depends_on(self):
        """Test check dependencies."""
        check = PythonCoverageCheck({})
        assert "overconfidence:untested-code.py" in check.depends_on

    def test_is_applicable_python_project(self, tmp_path):
        """Test is_applicable returns True for Python project with tests."""
        (tmp_path / "pyproject.toml").touch()
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_example.py").write_text("def test_one(): pass")
        check = PythonCoverageCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_run_coverage_above_threshold(self, tmp_path):
        """Test run when coverage is above threshold."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_example.py").write_text(
            "def test_ok():\n    pass\n"
        )
        # Create coverage.xml file
        (tmp_path / "coverage.xml").write_text("<coverage></coverage>")

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="TOTAL    1000    100    90%", stderr="", duration=1.0
        )

        check = PythonCoverageCheck({}, runner=mock_runner)
        with patch.object(check, "check_project_venv_or_warn", return_value=None):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_coverage_above_threshold_branch_columns(self, tmp_path):
        """Test run parses TOTAL correctly when branch columns are present."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_example.py").write_text(
            "def test_ok():\n    pass\n"
        )
        (tmp_path / "coverage.xml").write_text("<coverage></coverage>")

        mock_runner = MagicMock()
        # Branch format: Stmts  Miss  Branch  BrPart  Cover
        mock_runner.run.return_value = SubprocessResult(
            returncode=0,
            stdout="TOTAL    14188   1829   4910    736    84%",
            stderr="",
            duration=1.0,
        )

        check = PythonCoverageCheck({}, runner=mock_runner)
        with patch.object(check, "check_project_venv_or_warn", return_value=None):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_parse_coverage_branch_format(self):
        """_parse_coverage extracts TOTAL % even with Branch/BrPart columns."""
        check = PythonCoverageCheck({})
        # Non-branch format
        assert check._parse_coverage("TOTAL    1000    100    90%") == 90.0
        # Branch format (4 numeric columns before the %)
        assert (
            check._parse_coverage("TOTAL   14188   1829   4910    736    84%") == 84.0
        )

    def test_parse_missing_lines_branch_format(self):
        """_parse_missing_lines handles optional Branch/BrPart columns."""
        check = PythonCoverageCheck({})
        branch_output = (
            "Name      Stmts   Miss Branch BrPart  Cover   Missing\n"
            "slopmop/foo.py   100     10     40      5    85%   12-15, 42\n"
            "slopmop/bar.py    50      0     20      0   100%\n"
        )
        result = check._parse_missing_lines(branch_output)
        assert len(result) == 1
        assert result[0][0] == "slopmop/foo.py"
        assert result[0][2] == 10  # miss count
        assert result[0][3] == "12-15, 42"

    def test_run_coverage_below_threshold(self, tmp_path):
        """Test run when coverage is below threshold."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_example.py").write_text(
            "def test_ok():\n    pass\n"
        )
        # Create coverage.xml file
        (tmp_path / "coverage.xml").write_text("<coverage></coverage>")

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="TOTAL    1000    500    50%", stderr="", duration=1.0
        )

        check = PythonCoverageCheck({}, runner=mock_runner)
        with patch.object(check, "check_project_venv_or_warn", return_value=None):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED

    def test_run_no_coverage_data(self, tmp_path):
        """Test run when no coverage data exists."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_example.py").write_text(
            "def test_ok():\n    pass\n"
        )
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1, stdout="No data to report", stderr="", duration=1.0
        )

        check = PythonCoverageCheck({}, runner=mock_runner)
        with patch.object(check, "check_project_venv_or_warn", return_value=None):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED

    def test_skip_reason_python_project_not_applicable_message(self, tmp_path):
        """Skip reason uses coverage-specific generic message for Python projects."""
        (tmp_path / "pyproject.toml").touch()
        check = PythonCoverageCheck({})
        assert (
            check.skip_reason(str(tmp_path)) == "Python coverage check not applicable"
        )

    def test_run_fails_when_no_python_tests_exist(self, tmp_path):
        """No tests should fail before coverage parsing with actionable guidance."""
        (tmp_path / "pyproject.toml").touch()
        check = PythonCoverageCheck({})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "No Python test files" in (result.error or "")
        assert result.fix_suggestion is not None

    def test_diagnose_warns_when_coverage_xml_is_missing(self, tmp_path):
        """Doctor surfaces the common missing coverage.xml preflight issue."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('hello')")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_main.py").write_text(
            "def test_main():\n    assert True\n"
        )

        diagnostics = PythonCoverageCheck({}).diagnose(str(tmp_path))

        assert len(diagnostics) == 1
        assert diagnostics[0].severity == "warn"
        assert diagnostics[0].summary == "coverage.xml is missing"
        assert "overconfidence:untested-code.py" in diagnostics[0].fix_hint

    def test_diagnose_passes_when_coverage_xml_exists(self, tmp_path):
        """Coverage doctor diagnostic is quiet when XML data is present."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('hello')")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_main.py").write_text(
            "def test_main():\n    assert True\n"
        )
        (tmp_path / "coverage.xml").write_text("<coverage />")

        assert PythonCoverageCheck({}).diagnose(str(tmp_path)) == []


class TestPythonStaticAnalysisCheck:
    """Tests for PythonStaticAnalysisCheck."""

    def test_name(self):
        """Test check name."""
        check = PythonStaticAnalysisCheck({})
        assert check.name == "missing-annotations.py"

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
        assert "laziness:sloppy-formatting.py" in check.depends_on

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
        errors, codes, _findings = PythonStaticAnalysisCheck._dedup_output(raw)
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
        errors, codes, _findings = PythonStaticAnalysisCheck._dedup_output(raw)
        assert len(errors) == 3
        assert codes == {"type-arg": 2, "no-untyped-def": 1}

    def test_dedup_output_skips_summary_line(self):
        """Test dedup strips mypy's own summary line."""
        raw = (
            "a.py:1: error: Bad  [type-arg]\n"
            "Found 1 error in 1 file (checked 5 source files)\n"
        )
        errors, _, _findings = PythonStaticAnalysisCheck._dedup_output(raw)
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
        assert result.why_it_matters is not None
        assert result.findings
        assert result.findings[0].fix_strategy is not None
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


# ─── coverage.py helper functions ────────────────────────────────────────


class TestGetCompareBranch:
    """Tests for _get_compare_branch() env-var precedence."""

    def test_explicit_compare_branch_takes_priority(self):
        with patch.dict("os.environ", {"COMPARE_BRANCH": "origin/dev"}):
            assert _get_compare_branch() == "origin/dev"

    def test_github_base_ref_gets_origin_prefix(self):
        env = {"GITHUB_BASE_REF": "main"}
        with patch.dict("os.environ", env, clear=True):
            # Remove COMPARE_BRANCH if it exists
            import os

            os.environ.pop("COMPARE_BRANCH", None)
            assert _get_compare_branch() == "origin/main"

    def test_defaults_to_origin_main(self):
        with patch.dict("os.environ", {}, clear=True):
            assert _get_compare_branch() == "origin/main"

    def test_compare_branch_overrides_github_base_ref(self):
        env = {"COMPARE_BRANCH": "origin/staging", "GITHUB_BASE_REF": "main"}
        with patch.dict("os.environ", env):
            assert _get_compare_branch() == "origin/staging"


class TestTestFileFor:
    """Tests for _test_file_for() — conventional test path derivation."""

    def test_regular_module(self):
        assert _test_file_for("slopmop/cli/hooks.py") == "tests/test_hooks.py"

    def test_init_resolves_to_package_name(self):
        assert _test_file_for("slopmop/core/__init__.py") == "tests/test_core.py"

    def test_root_init_returns_none(self):
        assert _test_file_for("__init__.py") is None

    def test_empty_stem_returns_none(self):
        assert _test_file_for("") is None

    def test_nested_module(self):
        assert _test_file_for("a/b/c/utils.py") == "tests/test_utils.py"

    def test_degenerate_init_with_dot_parent(self):
        assert _test_file_for("./__init__.py") is None


class TestFirstRange:
    """Tests for _first_range() — parsing coverage missing ranges."""

    def test_single_number(self):
        assert _first_range("42") == (42, 42)

    def test_range(self):
        assert _first_range("12-18") == (12, 18)

    def test_comma_separated_picks_first(self):
        assert _first_range("12-18, 42, 90-101") == (12, 18)

    def test_single_in_list(self):
        assert _first_range("5, 10-20") == (5, 5)

    def test_garbage_returns_none(self):
        assert _first_range("abc") is None

    def test_empty_returns_none(self):
        assert _first_range("") is None

    def test_whitespace_stripped(self):
        assert _first_range("  7  ") == (7, 7)


class TestCharacteriseBlock:
    """Tests for _characterise_block() — AST-based block identification."""

    def test_except_handler(self):
        import ast

        code = "def foo():\n  try:\n    x()\n  except IOError:\n    pass\n"
        tree = ast.parse(code)
        func = tree.body[0]
        hint = _characterise_block(func, 4, 5)
        assert hint is not None
        assert "except" in hint

    def test_if_body(self):
        import ast

        code = "def foo():\n  if x:\n    return 1\n"
        tree = ast.parse(code)
        func = tree.body[0]
        hint = _characterise_block(func, 3, 3)
        assert hint is not None
        assert "conditional" in hint

    def test_other_body_returns_none(self):
        import ast

        code = "def foo():\n  x = 1\n  return x\n"
        tree = ast.parse(code)
        func = tree.body[0]
        hint = _characterise_block(func, 2, 3)
        assert hint is None


class TestResolveUncoveredRange:
    """Tests for _resolve_uncovered_range() — AST-resolution of uncovered lines."""

    def test_happy_path_finds_enclosing_function(self, tmp_path):
        source = "def helper():\n    if True:\n        x = 1\n    return x\n"
        (tmp_path / "mod.py").write_text(source)
        result = _resolve_uncovered_range(str(tmp_path), "mod.py", "2-3")
        assert result is not None
        assert "helper()" in result
        assert "uncovered" in result

    def test_no_enclosing_function_returns_none(self, tmp_path):
        source = "x = 1\ny = 2\n"
        (tmp_path / "mod.py").write_text(source)
        result = _resolve_uncovered_range(str(tmp_path), "mod.py", "1-2")
        assert result is None

    def test_unparseable_file_returns_none(self, tmp_path):
        (tmp_path / "bad.py").write_text("def whoops(:\n")
        result = _resolve_uncovered_range(str(tmp_path), "bad.py", "1")
        assert result is None

    def test_missing_file_returns_none(self, tmp_path):
        result = _resolve_uncovered_range(str(tmp_path), "gone.py", "1")
        assert result is None

    def test_garbage_range_returns_none(self, tmp_path):
        (tmp_path / "mod.py").write_text("def f():\n    pass\n")
        result = _resolve_uncovered_range(str(tmp_path), "mod.py", "abc")
        assert result is None

    def test_except_block_gets_hint(self, tmp_path):
        source = (
            "def handler():\n"
            "    try:\n"
            "        open('x')\n"
            "    except FileNotFoundError:\n"
            "        return None\n"
        )
        (tmp_path / "mod.py").write_text(source)
        result = _resolve_uncovered_range(str(tmp_path), "mod.py", "5")
        assert result is not None
        assert "except" in result


class TestParseUnifiedDiff:
    """``_parse_unified_diff`` extracts head-line numbers from git diff output."""

    def test_pure_addition(self):
        diff = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -0,0 +1,3 @@\n"
            "+line one\n"
            "+line two\n"
            "+line three\n"
        )
        assert _parse_unified_diff(diff) == {"foo.py": {1, 2, 3}}

    def test_replacement_block_records_only_added_lines(self):
        diff = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -10,2 +10,3 @@\n"
            "-old a\n"
            "-old b\n"
            "+new a\n"
            "+new b\n"
            "+new c\n"
        )
        assert _parse_unified_diff(diff) == {"foo.py": {10, 11, 12}}

    def test_pure_deletion_yields_no_added_lines(self):
        diff = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -5,2 +4,0 @@\n"
            "-gone\n"
            "-also gone\n"
        )
        assert _parse_unified_diff(diff) == {}

    def test_deleted_file_skipped(self):
        diff = (
            "diff --git a/old.py b/old.py\n"
            "deleted file mode 100644\n"
            "--- a/old.py\n"
            "+++ /dev/null\n"
            "@@ -1,2 +0,0 @@\n"
            "-bye\n"
            "-bye\n"
        )
        assert _parse_unified_diff(diff) == {}

    def test_multiple_files_and_hunks(self):
        diff = (
            "diff --git a/a.py b/a.py\n"
            "--- a/a.py\n"
            "+++ b/a.py\n"
            "@@ -1,0 +1,1 @@\n"
            "+a1\n"
            "@@ -10,0 +12,2 @@\n"
            "+a12\n"
            "+a13\n"
            "diff --git a/b.py b/b.py\n"
            "--- a/b.py\n"
            "+++ b/b.py\n"
            "@@ -3,1 +3,1 @@\n"
            "-old\n"
            "+new at 3\n"
        )
        assert _parse_unified_diff(diff) == {
            "a.py": {1, 12, 13},
            "b.py": {3},
        }

    def test_empty_diff(self):
        assert _parse_unified_diff("") == {}

    def test_added_line_body_starting_with_plus_plus(self):
        """Hunk line ``+++ value`` is ``+`` plus body ``++ value``, not a path."""
        diff = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+normal\n"
            "+++ value\n"
        )
        assert _parse_unified_diff(diff) == {"foo.py": {1, 2}}


class TestParseCoverageXmlLines:
    """``_parse_coverage_xml_lines`` classifies Cobertura lines as hit/miss/partial."""

    def _xml(self, lines_xml: str) -> str:
        return (
            '<?xml version="1.0" ?>\n'
            "<coverage>\n"
            "  <packages>\n"
            "    <package>\n"
            "      <classes>\n"
            '        <class filename="src/foo.py">\n'
            "          <lines>\n"
            f"            {lines_xml}\n"
            "          </lines>\n"
            "        </class>\n"
            "      </classes>\n"
            "    </package>\n"
            "  </packages>\n"
            "</coverage>\n"
        )

    def test_plain_hit(self):
        xml = self._xml('<line number="1" hits="3"/>')
        assert _parse_coverage_xml_lines(xml) == {"src/foo.py": {1: "hit"}}

    def test_plain_miss(self):
        xml = self._xml('<line number="2" hits="0"/>')
        assert _parse_coverage_xml_lines(xml) == {"src/foo.py": {2: "miss"}}

    def test_branch_full_is_hit(self):
        xml = self._xml(
            '<line number="3" hits="1" branch="true" '
            'condition-coverage="100% (2/2)"/>'
        )
        assert _parse_coverage_xml_lines(xml) == {"src/foo.py": {3: "hit"}}

    def test_branch_partial(self):
        xml = self._xml(
            '<line number="4" hits="1" branch="true" '
            'condition-coverage="50% (1/2)" missing-branches="6"/>'
        )
        assert _parse_coverage_xml_lines(xml) == {"src/foo.py": {4: "partial"}}

    def test_zero_hit_branch_is_miss_not_partial(self):
        # hits=0 always wins, even on a branch line.
        xml = self._xml(
            '<line number="5" hits="0" branch="true" ' 'condition-coverage="0% (0/2)"/>'
        )
        assert _parse_coverage_xml_lines(xml) == {"src/foo.py": {5: "miss"}}

    def test_skips_lines_missing_required_attrs(self):
        xml = self._xml(
            '<line number="6"/>\n            <line number="7" hits="not-a-number"/>'
        )
        # Both lines are dropped silently; class still appears with empty map.
        assert _parse_coverage_xml_lines(xml) == {"src/foo.py": {}}


class TestComputeDiffCoverage:
    """``_compute_diff_coverage`` intersects diff lines with coverage data."""

    def test_classifies_hit_miss_partial(self):
        diff = {"a.py": {1, 2, 3, 4}}
        coverage = {
            "a.py": {
                1: "hit",
                2: "miss",
                3: "partial",
                4: "hit",
            }
        }
        report = _compute_diff_coverage(diff, coverage, "origin/main")
        assert len(report.files) == 1
        f = report.files[0]
        assert f.hits == [1, 4]
        assert f.misses == [2]
        assert f.partials == [3]
        assert f.percent == 50.0
        assert report.percent == 50.0
        assert report.total_lines == 4

    def test_drops_files_not_in_coverage(self):
        diff = {"src/main.py": {1}, "tests/test_main.py": {1}}
        coverage = {"src/main.py": {1: "hit"}}
        report = _compute_diff_coverage(diff, coverage, "origin/main")
        assert [f.filename for f in report.files] == ["src/main.py"]

    def test_drops_diff_lines_not_in_coverage_data(self):
        # Comment / blank lines: in the diff but absent from coverage.
        diff = {"a.py": {1, 2, 3}}
        coverage = {"a.py": {1: "hit", 3: "hit"}}
        report = _compute_diff_coverage(diff, coverage, "origin/main")
        assert report.files[0].hits == [1, 3]
        assert report.files[0].misses == []
        assert report.files[0].partials == []
        assert report.total_lines == 2

    def test_file_with_zero_classified_lines_dropped(self):
        diff = {"a.py": {99}}  # diffed but not a statement
        coverage = {"a.py": {}}
        report = _compute_diff_coverage(diff, coverage, "origin/main")
        assert report.files == []
        assert report.percent == 100.0

    def test_empty_diff(self):
        report = _compute_diff_coverage({}, {}, "origin/main")
        assert report.files == []
        assert report.total_lines == 0
        assert report.percent == 100.0


class TestCompactLineRanges:
    """``_compact_line_ranges`` collapses line lists into Cobertura-style ranges."""

    def test_consecutive(self):
        assert _compact_line_ranges([1, 2, 3]) == "1-3"

    def test_singleton(self):
        assert _compact_line_ranges([42]) == "42"

    def test_mixed(self):
        assert _compact_line_ranges([1, 2, 3, 5, 7, 8, 10]) == "1-3,5,7-8,10"

    def test_unsorted_input(self):
        assert _compact_line_ranges([5, 1, 3, 2]) == "1-3,5"

    def test_empty(self):
        assert _compact_line_ranges([]) == ""

    def test_dedupes(self):
        assert _compact_line_ranges([1, 1, 2]) == "1-2"


class TestFormatDiffCoverageOutput:
    """``_format_diff_coverage_output`` renders the human-readable summary."""

    def test_includes_partials_in_per_file_line(self):
        report = _DiffCoverageReport(
            files=[
                _FileDiffCov(
                    filename="src/x.py",
                    hits=[1, 2],
                    misses=[3, 4],
                    partials=[5],
                )
            ],
            compare_branch="origin/main",
        )
        out = _format_diff_coverage_output(report)
        assert "src/x.py (40.0%): Missing 3-4; Partial 5" in out
        assert "Total:    5 lines" in out
        assert "Hit:      2 lines" in out
        assert "Missing:  2 lines" in out
        assert "Partial:  1 lines" in out
        assert "Coverage: 40.0%" in out
        assert "origin/main...HEAD" in out

    def test_full_coverage_file_has_no_suffix(self):
        report = _DiffCoverageReport(
            files=[_FileDiffCov(filename="src/x.py", hits=[1, 2, 3])],
            compare_branch="origin/main",
        )
        out = _format_diff_coverage_output(report)
        assert "src/x.py (100.0%)" in out
        assert "Missing" not in out.split("src/x.py (100.0%)")[1].split("---")[0]

    def test_empty_report(self):
        report = _DiffCoverageReport(files=[], compare_branch="origin/main")
        out = _format_diff_coverage_output(report)
        assert "No coverage-tracked changes to evaluate." in out
        assert "Coverage: 100.0%" in out


class TestBuildDiffCoverageFindings:
    """``_build_diff_coverage_findings`` emits one Finding per non-clean file."""

    def test_one_finding_per_problem_file(self):
        report = _DiffCoverageReport(
            files=[
                _FileDiffCov(filename="a.py", hits=[1, 2]),
                _FileDiffCov(filename="b.py", hits=[1], misses=[2], partials=[3]),
                _FileDiffCov(filename="c.py", hits=[1], misses=[2]),
            ],
            compare_branch="origin/main",
        )
        findings = _build_diff_coverage_findings(report)
        assert {f.file for f in findings} == {"b.py", "c.py"}

    def test_finding_message_lists_missing_and_partial(self):
        report = _DiffCoverageReport(
            files=[
                _FileDiffCov(
                    filename="a.py", hits=[1], misses=[2, 3], partials=[5, 6, 7]
                )
            ],
            compare_branch="origin/main",
        )
        findings = _build_diff_coverage_findings(report)
        assert len(findings) == 1
        msg = findings[0].message
        assert "missing 2-3" in msg
        assert "partial 5-7" in msg


class TestPythonDiffCoverageCheck:
    """High-level behavior of the rewired diff-coverage gate."""

    COVERAGE_XML = (
        '<?xml version="1.0" ?>\n'
        "<coverage>\n"
        "  <packages>\n"
        "    <package>\n"
        "      <classes>\n"
        '        <class filename="src/main.py">\n'
        "          <lines>\n"
        '            <line number="10" hits="1"/>\n'
        '            <line number="11" hits="0"/>\n'
        '            <line number="12" hits="1" branch="true" '
        'condition-coverage="50% (1/2)"/>\n'
        "          </lines>\n"
        "        </class>\n"
        "      </classes>\n"
        "    </package>\n"
        "  </packages>\n"
        "</coverage>\n"
    )

    def _setup_python_project(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test_a():\n    pass\n")
        (tmp_path / "coverage.xml").write_text(self.COVERAGE_XML)

    def test_name(self):
        check = PythonDiffCoverageCheck({})
        assert check.name == "just-this-once.py"

    def test_depends_on_untested_code(self):
        check = PythonDiffCoverageCheck({})
        assert "overconfidence:untested-code.py" in check.depends_on

    def test_is_applicable_python_with_tests(self, tmp_path):
        (tmp_path / "setup.py").touch()
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test_a(): pass")
        check = PythonDiffCoverageCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_run_passes_when_diff_is_empty(self, tmp_path):
        self._setup_python_project(tmp_path)
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="", stderr="", duration=0.1
        )
        check = PythonDiffCoverageCheck({}, runner=mock_runner)
        with patch.object(check, "check_project_venv_or_warn", return_value=None):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED
        assert "No changed Python files" in result.output

    def test_run_passes_when_diff_lines_all_hit(self, tmp_path):
        self._setup_python_project(tmp_path)
        diff = (
            "diff --git a/src/main.py b/src/main.py\n"
            "--- a/src/main.py\n"
            "+++ b/src/main.py\n"
            "@@ -9,0 +10,1 @@\n"
            "+executed line\n"
        )
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout=diff, stderr="", duration=0.1
        )
        check = PythonDiffCoverageCheck({}, runner=mock_runner)
        with patch.object(check, "check_project_venv_or_warn", return_value=None):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED
        assert "Coverage: 100.0%" in result.output

    def test_run_fails_when_partials_drag_below_threshold(self, tmp_path):
        # Diff covers lines 10 (hit), 11 (miss), 12 (partial) — 1/3 = 33%.
        self._setup_python_project(tmp_path)
        diff = (
            "diff --git a/src/main.py b/src/main.py\n"
            "--- a/src/main.py\n"
            "+++ b/src/main.py\n"
            "@@ -9,0 +10,3 @@\n"
            "+a\n"
            "+b\n"
            "+c\n"
        )
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout=diff, stderr="", duration=0.1
        )
        check = PythonDiffCoverageCheck({}, runner=mock_runner)
        with patch.object(check, "check_project_venv_or_warn", return_value=None):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "Missing 11" in result.output
        assert "Partial 12" in result.output
        assert "Coverage: 33.3%" in result.output
        assert any("partial" in (f.message or "").lower() for f in result.findings)

    def test_run_skips_files_outside_coverage_scope(self, tmp_path):
        # Diff touches a test file (not in coverage.xml) — should pass with
        # "no coverage-tracked changes" message.
        self._setup_python_project(tmp_path)
        diff = (
            "diff --git a/tests/test_x.py b/tests/test_x.py\n"
            "--- a/tests/test_x.py\n"
            "+++ b/tests/test_x.py\n"
            "@@ -1,0 +1,1 @@\n"
            "+# new test comment\n"
        )
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout=diff, stderr="", duration=0.1
        )
        check = PythonDiffCoverageCheck({}, runner=mock_runner)
        with patch.object(check, "check_project_venv_or_warn", return_value=None):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED
        assert "No coverage-tracked changes" in result.output

    def test_run_returns_error_when_git_diff_fails(self, tmp_path):
        self._setup_python_project(tmp_path)
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=128, stdout="", stderr="bad ref", duration=0.1
        )
        check = PythonDiffCoverageCheck({}, runner=mock_runner)
        with patch.object(check, "check_project_venv_or_warn", return_value=None):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.ERROR
        assert "git diff failed" in (result.error or "")

    def test_run_returns_error_when_coverage_xml_unparseable(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test_a():\n    pass\n")
        (tmp_path / "coverage.xml").write_text("not xml at all <<<")
        diff = (
            "diff --git a/src/main.py b/src/main.py\n"
            "--- a/src/main.py\n"
            "+++ b/src/main.py\n"
            "@@ -0,0 +1,1 @@\n"
            "+x\n"
        )
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout=diff, stderr="", duration=0.1
        )
        check = PythonDiffCoverageCheck({}, runner=mock_runner)
        with patch.object(check, "check_project_venv_or_warn", return_value=None):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.ERROR
        assert "coverage.xml" in (result.error or "")

    def test_run_no_coverage_xml(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test_a():\n    pass\n")
        check = PythonDiffCoverageCheck({})
        with (
            patch.object(check, "check_project_venv_or_warn", return_value=None),
            patch(
                "slopmop.checks.python.coverage._wait_for_coverage_xml",
                return_value=False,
            ),
        ):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.ERROR

    def test_diagnose_warns_when_coverage_xml_is_missing(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('hello')")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test_a():\n    pass\n")

        diagnostics = PythonDiffCoverageCheck({}).diagnose(str(tmp_path))

        assert len(diagnostics) == 1
        assert diagnostics[0].severity == "warn"
        assert diagnostics[0].summary == "coverage.xml is missing"
        assert "overconfidence:untested-code.py" in diagnostics[0].fix_hint

    def test_skip_reason_python_project_not_applicable_message(self, tmp_path):
        """Skip reason uses diff-coverage specific generic message for Python projects."""
        (tmp_path / "pyproject.toml").touch()
        check = PythonDiffCoverageCheck({})
        assert check.skip_reason(str(tmp_path)) == "Diff coverage check not applicable"

    def test_run_fails_when_no_python_tests_exist(self, tmp_path):
        """No tests should fail before invoking diff-cover."""
        (tmp_path / "pyproject.toml").touch()
        check = PythonDiffCoverageCheck({})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "No Python test files" in (result.error or "")
        assert result.fix_suggestion is not None
