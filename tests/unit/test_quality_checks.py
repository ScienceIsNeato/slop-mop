"""Tests for quality checks (complexity, source duplication)."""

import json
from unittest.mock import MagicMock, patch

from slopmop.checks.quality.complexity import (
    MAX_COMPLEXITY,
    ComplexityCheck,
    _to_finding,
)
from slopmop.checks.quality.duplication import SourceDuplicationCheck
from slopmop.core.result import CheckStatus


class TestComplexityCheck:
    """Tests for ComplexityCheck."""

    def test_name(self):
        """Test check name."""
        check = ComplexityCheck({})
        assert check.name == "complexity-creep.py"

    def test_full_name(self):
        """Test full check name with category."""
        check = ComplexityCheck({})
        assert check.full_name == "laziness:complexity-creep.py"

    def test_display_name(self):
        """Test display name."""
        check = ComplexityCheck({})
        assert "Complexity" in check.display_name

    def test_config_schema(self):
        """Test config schema includes expected fields."""
        check = ComplexityCheck({})
        schema = check.config_schema
        field_names = [f.name for f in schema]
        assert "max_rank" in field_names
        assert "max_complexity" in field_names
        assert "src_dirs" in field_names

    def test_max_complexity_constant_matches_schema_default(self):
        """Fallback constant must stay in sync with schema default."""
        check = ComplexityCheck({})
        schema = {f.name: f for f in check.config_schema}
        assert schema["max_complexity"].default == MAX_COMPLEXITY

    def test_is_applicable_with_python_files(self, tmp_path):
        """Test is_applicable returns True for Python projects."""
        (tmp_path / "app.py").write_text("print('hello')")
        check = ComplexityCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_no_python(self, tmp_path):
        """Test is_applicable returns False for non-Python projects."""
        (tmp_path / "app.js").write_text("console.log('hello')")
        check = ComplexityCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_run_low_complexity(self, tmp_path):
        """Test run() when complexity is acceptable."""
        (tmp_path / "app.py").write_text("def simple(): pass")
        check = ComplexityCheck({})

        # Mock radon output with no violations (empty markdown output)
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.returncode = 0
        mock_result.output = ""  # No violations

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_high_complexity(self, tmp_path):
        """Test run() when complexity exceeds threshold."""
        (tmp_path / "app.py").write_text("def complex(): pass")
        check = ComplexityCheck({})

        # Mock radon output with violations - matches regex for D/E/F with (
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.returncode = 0
        mock_result.output = "    F   50:0 complex (50)"  # Radon markdown format

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED

    def test_run_empty_output(self, tmp_path):
        """Test run() when radon finds no functions."""
        (tmp_path / "app.py").write_text("# Just a comment")
        check = ComplexityCheck({})

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.returncode = 0
        mock_result.output = ""

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_radon_not_available(self, tmp_path):
        """Test run() when radon is not installed."""
        (tmp_path / "app.py").write_text("def test(): pass")
        check = ComplexityCheck({})

        mock_result = MagicMock()
        mock_result.returncode = 127
        mock_result.output = "command not found"

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.WARNED
        assert "Radon not available" in result.error

    def test_run_radon_file_not_found_error(self, tmp_path):
        """Test run() when SubprocessRunner raises FileNotFoundError (returncode -1).

        When find_tool() returns None and the bare 'radon' command doesn't exist,
        SubprocessRunner catches FileNotFoundError and returns returncode=-1 with
        stderr containing 'Command not found'. The check must recognise this as
        'tool not installed' rather than silently passing.
        Regression test for: PR #48 Bugbot comment on radon detection.
        """
        (tmp_path / "app.py").write_text("def test(): pass")
        check = ComplexityCheck({})

        mock_result = MagicMock()
        mock_result.returncode = -1
        mock_result.stderr = "Command not found: radon\n[Errno 2] No such file"
        mock_result.output = ""

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.WARNED
        assert "Radon not available" in result.error


