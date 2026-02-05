"""Tests for LocLockCheck."""

from slopmop.checks.quality.loc_lock import (
    LocLockCheck,
)
from slopmop.core.result import CheckStatus


class TestLocLockCheck:
    """Tests for LocLockCheck."""

    def test_name(self):
        """Test check name."""
        check = LocLockCheck({})
        assert check.name == "loc-lock"

    def test_display_name(self):
        """Test display name."""
        check = LocLockCheck({})
        assert "LOC" in check.display_name

    def test_category(self):
        """Test check category."""
        check = LocLockCheck({})
        assert check.category.key == "quality"

    def test_config_schema_has_required_fields(self):
        """Test config schema includes key fields."""
        check = LocLockCheck({})
        schema = check.config_schema
        field_names = [f.name for f in schema]

        assert "max_file_lines" in field_names
        assert "max_function_lines" in field_names
        assert "include_dirs" in field_names
        assert "exclude_dirs" in field_names

    def test_is_applicable_with_python_files(self, tmp_path):
        """Test check is applicable when Python files exist."""
        (tmp_path / "main.py").write_text("print('hello')")
        check = LocLockCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_with_js_files(self, tmp_path):
        """Test check is applicable when JS files exist."""
        (tmp_path / "app.js").write_text("console.log('hello');")
        check = LocLockCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_no_source_files(self, tmp_path):
        """Test check is not applicable without source files."""
        (tmp_path / "data.txt").write_text("just text")
        check = LocLockCheck({})
        assert check.is_applicable(str(tmp_path)) is False


class TestLocLockFileLength:
    """Tests for file length enforcement."""

    def test_passes_short_file(self, tmp_path):
        """Test passes when file is under limit."""
        content = "\n".join([f"line {i}" for i in range(50)])
        (tmp_path / "short.py").write_text(content)

        check = LocLockCheck({"max_file_lines": 100})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_fails_long_file(self, tmp_path):
        """Test fails when file exceeds limit."""
        content = "\n".join([f"# line {i}" for i in range(150)])
        (tmp_path / "long.py").write_text(content)

        check = LocLockCheck({"max_file_lines": 100})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "long.py" in result.output
        assert "150 lines" in result.output

    def test_respects_default_file_limit(self, tmp_path):
        """Test uses default 1000 line limit."""
        content = "\n".join([f"# line {i}" for i in range(999)])
        (tmp_path / "under.py").write_text(content)

        check = LocLockCheck({})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_fails_over_default_file_limit(self, tmp_path):
        """Test fails when file exceeds default 1000 line limit."""
        content = "\n".join([f"# line {i}" for i in range(1001)])
        (tmp_path / "over.py").write_text(content)

        check = LocLockCheck({})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED


class TestLocLockFunctionLength:
    """Tests for function length enforcement."""

    def test_passes_short_function(self, tmp_path):
        """Test passes when function is under limit."""
        content = '''
def short_function():
    """Short function."""
    x = 1
    y = 2
    return x + y
'''
        (tmp_path / "short.py").write_text(content)

        check = LocLockCheck({"max_function_lines": 10})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_fails_long_function(self, tmp_path):
        """Test fails when function exceeds limit."""
        lines = ["def long_function():"]
        lines.append('    """Long function."""')
        for i in range(25):
            lines.append(f"    x{i} = {i}")
        lines.append("    return x0")

        (tmp_path / "long.py").write_text("\n".join(lines))

        check = LocLockCheck({"max_function_lines": 10})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "long_function" in result.output

    def test_respects_default_function_limit(self, tmp_path):
        """Test uses default 100 line limit for functions."""
        lines = ["def almost_too_long():"]
        for i in range(98):
            lines.append(f"    x{i} = {i}")
        lines.append("    return x0")

        (tmp_path / "ok.py").write_text("\n".join(lines))

        check = LocLockCheck({})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_detects_multiple_long_functions(self, tmp_path):
        """Test detects multiple function violations."""
        lines = []

        # First long function
        lines.append("def func1():")
        for i in range(15):
            lines.append(f"    a{i} = {i}")
        lines.append("")

        # Second long function
        lines.append("def func2():")
        for i in range(15):
            lines.append(f"    b{i} = {i}")

        (tmp_path / "multi.py").write_text("\n".join(lines))

        check = LocLockCheck({"max_function_lines": 10})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "func1" in result.output
        assert "func2" in result.output


