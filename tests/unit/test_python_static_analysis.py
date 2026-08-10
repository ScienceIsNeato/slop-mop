"""Tests for PythonStaticAnalysisCheck (the mypy gate).

Split out of test_python_checks.py when that file crossed the code-sprawl
limit — this class carries its own fixtures and reads better standalone.
"""

from unittest.mock import MagicMock

from slopmop.checks.python.static_analysis import PythonStaticAnalysisCheck
from slopmop.core.result import CheckStatus
from slopmop.subprocess.runner import SubprocessResult


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

    def test_mypy_crash_reports_could_not_run_not_zero_errors(self, tmp_path):
        """mypy failing to RUN must not surface as 'FAILED: 0 type error(s)'.

        Regression: a duplicate module name (the same filename vendored in
        several dirs) makes mypy exit non-zero with a module-resolution error
        and no type errors. The gate parsed zero errors and still reported
        FAILED, handing the user a red gate with nothing to fix.
        """
        (tmp_path / "main.py").touch()
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").touch()

        crash = (
            'a/llm_api.py: error: Duplicate module named "llm_api" '
            '(also at "b/llm_api.py")\n'
            "Found 1 error in 1 file (errors prevented further checking)"
        )
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=2, stdout=crash, stderr="", duration=0.5
        )

        check = PythonStaticAnalysisCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.ERROR
        assert "could not complete" in (result.error or "")
        # mypy's own words must reach the user so the cause is actionable.
        assert "Duplicate module" in (result.output or "")
        assert "0 type error" not in (result.error or "")

    def test_mypy_real_type_errors_still_fail(self, tmp_path):
        """The crash path must not swallow genuine type errors."""
        (tmp_path / "main.py").touch()
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1,
            stdout="main.py:3: error: Function is missing a return type annotation  [no-untyped-def]",
            stderr="",
            duration=0.5,
        )

        check = PythonStaticAnalysisCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "type error(s) found" in (result.error or "")

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
