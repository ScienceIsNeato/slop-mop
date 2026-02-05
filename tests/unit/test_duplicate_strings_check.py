"""Tests for string duplication check (wrapper for find-duplicate-strings)."""

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
        assert check.full_name == "quality:string-duplication"

    def test_display_name(self, check):
        """Test display name includes identifier."""
        assert "Duplication" in check.display_name

    def test_description(self, check):
        """Test description is present."""
        assert check.description is not None
        assert len(check.description) > 0

    def test_category(self, check):
        """Test check category is QUALITY."""
        from slopmop.checks.base import GateCategory

        assert check.category == GateCategory.QUALITY

    def test_config_schema(self, check):
        """Test config schema includes expected fields."""
        schema = check.config_schema
        field_names = [f.name for f in schema]
        assert "threshold" in field_names
        assert "min_file_count" in field_names
        assert "min_length" in field_names
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
        assert config["threshold"] == 3
        assert config["min_file_count"] == 2
        assert config["min_length"] == 4
        assert "**/*.py" in config["include_patterns"]

    def test_get_effective_config_overrides(self):
        """Test effective config merges overrides."""
        check = StringDuplicationCheck({"threshold": 5, "min_length": 10})
        config = check._get_effective_config()
        assert config["threshold"] == 5
        assert config["min_length"] == 10
        # Default should still be present
        assert config["min_file_count"] == 2

    def test_build_command_basic(self, check):
        """Test command building with basic config."""
        config = check._get_effective_config()
        cmd = check._build_command(config)

        assert "node" in cmd
        assert "--threshold" in cmd
        assert "--json" in cmd
        assert "3" in cmd  # default threshold

    def test_build_command_with_ignore(self, check):
        """Test command includes ignore patterns."""
        config = check._get_effective_config()
        cmd = check._build_command(config)

        assert "--ignore" in cmd
        # Should have comma-separated ignore list
        ignore_idx = cmd.index("--ignore")
        assert "node_modules" in cmd[ignore_idx + 1]

    def test_is_noise_whitespace(self, check):
        """Test that whitespace patterns are detected as noise."""
        assert check._is_noise("\\n") is True
        assert check._is_noise("\\t") is True
        assert check._is_noise(" ") is True

    def test_is_noise_common_words(self, check):
        """Test that common single words are detected as noise."""
        assert check._is_noise("id") is True
        assert check._is_noise("name") is True
        assert check._is_noise("type") is True
        assert check._is_noise("error") is True

    def test_is_noise_http_methods(self, check):
        """Test that HTTP methods are detected as noise."""
        assert check._is_noise("GET") is True
        assert check._is_noise("POST") is True
        assert check._is_noise("PUT") is True

    def test_is_noise_case_insensitive(self, check):
        """Test noise detection is case insensitive."""
        assert check._is_noise("Name") is True
        assert check._is_noise("NAME") is True
        assert check._is_noise("True") is True
        assert check._is_noise("FALSE") is True

    def test_is_not_noise(self, check):
        """Test that actual strings are not detected as noise."""
        assert check._is_noise("api_endpoint_url") is False
        assert check._is_noise("user_authentication") is False
        assert check._is_noise("database_connection") is False

    def test_filter_results_min_file_count(self, check):
        """Test filtering by minimum file count."""
        findings = [
            {
                "key": "single_file_string",
                "count": 5,
                "fileCount": 1,
                "files": ["a.py"],
            },
            {
                "key": "multi_file_string",
                "count": 3,
                "fileCount": 2,
                "files": ["a.py", "b.py"],
            },
        ]
        config = {"min_file_count": 2, "min_length": 4}
        filtered = check._filter_results(findings, config)

        assert len(filtered) == 1
        assert filtered[0]["key"] == "multi_file_string"

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
                "key": "long_string_here",
                "count": 3,
                "fileCount": 2,
                "files": ["a.py", "b.py"],
            },
        ]
        config = {"min_file_count": 1, "min_length": 4}
        filtered = check._filter_results(findings, config)

        assert len(filtered) == 1
        assert filtered[0]["key"] == "long_string_here"

    def test_filter_results_noise(self, check):
        """Test filtering removes noise patterns."""
        findings = [
            {"key": "\\n", "count": 100, "fileCount": 50, "files": ["a.py"]},
            {"key": "name", "count": 50, "fileCount": 25, "files": ["a.py"]},
            {
                "key": "actual_duplicate",
                "count": 5,
                "fileCount": 3,
                "files": ["a.py", "b.py", "c.py"],
            },
        ]
        config = {"min_file_count": 2, "min_length": 4}
        filtered = check._filter_results(findings, config)

        assert len(filtered) == 1
        assert filtered[0]["key"] == "actual_duplicate"

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

            assert result.status == CheckStatus.ERROR
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
        # Return findings that pass the filter
        findings = [
            {
                "key": "significant_duplicate_string",
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
                assert "significant_duplicate_string" in result.output

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