class TestSourceDuplicationCheck:
    """Tests for SourceDuplicationCheck."""

    def test_name(self):
        """Test check name."""
        check = SourceDuplicationCheck({})
        assert check.name == "source-duplication"

    def test_full_name(self):
        """Test full check name with category."""
        check = SourceDuplicationCheck({})
        assert check.full_name == "myopia:source-duplication"

    def test_display_name(self):
        """Test display name."""
        check = SourceDuplicationCheck({})
        assert "Duplication" in check.display_name

    def test_config_schema(self):
        """Test config schema includes expected fields."""
        check = SourceDuplicationCheck({})
        schema = check.config_schema
        field_names = [f.name for f in schema]
        assert "threshold" in field_names
        assert "min_tokens" in field_names
        assert "exclude_dirs" in field_names

    def test_build_command_ignores_migrations_by_default(self):
        """jscpd command should ignore migration boilerplate by default."""
        check = SourceDuplicationCheck({})
        cmd = check._build_jscpd_command(
            "/tmp/report", ["."], min_tokens=50, min_lines=5
        )
        ignore_arg = cmd[cmd.index("--ignore") + 1]
        assert "migrations" in ignore_arg
        assert "alembic" in ignore_arg

    def test_is_applicable_with_python(self, tmp_path):
        """Test is_applicable returns True for Python projects."""
        (tmp_path / "app.py").write_text("print('hello')")
        check = SourceDuplicationCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_with_js(self, tmp_path):
        """Test is_applicable returns True for JS projects."""
        (tmp_path / "app.js").write_text("console.log('hello')")
        check = SourceDuplicationCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_no_code(self, tmp_path):
        """Test is_applicable returns False for non-code projects."""
        (tmp_path / "README.md").write_text("# Hello")
        check = SourceDuplicationCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_run_jscpd_not_available(self, tmp_path):
        """Test run() when jscpd is not installed."""
        (tmp_path / "app.py").write_text("def test(): pass")
        check = SourceDuplicationCheck({})

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.output = ""

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.WARNED
        assert "jscpd not available" in result.error

    def test_run_no_duplication(self, tmp_path):
        """Test run() when no duplication found."""
        (tmp_path / "app.py").write_text("def unique(): pass")
        check = SourceDuplicationCheck({})

        # First call checks jscpd availability, second runs the analysis
        version_result = MagicMock()
        version_result.returncode = 0
        version_result.output = "6.0.0"

        analysis_result = MagicMock()
        analysis_result.returncode = 0
        analysis_result.output = ""
        analysis_result.stdout = json.dumps(
            {"statistics": {"total": {"percentage": 0, "duplicatedLines": 0}}}
        )

        with patch.object(
            check, "_run_command", side_effect=[version_result, analysis_result]
        ):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_with_duplication(self, tmp_path):
        """Test run() when duplication exceeds threshold."""
        (tmp_path / "app.py").write_text("def copy(): pass")
        check = SourceDuplicationCheck({"threshold": 5})

        version_result = MagicMock()
        version_result.returncode = 0
        version_result.output = "6.0.0"

        analysis_result = MagicMock()
        analysis_result.returncode = 0
        analysis_result.output = ""
        analysis_result.error = None

        # Mock the temp directory and report file
        report_data = {
            "duplicates": [
                {"firstFile": {"name": "a.py"}, "secondFile": {"name": "b.py"}}
            ],
            "statistics": {
                "total": {
                    "duplicatedLines": 100,
                    "lines": 200,
                    "percentage": 50.0,
                }
            },
        }

        with (
            patch.object(
                check, "_run_command", side_effect=[version_result, analysis_result]
            ),
            patch("tempfile.TemporaryDirectory") as mock_temp,
            patch("os.path.exists", return_value=True),
            patch("builtins.open", create=True) as mock_open,
        ):
            # Set up temp directory mock - use tempfile.gettempdir() for portability
            import tempfile as tf

            mock_temp.return_value.__enter__.return_value = tf.gettempdir()
            # Set up file read mock
            mock_file = MagicMock()
            mock_file.__enter__.return_value.read.return_value = json.dumps(report_data)
            mock_open.return_value = mock_file
            # Also need to mock json.load
            with patch("json.load", return_value=report_data):
                result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED

    def test_run_with_duplication_below_threshold(self, tmp_path):
        """Test run() passes when duplicates exist but percentage is below threshold."""
        (tmp_path / "app.py").write_text("def copy(): pass")
        check = SourceDuplicationCheck({"threshold": 5})

        version_result = MagicMock()
        version_result.returncode = 0
        version_result.output = "6.0.0"

        analysis_result = MagicMock()
        analysis_result.returncode = 0
        analysis_result.output = ""
        analysis_result.error = None

        # Mock the temp directory and report file with duplicates below threshold
        report_data = {
            "duplicates": [
                {"firstFile": {"name": "a.py"}, "secondFile": {"name": "b.py"}}
            ],
            "statistics": {
                "total": {
                    "duplicatedLines": 6,
                    "lines": 200,
                    "percentage": 3.0,  # Below 5% threshold
                }
            },
        }

        with (
            patch.object(
                check, "_run_command", side_effect=[version_result, analysis_result]
            ),
            patch("tempfile.TemporaryDirectory") as mock_temp,
            patch("os.path.exists", return_value=True),
            patch("builtins.open", create=True) as mock_open,
        ):
            import tempfile as tf

            mock_temp.return_value.__enter__.return_value = tf.gettempdir()
            mock_file = MagicMock()
            mock_file.__enter__.return_value.read.return_value = json.dumps(report_data)
            mock_open.return_value = mock_file
            with patch("json.load", return_value=report_data):
                result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert "within limits" in result.output
        assert "1 clone(s)" in result.output

    def test_skip_reason_no_source_files(self, tmp_path):
        """Test skip_reason returns correct message when no source files."""
        (tmp_path / "README.md").write_text("# Hello")
        check = SourceDuplicationCheck({})
        reason = check.skip_reason(str(tmp_path))
        assert "No Python or JavaScript/TypeScript source files" in reason

    def test_skip_reason_with_source_files(self, tmp_path):
        """Test skip_reason returns generic message when source files exist."""
        (tmp_path / "app.py").write_text("print('hello')")
        check = SourceDuplicationCheck({})
        reason = check.skip_reason(str(tmp_path))
        assert "not applicable" in reason.lower()


