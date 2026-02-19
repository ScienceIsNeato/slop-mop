"""Tests for slopmop.reporting.display.renderer module."""

from slopmop.reporting.display.renderer import (
    build_category_header,
    build_overall_progress,
    build_progress_bar,
    display_width,
    strip_category_prefix,
    truncate_for_inline,
)


class TestDisplayWidth:
    """Tests for display_width function."""

    def test_ascii_string(self):
        """ASCII characters have width 1."""
        assert display_width("hello") == 5

    def test_empty_string(self):
        """Empty string has width 0."""
        assert display_width("") == 0

    def test_emoji_double_width(self):
        """Common emoji typically take 2 columns."""
        # Snake emoji
        result = display_width("🐍")
        assert result >= 1  # At least 1, may be 2 depending on emoji

    def test_mixed_content(self):
        """Mixed ASCII and emoji."""
        text = "Hello 🐍"
        result = display_width(text)
        assert result >= 7  # "Hello " = 6, emoji >= 1


class TestTruncateForInline:
    """Tests for truncate_for_inline function."""

    def test_empty_text(self):
        """Empty text returns empty."""
        assert truncate_for_inline("", 50) == ""

    def test_whitespace_only(self):
        """Whitespace-only returns empty."""
        assert truncate_for_inline("   \n  \n  ", 50) == ""

    def test_short_text_unchanged(self):
        """Text shorter than max_width unchanged."""
        text = "Short error"
        assert truncate_for_inline(text, 50) == text

    def test_long_text_truncated(self):
        """Long text is truncated with ellipsis."""
        text = "This is a very long error message that should be truncated"
        result = truncate_for_inline(text, 20)
        assert len(result) <= 21  # max_width + ellipsis
        assert result.endswith("…")

    def test_multiline_takes_first(self):
        """Takes first non-empty line from multiline text."""
        text = "\n\nFirst line\nSecond line\nThird line"
        result = truncate_for_inline(text, 50)
        assert result == "First line"

    def test_strips_whitespace(self):
        """Strips leading/trailing whitespace from lines."""
        text = "  Error message  \n  More text  "
        result = truncate_for_inline(text, 50)
        assert result == "Error message"


class TestBuildCategoryHeader:
    """Tests for build_category_header function."""

    def test_basic_header(self):
        """Header contains label and progress."""
        header = build_category_header("Python", 3, 6, term_width=40)
        assert "Python" in header
        assert "[3/6]" in header

    def test_header_uses_dash(self):
        """Header uses the configured dash character."""
        header = build_category_header("Test", 0, 1, term_width=40)
        assert "─" in header

    def test_header_fills_width(self):
        """Header pads with dashes to fill terminal width."""
        header = build_category_header("X", 1, 1, term_width=40)
        # Header should be approximately terminal width
        assert display_width(header) <= 40

    def test_header_all_complete(self):
        """Header shows all completed."""
        header = build_category_header("Security", 5, 5, term_width=60)
        assert "[5/5]" in header

    def test_header_none_complete(self):
        """Header shows zero completed."""
        header = build_category_header("JS", 0, 3, term_width=60)
        assert "[0/3]" in header

    def test_header_with_emoji_label(self):
        """Header works with emoji in label."""
        header = build_category_header("🐍 Python", 2, 4, term_width=50)
        assert "🐍 Python" in header
        assert "[2/4]" in header


class TestStripCategoryPrefix:
    """Tests for strip_category_prefix function."""

    def test_strip_python_prefix(self):
        """Strips category prefix from py-prefixed check."""
        assert strip_category_prefix("laziness:py-lint") == "py-lint"

    def test_strip_myopia_prefix(self):
        """Strips myopia: prefix."""
        assert strip_category_prefix("myopia:loc-lock") == "loc-lock"

    def test_strip_deceptiveness_prefix(self):
        """Strips deceptiveness: prefix."""
        assert strip_category_prefix("deceptiveness:bogus-tests") == "bogus-tests"

    def test_no_prefix_unchanged(self):
        """Name without colon returned unchanged."""
        assert strip_category_prefix("some-check") == "some-check"

    def test_multiple_colons_splits_first(self):
        """Only strips up to first colon."""
        assert strip_category_prefix("a:b:c") == "b:c"

    def test_empty_string(self):
        """Empty string returned unchanged."""
        assert strip_category_prefix("") == ""


class TestBuildProgressBar:
    """Tests for build_progress_bar function."""

    def test_basic_progress_bar(self):
        """Progress bar renders with fill and empty chars."""
        result = build_progress_bar("left", "right", 60, 0.5)
        assert "[" in result
        assert "]" in result
        assert "50%" in result

    def test_colors_enabled_adds_ansi(self):
        """Colors enabled wraps filled portion in ANSI escape codes."""
        result = build_progress_bar("left", "right", 80, 0.5, colors_enabled=True)
        # Some ANSI escape should appear when there are filled chars
        assert "\033[" in result
        assert "\033[0m" in result

    def test_bar_color_param_used(self):
        """bar_color param controls the ANSI code applied to filled portion."""
        result = build_progress_bar(
            "left", "right", 80, 0.5, colors_enabled=True, bar_color="\033[32m"
        )
        assert "\033[32m" in result  # green, not the default cyan

    def test_colors_disabled_no_ansi(self):
        """Colors disabled produces no ANSI codes."""
        result = build_progress_bar("left", "right", 80, 0.5, colors_enabled=False)
        assert "\033[" not in result

    def test_zero_pct_no_color_escape(self):
        """0% completion with colors enabled still has no escape (no filled chars)."""
        result = build_progress_bar("left", "right", 80, 0.0, colors_enabled=True)
        assert "\033[0m" not in result


class TestBuildOverallProgress:
    """Tests for build_overall_progress function."""

    def test_basic_progress(self):
        """Overall progress line shows count and elapsed."""
        result = build_overall_progress(3, 10, 5.0)
        assert "3/10" in result
        assert "elapsed" in result

    def test_colors_enabled_adds_ansi(self):
        """Colors enabled wraps filled portion in ANSI green."""
        result = build_overall_progress(5, 10, 2.0, term_width=80, colors_enabled=True)
        assert "\033[32m" in result
        assert "\033[0m" in result

    def test_colors_disabled_no_ansi(self):
        """Colors disabled produces no ANSI codes."""
        result = build_overall_progress(5, 10, 2.0, term_width=80, colors_enabled=False)
        assert "\033[" not in result

    def test_zero_completed_no_color_escape(self):
        """0 completed with colors enabled has no escape (no filled chars)."""
        result = build_overall_progress(0, 10, 1.0, term_width=80, colors_enabled=True)
        assert "\033[32m" not in result