class TestLocLockExclusions:
    """Tests for directory and file exclusions."""

    def test_excludes_node_modules(self, tmp_path):
        """Test excludes node_modules directory."""
        nm_dir = tmp_path / "node_modules" / "package"
        nm_dir.mkdir(parents=True)

        # Long file in node_modules
        content = "\n".join([f"// line {i}" for i in range(2000)])
        (nm_dir / "huge.js").write_text(content)

        # Short file in project
        (tmp_path / "app.js").write_text("const x = 1;")

        check = LocLockCheck({"max_file_lines": 100})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_excludes_venv(self, tmp_path):
        """Test excludes venv directory."""
        venv_dir = tmp_path / "venv" / "lib"
        venv_dir.mkdir(parents=True)

        # Long file in venv
        content = "\n".join([f"# line {i}" for i in range(2000)])
        (venv_dir / "huge.py").write_text(content)

        # Short file in project
        (tmp_path / "main.py").write_text("x = 1")

        check = LocLockCheck({"max_file_lines": 100})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_respects_custom_exclude_dirs(self, tmp_path):
        """Test respects custom exclude_dirs config."""
        gen_dir = tmp_path / "generated"
        gen_dir.mkdir()

        # Long generated file
        content = "\n".join([f"# line {i}" for i in range(2000)])
        (gen_dir / "huge.py").write_text(content)

        # Short file in project
        (tmp_path / "main.py").write_text("x = 1")

        check = LocLockCheck(
            {
                "max_file_lines": 100,
                "exclude_dirs": ["generated"],
            }
        )
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED


class TestLocLockLanguageSupport:
    """Tests for different language support."""

    def test_detects_js_arrow_functions(self, tmp_path):
        """Test detects long arrow functions in JavaScript."""
        lines = ["const longArrow = () => {"]
        for i in range(15):
            lines.append(f"  const x{i} = {i};")
        lines.append("  return x0;")
        lines.append("};")

        (tmp_path / "arrow.js").write_text("\n".join(lines))

        check = LocLockCheck({"max_function_lines": 10})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "longArrow" in result.output

    def test_detects_async_python_functions(self, tmp_path):
        """Test detects long async functions in Python."""
        lines = ["async def long_async():"]
        for i in range(15):
            lines.append(f"    x{i} = {i}")
        lines.append("    return x0")

        (tmp_path / "async.py").write_text("\n".join(lines))

        check = LocLockCheck({"max_function_lines": 10})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "long_async" in result.output

    def test_checks_only_specified_extensions(self, tmp_path):
        """Test only checks specified extensions when configured."""
        # Long Python file
        py_content = "\n".join([f"# line {i}" for i in range(200)])
        (tmp_path / "long.py").write_text(py_content)

        # Long JS file
        js_content = "\n".join([f"// line {i}" for i in range(200)])
        (tmp_path / "long.js").write_text(js_content)

        # Only check .js files
        check = LocLockCheck(
            {
                "max_file_lines": 100,
                "extensions": [".js"],
            }
        )
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "long.js" in result.output
        assert "long.py" not in result.output


class TestLocLockOutput:
    """Tests for output formatting."""

    def test_includes_fix_suggestion(self, tmp_path):
        """Test failure includes fix suggestion."""
        content = "\n".join([f"# line {i}" for i in range(200)])
        (tmp_path / "long.py").write_text(content)

        check = LocLockCheck({"max_file_lines": 100})
        result = check.run(str(tmp_path))

        assert result.fix_suggestion is not None
        assert "Break" in result.fix_suggestion or "Extract" in result.fix_suggestion

    def test_limits_output_to_top_violations(self, tmp_path):
        """Test output is limited to top violations."""
        # Create 15 files, all too long
        for i in range(15):
            content = "\n".join([f"# line {j}" for j in range(200 + i)])
            (tmp_path / f"file{i:02d}.py").write_text(content)

        check = LocLockCheck({"max_file_lines": 100})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        # Should show top 10 and mention "... and X more"
        assert "and" in result.output and "more" in result.output
