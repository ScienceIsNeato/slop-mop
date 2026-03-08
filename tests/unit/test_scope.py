"""Tests for scope metrics feature.

Tests ScopeInfo data structure, count_source_scope utility,
measure_scope implementations, executor integration, and display output.
"""

from slopmop.checks.base import (
    BaseCheck,
    Flaw,
    GateCategory,
    count_source_scope,
)
from slopmop.checks.mixins import PythonCheckMixin
from slopmop.core.result import CheckResult, CheckStatus, ExecutionSummary, ScopeInfo
from slopmop.reporting.display import config
from slopmop.reporting.display.renderer import build_category_header


class TestScopeInfo:
    """Tests for ScopeInfo dataclass."""

    def test_default_values(self):
        """ScopeInfo defaults to zero files and lines."""
        scope = ScopeInfo()
        assert scope.files == 0
        assert scope.lines == 0

    def test_format_compact_files_and_lines(self):
        """Compact format shows files and LOC."""
        scope = ScopeInfo(files=47, lines=3200)
        assert scope.format_compact() == "47 files · 3,200 LOC"

    def test_format_compact_large_loc(self):
        """Lines >= 10k use k suffix."""
        scope = ScopeInfo(files=97, lines=26113)
        assert scope.format_compact() == "97 files · 26.1k LOC"

    def test_format_compact_files_only(self):
        """Shows only files when lines is zero."""
        scope = ScopeInfo(files=10, lines=0)
        assert scope.format_compact() == "10 files"

    def test_format_compact_lines_only(self):
        """Shows only LOC when files is zero."""
        scope = ScopeInfo(files=0, lines=500)
        assert scope.format_compact() == "500 LOC"

    def test_format_compact_empty(self):
        """Empty scope returns empty string."""
        scope = ScopeInfo()
        assert scope.format_compact() == ""

    def test_add_operator(self):
        """Addition combines files and lines."""
        a = ScopeInfo(files=10, lines=100)
        b = ScopeInfo(files=20, lines=200)
        result = a + b
        assert result.files == 30
        assert result.lines == 300


class TestCheckResultScope:
    """Tests for scope field on CheckResult."""

    def test_scope_defaults_to_none(self):
        """CheckResult.scope is None by default."""
        result = CheckResult("test", CheckStatus.PASSED, 1.0)
        assert result.scope is None

    def test_scope_can_be_set(self):
        """CheckResult accepts scope parameter."""
        scope = ScopeInfo(files=10, lines=500)
        result = CheckResult("test", CheckStatus.PASSED, 1.0, scope=scope)
        assert result.scope is not None
        assert result.scope.files == 10
        assert result.scope.lines == 500


class TestExecutionSummaryScope:
    """Tests for scope aggregation in ExecutionSummary."""

    def test_total_scope_no_results(self):
        """Returns None when no results have scope."""
        results = [
            CheckResult("check1", CheckStatus.PASSED, 1.0),
            CheckResult("check2", CheckStatus.PASSED, 2.0),
        ]
        summary = ExecutionSummary.from_results(results, 3.0)
        assert summary.total_scope() is None

    def test_total_scope_single_result(self):
        """Returns scope from single result with scope."""
        scope = ScopeInfo(files=47, lines=3200)
        results = [
            CheckResult(
                "check1",
                CheckStatus.PASSED,
                1.0,
                scope=scope,
                category="overconfidence",
            ),
            CheckResult("check2", CheckStatus.PASSED, 2.0),
        ]
        summary = ExecutionSummary.from_results(results, 3.0)
        total = summary.total_scope()
        assert total is not None
        assert total.files == 47
        assert total.lines == 3200

    def test_scope_by_category_max_within_category(self):
        """Takes max files/lines within same category."""
        results = [
            CheckResult(
                "check1",
                CheckStatus.PASSED,
                1.0,
                scope=ScopeInfo(files=30, lines=2000),
                category="overconfidence",
            ),
            CheckResult(
                "check2",
                CheckStatus.PASSED,
                2.0,
                scope=ScopeInfo(files=50, lines=1500),
                category="overconfidence",
            ),
        ]
        summary = ExecutionSummary.from_results(results, 3.0)
        by_cat = summary.scope_by_category()
        assert "overconfidence" in by_cat
        assert by_cat["overconfidence"].files == 50
        assert by_cat["overconfidence"].lines == 2000

    def test_total_scope_max_across_categories(self):
        """Takes max files/lines across categories."""
        results = [
            CheckResult(
                "check1",
                CheckStatus.PASSED,
                1.0,
                scope=ScopeInfo(files=30, lines=2000),
                category="overconfidence",
            ),
            CheckResult(
                "check2",
                CheckStatus.PASSED,
                2.0,
                scope=ScopeInfo(files=50, lines=1500),
                category="myopia",
            ),
        ]
        summary = ExecutionSummary.from_results(results, 3.0)
        total = summary.total_scope()
        assert total is not None
        assert total.files == 50
        assert total.lines == 2000

    def test_scope_ignores_results_without_category(self):
        """Results without category are excluded."""
        results = [
            CheckResult(
                "check1",
                CheckStatus.PASSED,
                1.0,
                scope=ScopeInfo(files=30, lines=2000),
            ),
        ]
        summary = ExecutionSummary.from_results(results, 3.0)
        assert summary.scope_by_category() == {}
        assert summary.total_scope() is None


