"""Tests for string duplication check (wrapper for find-duplicate-strings)."""

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slopmop.checks.quality.duplicate_strings import StringDuplicationCheck
from slopmop.core.result import CheckStatus


class TestStringDuplicationCheck:
    """Tests for StringDuplicationCheck wrapper."""

    @pytest.fixture
    def check(self):
        """Create a check instance."""
        return StringDuplicationCheck({})

    def test_name(self, check):
        """Test check name."""
        assert check.name == "string-duplication"

    def test_full_name(self, check):
        """Test full check name with category."""
        assert check.full_name == "myopia:string-duplication"

    def test_display_name(self, check):
        """Test display name includes identifier."""
        assert "Duplication" in check.display_name

    def test_description(self, check):
        """Test description is present."""
        assert check.description is not None
        assert len(check.description) > 0

    def test_category(self, check):
        """Test check category is MYOPIA."""
        from slopmop.checks.base import GateCategory

        assert check.category == GateCategory.MYOPIA

    def test_config_schema(self, check):
        """Test config schema includes expected fields."""
        schema = check.config_schema
        field_names = [f.name for f in schema]
        assert "threshold" in field_names
        assert "min_file_count" in field_names
        assert "min_length" in field_names
        assert "min_words" in field_names
        assert "include_patterns" in field_names
        assert "ignore_patterns" in field_names

    def test_is_applicable_with_python_files(self, check, tmp_path):
        """Test is_applicable returns True when Python files exist."""
        (tmp_path / "test.py").write_text("print('hello')")
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_without_python_files(self, check, tmp_path):
        """Test is_applicable returns False when no Python files."""
        (tmp_path / "test.txt").write_text("hello")
        assert check.is_applicable(str(tmp_path)) is False

    def test_get_tool_path(self, check):
        """Test tool path points to vendored find-duplicate-strings."""
        tool_path = check._get_tool_path()
        assert "tools" in str(tool_path)
        assert "find-duplicate-strings" in str(tool_path)
        assert "index.js" in str(tool_path)

    def test_get_effective_config_defaults(self, check):
        """Test effective config has defaults."""
        config = check._get_effective_config()
        assert config["threshold"] == 2
        assert config["min_file_count"] == 1
        assert config["min_length"] == 8
        assert config["min_words"] == 3
        assert "**/*.py" in config["include_patterns"]

    def test_get_effective_config_overrides(self):
        """Test effective config merges overrides."""
        check = StringDuplicationCheck({"threshold": 10, "min_length": 12})
        config = check._get_effective_config()
        assert config["threshold"] == 10
        assert config["min_length"] == 12
        # Default should still be present
        assert config["min_file_count"] == 1

    def test_build_command_basic(self, check):
        """Test command building with basic config."""
        config = check._get_effective_config()
        cmd = check._build_command(config)

        assert "node" in cmd
        assert "--threshold" in cmd
        assert "--json" in cmd
        assert "2" in cmd  # default threshold

    def test_build_command_with_ignore(self, check):
        """Test command includes ignore patterns."""
        config = check._get_effective_config()
        cmd = check._build_command(config)

        assert "--ignore" in cmd
        # Should have comma-separated ignore list with glob patterns
        ignore_idx = cmd.index("--ignore")
        assert "**/node_modules/**" in cmd[ignore_idx + 1]

    def test_is_noise_short_strings(self, check):
        """Test that short strings (< 8 chars) are detected as noise."""
        assert check._is_noise("\\n") is True
        assert check._is_noise(" ") is True
        assert check._is_noise("id") is True
        assert check._is_noise("name") is True
        assert check._is_noise("GET") is True
        assert check._is_noise("python") is True

    def test_is_noise_file_extensions(self, check):
        """Test that filenames with extensions are detected as noise."""
        assert check._is_noise("setup.py") is True
        assert check._is_noise("index.js") is True
        assert check._is_noise("config.json") is True
        assert check._is_noise("README.md") is True

    def test_is_noise_cli_flags(self, check):
        """Test that CLI flags are detected as noise."""
        assert check._is_noise("--verbose") is True
        assert check._is_noise("--threshold") is True
        assert check._is_noise("-m") is True

    def test_is_noise_import_paths(self, check):
        """Test that module import paths are detected as noise."""
        assert check._is_noise("os.path.join") is True
        assert check._is_noise("slopmop.core.registry") is True

    def test_is_not_noise(self, check):
        """Test that actual meaningful strings are not detected as noise."""
        assert check._is_noise("api_endpoint_url") is False
        assert check._is_noise("user_authentication") is False
        assert check._is_noise("database_connection") is False
        assert check._is_noise("application/json") is False

    def test_filter_results_min_file_count(self, check):
        """Test filtering by minimum file count."""
        findings = [
            {
                "key": "only in one single file",
                "count": 5,
                "fileCount": 1,
                "files": ["a.py"],
            },
            {
                "key": "appears in multiple files",
                "count": 3,
                "fileCount": 2,
                "files": ["a.py", "b.py"],
            },
        ]
        config = {"min_file_count": 2, "min_length": 4, "min_words": 1}
        filtered = check._filter_results(findings, config)

        assert len(filtered) == 1
        assert filtered[0]["key"] == "appears in multiple files"

    def test_filter_results_min_length(self, check):
        """Test filtering by minimum string length."""
        findings = [
            {
                "key": "ab",
                "count": 5,
                "fileCount": 2,
                "files": ["a.py", "b.py"],
            },
            {
                "key": "a longer string that qualifies",
                "count": 3,
                "fileCount": 2,
                "files": ["a.py", "b.py"],
            },
        ]
        config = {"min_file_count": 1, "min_length": 4, "min_words": 1}
        filtered = check._filter_results(findings, config)

        assert len(filtered) == 1
        assert filtered[0]["key"] == "a longer string that qualifies"

    def test_filter_results_noise(self, check):
        """Test filtering removes noise patterns."""
        findings = [
            {"key": "\\n", "count": 100, "fileCount": 50, "files": ["a.py"]},
            {"key": "name", "count": 50, "fileCount": 25, "files": ["a.py"]},
            {
                "key": "an actual duplicate string here",
                "count": 5,
                "fileCount": 3,
                "files": ["a.py", "b.py", "c.py"],
            },
        ]
        config = {"min_file_count": 2, "min_length": 4, "min_words": 1}
        filtered = check._filter_results(findings, config)

        assert len(filtered) == 1
        assert filtered[0]["key"] == "an actual duplicate string here"

    def test_filter_results_min_words(self, check):
        """Test filtering by minimum word count."""
        findings = [
            {
                "key": "store_true",
                "count": 14,
                "fileCount": 3,
                "files": ["a.py", "b.py", "c.py"],
            },
            {
                "key": "some identifier",
                "count": 10,
                "fileCount": 3,
                "files": ["a.py", "b.py", "c.py"],
            },
            {
                "key": "please extract this constant string",
                "count": 5,
                "fileCount": 3,
                "files": ["a.py", "b.py", "c.py"],
            },
        ]
        # min_words=3 filters 1-word and 2-word strings
        config = {"min_file_count": 1, "min_length": 4, "min_words": 3}
        filtered = check._filter_results(findings, config)

        assert len(filtered) == 1
        assert filtered[0]["key"] == "please extract this constant string"

    def test_filter_results_min_words_set_to_one(self, check):
        """Test min_words=1 allows single-word strings through."""
        findings = [
            {
                "key": "description",
                "count": 10,
                "fileCount": 3,
                "files": ["a.py", "b.py", "c.py"],
            },
        ]
        config = {"min_file_count": 1, "min_length": 4, "min_words": 1}
        filtered = check._filter_results(findings, config)

        assert len(filtered) == 1

    def test_format_findings_empty(self, check):
        """Test formatting with no findings."""
        output = check._format_findings([])
        assert "No duplicate strings" in output

    def test_format_findings_basic(self, check):
        """Test formatting with findings."""
        findings = [
            {
                "key": "duplicate_value",
                "count": 5,
                "fileCount": 2,
                "files": ["/path/to/file1.py", "/path/to/file2.py"],
            }
        ]
        output = check._format_findings(findings)

        assert "duplicate_value" in output
        assert "5 occurrences" in output
        assert "2 files" in output
        assert "constants.py" in output

    def test_format_findings_truncates_long_strings(self, check):
        """Test that long strings are truncated in output."""
        long_string = "a" * 100
        findings = [
            {
                "key": long_string,
                "count": 3,
                "fileCount": 2,
                "files": ["a.py", "b.py"],
            }
        ]
        output = check._format_findings(findings)

        # Should be truncated with ...
        assert "..." in output
        assert long_string not in output

    def test_format_findings_limits_files(self, check):
        """Test that file list is limited to 3."""
        findings = [
            {
                "key": "dup_string",
                "count": 10,
                "fileCount": 10,
                "files": [f"file{i}.py" for i in range(10)],
            }
        ]
        output = check._format_findings(findings)

        assert "and 7 more files" in output

    @patch.object(StringDuplicationCheck, "_run_command")
    def test_run_tool_not_found(self, mock_run, check, tmp_path):
        """Test run handles missing tool gracefully."""
        # Mock tool path to not exist
        with patch.object(check, "_get_tool_path") as mock_path:
            mock_path.return_value = MagicMock()
            mock_path.return_value.exists.return_value = False

            result = check.run(str(tmp_path))

            assert result.status == CheckStatus.WARNED
            assert "not found" in result.error.lower()

    @patch.object(StringDuplicationCheck, "_run_command")
    def test_run_no_duplicates(self, mock_run, check, tmp_path):
        """Test run when no duplicates found."""
        mock_result = MagicMock()
        mock_result.stdout = "[]"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        with patch.object(check, "_get_tool_path") as mock_path:
            mock_path.return_value = MagicMock()
            mock_path.return_value.exists.return_value = True

            result = check.run(str(tmp_path))

            assert result.status == CheckStatus.PASSED

    @patch.object(StringDuplicationCheck, "_run_command")
    def test_run_with_duplicates(self, mock_run, check, tmp_path):
        """Test run when duplicates are found."""
        # Return findings that pass the filter (multi-word to pass min_words=3)
        findings = [
            {
                "key": "a significant duplicate string found here",
                "count": 10,
                "fileCount": 5,
                "files": [f"file{i}.py" for i in range(5)],
            }
        ]
        mock_result = MagicMock()
        mock_result.stdout = str(findings).replace("'", '"')  # JSON format
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        with patch.object(check, "_get_tool_path") as mock_path:
            mock_path.return_value = MagicMock()
            mock_path.return_value.exists.return_value = True
            with patch("json.loads", return_value=findings):
                result = check.run(str(tmp_path))

                assert result.status == CheckStatus.FAILED
                assert "a significant duplicate string found here" in result.output

    @patch.object(StringDuplicationCheck, "_run_command")
    def test_run_json_parse_error(self, mock_run, check, tmp_path):
        """Test run handles JSON parse errors."""
        mock_result = MagicMock()
        mock_result.stdout = "invalid json {"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        with patch.object(check, "_get_tool_path") as mock_path:
            mock_path.return_value = MagicMock()
            mock_path.return_value.exists.return_value = True

            result = check.run(str(tmp_path))

            assert result.status == CheckStatus.ERROR
            assert "parse" in result.error.lower()

    @patch.object(StringDuplicationCheck, "_run_command")
    def test_run_command_exception(self, mock_run, check, tmp_path):
        """Test run handles command exceptions."""
        mock_run.side_effect = Exception("Command failed")

        with patch.object(check, "_get_tool_path") as mock_path:
            mock_path.return_value = MagicMock()
            mock_path.return_value.exists.return_value = True

            result = check.run(str(tmp_path))

            assert result.status == CheckStatus.ERROR
            assert "failed" in result.error.lower()

    def test_load_strip_function_success(self, check):
        """Test loading the strip_docstrings function from vendored tool."""
        fn = check._load_strip_function()
        # The function should be loadable if the tool is vendored
        strip_path = check._get_strip_docstrings_path()
        if strip_path.exists():
            assert fn is not None
            assert callable(fn)
            # Verify it strips docstrings
            result = fn('def foo():\n    """docstring"""\n    pass\n')
            assert '"""docstring"""' not in result
            assert "pass" in result
        else:
            assert fn is None

    def test_load_strip_function_missing_script(self, check):
        """Test loading returns None when script doesn't exist."""
        with patch.object(check, "_get_strip_docstrings_path") as mock_path:
            mock_path.return_value = Path("/nonexistent/strip_docstrings.py")
            assert check._load_strip_function() is None

    def test_preprocess_preserves_line_numbers(self, check, tmp_path):
        """Test that preprocessing preserves line count in stripped files."""
        src = tmp_path / "src"
        src.mkdir()
        # Write a file with a multi-line docstring
        code = (
            "def foo():\n"
            '    """This is\n'
            "    a multi-line\n"
            '    docstring."""\n'
            '    x = "real string"\n'
            "    return x\n"
        )
        (src / "example.py").write_text(code)

        config = {
            "include_patterns": ["**/*.py"],
            "ignore_patterns": [],
        }
        tmp_dir = check._preprocess_python_files(str(src), config)

        if tmp_dir is not None:
            try:
                stripped_file = Path(tmp_dir) / "example.py"
                assert stripped_file.exists()
                stripped = stripped_file.read_text()
                # Line count should be preserved
                assert stripped.count("\n") == code.count("\n")
                # Real string should still be present
                assert '"real string"' in stripped
                # Docstring content should be gone
                assert "multi-line" not in stripped
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_preprocess_no_python_patterns(self, check, tmp_path):
        """Test preprocessing returns None for non-Python patterns."""
        config = {
            "include_patterns": ["**/*.js"],
            "ignore_patterns": [],
        }
        result = check._preprocess_python_files(str(tmp_path), config)
        assert result is None

    def test_preprocess_no_matching_files(self, check, tmp_path):
        """Test preprocessing returns None when no .py files match."""
        config = {
            "include_patterns": ["**/*.py"],
            "ignore_patterns": [],
        }
        # tmp_path has no .py files
        result = check._preprocess_python_files(str(tmp_path), config)
        assert result is None

    def test_preprocess_respects_ignore_patterns(self, check, tmp_path):
        """Test preprocessing skips files matching ignore patterns."""
        (tmp_path / "good.py").write_text("x = 1\n")
        (tmp_path / "test_bad.py").write_text("x = 1\n")

        config = {
            "include_patterns": ["**/*.py"],
            "ignore_patterns": ["test_*"],
        }
        tmp_dir = check._preprocess_python_files(str(tmp_path), config)

        if tmp_dir is not None:
            try:
                # good.py should be present, test_bad.py should not
                assert (Path(tmp_dir) / "good.py").exists()
                assert not (Path(tmp_dir) / "test_bad.py").exists()
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_preprocess_strip_function_unavailable(self, check, tmp_path):
        """Test preprocessing returns None when strip function unavailable."""
        (tmp_path / "code.py").write_text("x = 1\n")

        config = {
            "include_patterns": ["**/*.py"],
            "ignore_patterns": [],
        }
        with patch.object(check, "_load_strip_function", return_value=None):
            result = check._preprocess_python_files(str(tmp_path), config)
            assert result is None
