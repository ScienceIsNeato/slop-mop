"""Tests for the Python lint/format check."""

from unittest.mock import MagicMock

from slopmop.checks.python.lint_format import PythonLintFormatCheck
from slopmop.core.result import CheckStatus
from slopmop.subprocess.runner import SubprocessResult


class TestPythonLintFormatCheck:
    """Tests for PythonLintFormatCheck."""

    def test_name(self):
        """Test check name."""
        check = PythonLintFormatCheck({})
        assert check.name == "sloppy-formatting.py"

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

    def test_auto_fix_excludes_generated_dirs(self, tmp_path):
        """Test auto_fix excludes migration/ephemeral directories."""
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "__init__.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="", stderr="", duration=1.0
        )
        check = PythonLintFormatCheck({}, runner=mock_runner)
        check.auto_fix(str(tmp_path))

        commands = [call.args[0] for call in mock_runner.run.call_args_list]
        autoflake_cmd = next(
            cmd for cmd in commands if cmd and cmd[0].endswith("autoflake")
        )
        isort_cmd = next(cmd for cmd in commands if cmd and cmd[0].endswith("isort"))

        assert any(
            arg.startswith("--exclude=")
            and "migrations" in arg
            and "alembic" in arg
            and "ephemeral" in arg
            for arg in autoflake_cmd
        )
        assert "--skip=migrations" in isort_cmd
        assert "--skip=alembic" in isort_cmd
        assert "--skip=ephemeral" in isort_cmd

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

    def test_check_black_module_not_found_skips(self, tmp_path):
        """Broken black install (ModuleNotFoundError) returns skip sentinel."""
        from slopmop.checks.python.lint_format import _BLACK_SKIPPED

        (tmp_path / "test.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1,
            stdout=(
                "Traceback (most recent call last):\n"
                '  File "/usr/bin/black", line 5, in <module>\n'
                "ModuleNotFoundError: No module named '_black_internals'"
            ),
            stderr="",
            duration=1.0,
        )

        check = PythonLintFormatCheck({}, runner=mock_runner)
        result = check._check_black(str(tmp_path))
        assert result == _BLACK_SKIPPED

    def test_check_black_import_error_skips(self, tmp_path):
        """Broken black install (ImportError) returns skip sentinel."""
        from slopmop.checks.python.lint_format import _BLACK_SKIPPED

        (tmp_path / "test.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1,
            stdout="ImportError: cannot import name 'parse' from 'ast'",
            stderr="",
            duration=1.0,
        )

        check = PythonLintFormatCheck({}, runner=mock_runner)
        result = check._check_black(str(tmp_path))
        assert result == _BLACK_SKIPPED

    def test_check_black_filename_containing_import_error_not_skipped(self, tmp_path):
        """File named ImportError.py does not trigger the skip sentinel."""
        (tmp_path / "test.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1,
            stdout="would reformat ImportError.py",
            stderr="",
            duration=1.0,
        )

        check = PythonLintFormatCheck({}, runner=mock_runner)
        result = check._check_black(str(tmp_path))
        # Real formatting failure — not treated as a broken installation
        assert result is not None
        assert result != "__BLACK_SKIPPED_BROKEN_INSTALL__"
        assert "ImportError.py" in result

    def test_run_black_broken_shows_skipped_not_passed(self, tmp_path):
        """run() shows 'Skipped' when black is broken, not '✅ Formatting OK'."""

        (tmp_path / "test.py").touch()

        mock_runner = MagicMock()
        # First call = black (broken), subsequent calls = isort/flake8 (pass)
        mock_runner.run.side_effect = [
            SubprocessResult(
                returncode=1,
                stdout="ModuleNotFoundError: No module named 'black'",
                stderr="",
                duration=1.0,
            ),
            SubprocessResult(returncode=0, stdout="", stderr="", duration=1.0),
            SubprocessResult(returncode=0, stdout="", stderr="", duration=1.0),
        ]

        check = PythonLintFormatCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))
        # Gate passes overall (broken tool is not the user's code fault)
        assert result.status == CheckStatus.PASSED
        assert "Skipped" in result.output
        assert "Formatting OK" not in result.output

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

    def test_check_isort_uses_generated_dir_excludes(self, tmp_path):
        """Test _check_isort command excludes migration/ephemeral directories."""
        (tmp_path / "test.py").touch()
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="", stderr="", duration=1.0
        )

        check = PythonLintFormatCheck({}, runner=mock_runner)
        check._check_isort(str(tmp_path))

        command = mock_runner.run.call_args.args[0]
        assert "--skip=migrations" in command
        assert "--skip=alembic" in command
        assert "--skip=ephemeral" in command