class TestCountSourceScope:
    """Tests for count_source_scope utility function."""

    def test_counts_python_files(self, tmp_path):
        """Counts .py files in directory."""
        (tmp_path / "main.py").write_text("line1\nline2\nline3\n")
        (tmp_path / "util.py").write_text("x = 1\n")

        scope = count_source_scope(str(tmp_path), extensions={".py"})
        assert scope.files == 2
        assert scope.lines == 4  # 3 + 1

    def test_excludes_standard_dirs(self, tmp_path):
        """Excludes __pycache__, .git, etc."""
        (tmp_path / "good.py").write_text("x = 1\n")
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "bad.py").write_text("cached\n")

        scope = count_source_scope(str(tmp_path), extensions={".py"})
        assert scope.files == 1

    def test_filters_by_extension(self, tmp_path):
        """Only counts files matching extensions."""
        (tmp_path / "main.py").write_text("python\n")
        (tmp_path / "readme.md").write_text("markdown\n")
        (tmp_path / "style.css").write_text("css\n")

        scope = count_source_scope(str(tmp_path), extensions={".py"})
        assert scope.files == 1

    def test_scans_include_dirs(self, tmp_path):
        """Scans only specified include_dirs."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("code\n")
        (tmp_path / "other.py").write_text("excluded\n")

        scope = count_source_scope(
            str(tmp_path), include_dirs=["src"], extensions={".py"}
        )
        assert scope.files == 1

    def test_empty_directory(self, tmp_path):
        """Returns zero counts for empty directory."""
        scope = count_source_scope(str(tmp_path), extensions={".py"})
        assert scope.files == 0
        assert scope.lines == 0

    def test_nonexistent_include_dir(self, tmp_path):
        """Handles nonexistent include_dirs gracefully."""
        scope = count_source_scope(
            str(tmp_path), include_dirs=["nonexistent"], extensions={".py"}
        )
        assert scope.files == 0
        assert scope.lines == 0

    def test_all_extensions_when_none(self, tmp_path):
        """Counts all files when extensions is None."""
        (tmp_path / "main.py").write_text("python\n")
        (tmp_path / "app.js").write_text("javascript\n")

        scope = count_source_scope(str(tmp_path))
        assert scope.files == 2

    def test_custom_exclude_dirs(self, tmp_path):
        """Respects custom exclude_dirs."""
        (tmp_path / "keep.py").write_text("kept\n")
        ignore = tmp_path / "ignored"
        ignore.mkdir()
        (ignore / "skip.py").write_text("skipped\n")

        scope = count_source_scope(
            str(tmp_path), extensions={".py"}, exclude_dirs={"ignored"}
        )
        assert scope.files == 1


class TestPythonCheckMixinScope:
    """Tests for PythonCheckMixin.measure_scope."""

    def test_returns_scope_info(self, tmp_path):
        """PythonCheckMixin.measure_scope returns ScopeInfo."""

        class TestCheck(BaseCheck, PythonCheckMixin):
            @property
            def name(self):
                return "test"

            @property
            def display_name(self):
                return "Test"

            @property
            def category(self):
                return GateCategory.OVERCONFIDENCE

            @property
            def flaw(self):
                return Flaw.OVERCONFIDENCE

            def is_applicable(self, root):
                return True

            def run(self, root):
                return CheckResult("test", CheckStatus.PASSED, 0.0)

        (tmp_path / "main.py").write_text("x = 1\ny = 2\n")
        (tmp_path / "test.js").write_text("var x;\n")

        check = TestCheck(config={})
        scope = check.measure_scope(str(tmp_path))

        assert scope is not None
        assert scope.files == 1  # Only .py files
        assert scope.lines == 2


class TestBuildCategoryHeaderScope:
    """Tests for column headers — now emitted separately, not in category headers."""

    def test_header_no_longer_embeds_column_labels(self):
        """Category header is a plain dash line — no scope/timing labels."""
        scope = ScopeInfo(files=23, lines=1200)
        header = build_category_header("Python", 3, 3, term_width=80, scope=scope)
        # Category header should NOT contain column labels any more
        assert "# files" not in header
        assert "LOC" not in header
        assert "avg" not in header
        assert "exp duration" not in header  # column labels belong in header line
        assert "act duration" not in header
        # Should still contain category name and progress
        assert "Python" in header
        assert "[3/3]" in header

    def test_header_without_scope(self):
        """Header works normally without scope."""
        header = build_category_header("Python", 3, 3, term_width=80, scope=None)
        assert "Python" in header
        assert "[3/3]" in header

    def test_column_header_line_has_labels(self):
        """Standalone column-header line contains timing labels."""
        from slopmop.reporting.display.renderer import build_column_header_line

        line = build_column_header_line(term_width=120)
        assert "exp duration" in line
        assert "act duration" in line
        assert "history" in line
        # Scope labels should NOT appear (moved to summary only)
        assert "# files" not in line
        assert "LOC" not in line

    def test_column_header_line_pipes_align_with_data(self):
        """The timing columns in the header align with data rows."""
        from slopmop.reporting.display.renderer import build_column_header_line

        tw = 120
        line = build_column_header_line(term_width=tw)
        # Build a fake data row with same constants as _format_completed_line
        timing = (
            "  0.2s".rjust(config.TIMING_AVG_WIDTH)
            + config.TIMING_SEP
            + "  0.3s".rjust(config.TIMING_TIME_WIDTH)
            + config.TIMING_SEP
            + "█" * config.TIMING_SPARK_WIDTH
        )
        data_line = " " * (tw - len(timing)) + timing
        # "history" label in header should start at same column as sparkline
        header_hist = line.index("history")
        # Find the first █ in data
        data_spark = data_line.index("█")
        assert (
            header_hist == data_spark
        ), f"Header 'history' at col {header_hist}, data sparkline at col {data_spark}"


class TestConsoleSummaryScope:
    """Tests for scope in console summary output."""

    def test_summary_all_passed_no_scope_in_summary(self, capsys):
        """Scope is NOT shown in swab/scour summary (moved to sm status)."""
        from slopmop.reporting.adapters import ConsoleAdapter
        from slopmop.reporting.report import RunReport

        scope = ScopeInfo(files=47, lines=3200)
        results = [
            CheckResult(
                "check1",
                CheckStatus.PASSED,
                1.0,
                scope=scope,
                category="overconfidence",
            ),
        ]
        summary = ExecutionSummary.from_results(results, 1.0)
        ConsoleAdapter(RunReport.from_summary(summary)).render()

        captured = capsys.readouterr()
        assert "NO SLOP DETECTED" in captured.out
        # Scope should NOT be in the validation summary
        assert "47 files" not in captured.out
        assert "3,200 LOC" not in captured.out

    def test_summary_all_passed_no_scope(self, capsys):
        """Summary line omits scope when no checks report it."""
        from slopmop.reporting.adapters import ConsoleAdapter
        from slopmop.reporting.report import RunReport

        results = [
            CheckResult("check1", CheckStatus.PASSED, 1.0),
        ]
        summary = ExecutionSummary.from_results(results, 1.0)
        ConsoleAdapter(RunReport.from_summary(summary)).render()

        captured = capsys.readouterr()
        assert "NO SLOP DETECTED" in captured.out
        assert "files" not in captured.out

    def test_summary_failure_no_scope_in_summary(self, capsys):
        """Scope is NOT shown in failure summary (moved to sm status)."""
        from slopmop.reporting.adapters import ConsoleAdapter
        from slopmop.reporting.report import RunReport

        scope = ScopeInfo(files=148, lines=27800)
        results = [
            CheckResult(
                "check1",
                CheckStatus.FAILED,
                1.0,
                error="Something broke",
                scope=scope,
                category="myopia",
            ),
        ]
        summary = ExecutionSummary.from_results(results, 1.0)
        ConsoleAdapter(RunReport.from_summary(summary)).render()

        captured = capsys.readouterr()
        assert "SLOP DETECTED" in captured.out
        # Scope should NOT be in the validation summary
        assert "148 files" not in captured.out
        assert "27.8k LOC" not in captured.out