# ─── _to_finding helper ──────────────────────────────────────────────────


class TestToFinding:
    """Tests for _to_finding() — radon violation line → Finding."""

    def test_delta_positive_strategy(self):
        line = "slopmop/cli/validate.py:10:0 `_run_validation` - C (17)"
        f = _to_finding(line, limit=10)
        assert f.fix_strategy is not None
        assert "shed at least 7" in f.fix_strategy
        assert f.file == "slopmop/cli/validate.py"
        assert f.line == 10

    def test_delta_zero_or_negative_strategy(self):
        # Score equals limit — still gets "extract helpers" advice
        line = "src/app.py:5:0 `handle` - B (10)"
        f = _to_finding(line, limit=10)
        assert f.fix_strategy is not None
        assert "Extract helpers" in f.fix_strategy
        assert "configured rank gate" in f.fix_strategy
        assert "exceeds rank threshold" not in f.fix_strategy

    def test_no_loc_match(self):
        line = "`some_func` - C (15)"
        f = _to_finding(line, limit=10)
        assert f.file is None
        assert f.line is None
        assert f.fix_strategy is not None
        assert "shed at least 5" in f.fix_strategy

    def test_no_meta_match(self):
        line = "slopmop/x.py:1:0 random noise"
        f = _to_finding(line, limit=10)
        assert f.fix_strategy is None
        assert f.file == "slopmop/x.py"
        assert f.line == 1
