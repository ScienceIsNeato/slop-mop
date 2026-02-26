"""Tests for dead code check (vulture wrapper)."""

from unittest.mock import MagicMock, patch

import pytest

from slopmop.checks.quality.dead_code import DeadCodeCheck
from slopmop.core.result import CheckStatus


class TestDeadCodeCheck:
    """Tests for DeadCodeCheck."""

    @pytest.fixture
    def check(self):
        """Default DeadCodeCheck instance."""
        return DeadCodeCheck({})

    # --- Identity & metadata ---

    def test_name(self, check):
        """Test check name."""
        assert check.name == "dead-code"

    def test_full_name(self, check):
        """Test full check name with category."""
        assert check.full_name == "laziness:dead-code"

    def test_display_name(self, check):
        """Test display name contains Dead Code."""
        assert "Dead Code" in check.display_name
        assert "80%" in check.display_name

    def test_display_name_custom_confidence(self):
        """Test display name reflects custom confidence."""
        check = DeadCodeCheck({"min_confidence": 90})
        assert "90%" in check.display_name

    def test_category(self, check):
        """Test category is laziness."""
        from slopmop.checks.base import GateCategory

        assert check.category == GateCategory.LAZINESS

    # --- Config schema ---

    def test_config_schema(self, check):
        """Test config schema includes expected fields."""
        schema = check.config_schema
        field_names = [f.name for f in schema]
        assert "min_confidence" in field_names
        assert "exclude_patterns" in field_names
        assert "src_dirs" in field_names
        assert "whitelist_file" in field_names

    # --- is_applicable ---

    def test_is_applicable_with_python_files(self, check, tmp_path):
        """Test is_applicable returns True when Python files exist."""
        (tmp_path / "app.py").write_text("print('hello')")
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_no_python(self, check, tmp_path):
        """Test is_applicable returns False with no Python files."""
        (tmp_path / "app.js").write_text("console.log('hello')")
        assert check.is_applicable(str(tmp_path)) is False

    # --- Config accessors ---

    def test_get_min_confidence_default(self, check):
        """Test default min_confidence is 80."""
        assert check._get_min_confidence() == 80

    def test_get_min_confidence_custom(self):
        """Test custom min_confidence from config."""
        check = DeadCodeCheck({"min_confidence": 95})
        assert check._get_min_confidence() == 95

    def test_get_exclude_patterns_default(self, check):
        """Test default exclude patterns include common ignored dirs."""
        patterns = check._get_exclude_patterns()
        assert "**/venv/**" in patterns
        assert "**/test_*" in patterns
        assert "**/*.egg-info/**" in patterns
        assert "**/build/**" in patterns
        assert "**/dist/**" in patterns
        assert "**/cursor-rules/**" in patterns

    def test_get_exclude_patterns_custom(self):
        """Test custom exclude patterns override defaults."""
        check = DeadCodeCheck({"exclude_patterns": ["**/custom/**"]})
        patterns = check._get_exclude_patterns()
        assert patterns == ["**/custom/**"]

    def test_get_src_dirs_default(self, check, tmp_path):
        """Test default src_dirs is ['.']."""
        dirs = check._get_src_dirs(str(tmp_path))
        assert dirs == ["."]

    def test_get_src_dirs_filters_nonexistent(self, tmp_path):
        """Test src_dirs filters out directories that don't exist."""
        (tmp_path / "src").mkdir()
        check = DeadCodeCheck({"src_dirs": ["src", "nonexistent"]})
        dirs = check._get_src_dirs(str(tmp_path))
        assert dirs == ["src"]

    # --- Glob-to-vulture conversion ---

    def test_glob_patterns_to_vulture_excludes(self, check):
        """Test glob pattern conversion preserves filename-level wildcards."""
        patterns = [
            "**/venv/**",
            "**/.venv/**",
            "**/node_modules/**",
            "**/test_*",
        ]
        excludes = check._glob_patterns_to_vulture_excludes(patterns)
        assert "venv" in excludes
        assert ".venv" in excludes
        assert "node_modules" in excludes
        assert "test_*" in excludes

    def test_glob_patterns_deduplicates(self, check):
        """Test no duplicate exclude names are produced."""
        patterns = ["**/venv/**", "**/venv/**"]
        excludes = check._glob_patterns_to_vulture_excludes(patterns)
        assert excludes.count("venv") == 1

    # --- Command building ---

    @patch("slopmop.checks.quality.dead_code.find_tool", return_value=None)
    def test_build_command_basic(self, mock_find, check, tmp_path):
        """Test basic command structure."""
        cmd = check._build_command(str(tmp_path))
        assert cmd[0] == "vulture"
        assert "." in cmd
        assert "--min-confidence" in cmd
        assert "80" in cmd

    def test_build_command_with_exclude(self, check, tmp_path):
        """Test command includes --exclude with patterns."""
        cmd = check._build_command(str(tmp_path))
        assert "--exclude" in cmd

    def test_build_command_with_whitelist(self, tmp_path):
        """Test whitelist file is placed as positional arg before flags.

        Vulture uses argparse with positional PATH args. The whitelist
        must appear alongside source dirs (before --min-confidence and
        --exclude) or argparse will reject it.
        Regression test for: https://github.com/ScienceIsNeato/slop-mop/issues/49
        """
        wl_file = tmp_path / "whitelist.py"
        wl_file.write_text("# whitelist")
        check = DeadCodeCheck({"whitelist_file": "whitelist.py"})
        cmd = check._build_command(str(tmp_path))
        assert str(wl_file) in cmd
        # Whitelist must come BEFORE any flags
        wl_idx = cmd.index(str(wl_file))
        assert "--min-confidence" in cmd
        flag_idx = cmd.index("--min-confidence")
        assert (
            wl_idx < flag_idx
        ), f"whitelist at index {wl_idx} must precede --min-confidence at {flag_idx}"

    def test_build_command_ignores_missing_whitelist(self, tmp_path):
        """Test command skips whitelist if file doesn't exist."""
        check = DeadCodeCheck({"whitelist_file": "nonexistent.py"})
        cmd = check._build_command(str(tmp_path))
        assert "nonexistent.py" not in " ".join(cmd)

    def test_build_command_custom_src_dirs(self, tmp_path):
        """Test command uses configured src_dirs."""
        (tmp_path / "lib").mkdir()
        check = DeadCodeCheck({"src_dirs": ["lib"]})
        cmd = check._build_command(str(tmp_path))
        assert "lib" in cmd

    # --- Output parsing ---

    def test_parse_findings_typical(self, check):
        """Test parsing typical vulture output."""
        output = (
            "app.py:42: unused function 'foo' (80% confidence)\n"
            "utils.py:10: unused import 'os' (90% confidence)\n"
        )
        findings = check._parse_findings(output)
        assert len(findings) == 2
        assert findings[0] == ("app.py", 42, "unused function 'foo'", 80)
        assert findings[1] == ("utils.py", 10, "unused import 'os'", 90)

    def test_parse_findings_empty(self, check):
        """Test parsing empty output produces no findings."""
        assert check._parse_findings("") == []
        assert check._parse_findings("\n\n") == []

    def test_parse_findings_ignores_noise(self, check):
        """Test parser ignores lines that don't match the pattern."""
        output = "Some random warning\nvulture: error\n"
        assert check._parse_findings(output) == []

    def test_parse_findings_various_types(self, check):
        """Test parsing different finding types."""
        output = (
            "a.py:1: unused variable 'x' (60% confidence)\n"
            "b.py:2: unused class 'Foo' (80% confidence)\n"
            "c.py:3: unreachable code after 'return' (100% confidence)\n"
        )
        findings = check._parse_findings(output)
        assert len(findings) == 3
        assert "unused variable" in findings[0][2]
        assert "unused class" in findings[1][2]
        assert "unreachable code" in findings[2][2]

    # --- Output formatting ---

    def test_format_findings(self, check):
        """Test findings are formatted as prescriptive output."""
        findings = [
            ("app.py", 42, "unused function 'foo'", 80),
            ("utils.py", 10, "unused import 'os'", 90),
        ]
        output = check._format_findings(findings)
        assert "2 dead code issue(s)" in output
        assert "app.py:42" in output
        assert "utils.py:10" in output
        assert "80%" in output

    def test_format_findings_truncates(self, check):
        """Test output truncation when many findings exist."""
        findings = [
            (f"file{i}.py", i, f"unused function 'f{i}'", 80) for i in range(20)
        ]
        output = check._format_findings(findings)
        assert "... and 5 more" in output

    # --- Run integration (mocked) ---

    def test_run_clean(self, check, tmp_path):
        """Test run() when vulture finds no dead code."""
        (tmp_path / "app.py").write_text("def used(): pass")
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.returncode = 0
        mock_result.output = ""
        mock_result.timed_out = False

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert "No dead code" in result.output

    def test_run_with_findings(self, check, tmp_path):
        """Test run() when vulture finds dead code."""
        (tmp_path / "app.py").write_text("def unused(): pass")
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.returncode = 3
        mock_result.output = "app.py:1: unused function 'unused' (80% confidence)\n"
        mock_result.timed_out = False

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "1 dead code finding(s)" in result.error

    def test_run_vulture_not_installed(self, check, tmp_path):
        """Test warning when vulture is not installed."""
        (tmp_path / "app.py").write_text("pass")
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.returncode = -1
        mock_result.output = ""
        mock_result.stderr = "Command not found: vulture"
        mock_result.timed_out = False

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        # Should be WARNED — vulture missing is non-blocking
        assert result.status == CheckStatus.WARNED
        assert "vulture not available" in result.error.lower()
        assert "install vulture" in result.fix_suggestion.lower()

    def test_run_vulture_not_installed_exit_127(self, check, tmp_path):
        """Test warning when shell returns 127 (command not found)."""
        (tmp_path / "app.py").write_text("pass")
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.returncode = 127
        mock_result.output = ""
        mock_result.stderr = ""
        mock_result.timed_out = False

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.WARNED
        assert "vulture not available" in result.error.lower()

    def test_run_multiple_findings(self, check, tmp_path):
        """Test run() with multiple findings produces correct count."""
        (tmp_path / "app.py").write_text("x = 1\ny = 2\n")
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.returncode = 3
        mock_result.output = (
            "app.py:1: unused variable 'x' (60% confidence)\n"
            "app.py:2: unused variable 'y' (60% confidence)\n"
            "app.py:3: unused function 'foo' (80% confidence)\n"
        )
        mock_result.timed_out = False

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "3 dead code finding(s)" in result.error
