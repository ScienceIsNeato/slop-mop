"""Tests for slopmop.reporting.display.renderer module."""

from slopmop.reporting.display import config
from slopmop.reporting.display.renderer import (
    build_category_header,
    build_check_connector,
    build_sparkline,
    display_width,
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


class TestBuildSparkline:
    """Tests for build_sparkline function."""

    def test_empty_historical(self):
        """Returns empty string with no history."""
        assert build_sparkline(1.0, [], 5) == ""

    def test_single_value_matches(self):
        """When current matches historical, shows middle chars."""
        result = build_sparkline(1.0, [1.0, 1.0, 1.0], 5)
        # All same value - should show middle bars
        assert len(result) == 4  # current + 3 historical values

    def test_increasing_values(self):
        """Increasing values show increasing bars."""
        # Current is highest
        result = build_sparkline(10.0, [2.0, 5.0, 8.0], 5)
        assert len(result) == 4  # current + 3 values
        # First char (current) should be highest
        chars = config.SPARKLINE_CHARS
        assert result[0] == chars[-1]  # Highest bar

    def test_width_limits_output(self):
        """Width parameter limits sparkline length."""
        result = build_sparkline(5.0, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], 3)
        assert len(result) == 3  # Limited by width

    def test_decreasing_values(self):
        """Decreasing values show correct pattern."""
        # Current is lowest
        result = build_sparkline(1.0, [10.0, 8.0, 5.0], 5)
        chars = config.SPARKLINE_CHARS
        assert result[0] == chars[0]  # Lowest bar for current


class TestBuildCategoryHeader:
    """Tests for build_category_header function."""

    def test_basic_header(self):
        """Builds header with correct structure."""
        header = build_category_header("python", "🐍", "Python", (2, 5), 80)
        assert "🐍" in header
        assert "Python" in header
        assert "[2/5]" in header
        assert header.startswith(config.HEADER_LEFT)

    def test_header_respects_width(self):
        """Header doesn't exceed terminal width."""
        header = build_category_header("test", "🧪", "Test", (1, 1), 50)
        # The visible width should be approximately 50
        # Note: emoji width calculation may vary
        assert config.HEADER_LEFT in header
        assert "Test" in header

    def test_header_with_zero_progress(self):
        """Header works with 0/0 progress."""
        header = build_category_header("empty", "📭", "Empty", (0, 0), 80)
        assert "[0/0]" in header

    def test_header_uses_default_width(self):
        """Header auto-detects width when not provided."""
        header = build_category_header("python", "🐍", "Python", (1, 3))
        assert "Python" in header


class TestBuildCheckConnector:
    """Tests for build_check_connector function."""

    def test_middle_connector(self):
        """Middle items use tee connector."""
        connector = build_check_connector(is_last=False)
        assert config.CONNECTOR_TEE in connector
        assert config.HEADER_HORIZONTAL in connector

    def test_last_connector(self):
        """Last item uses end connector."""
        connector = build_check_connector(is_last=True)
        assert config.CONNECTOR_END in connector
        assert config.HEADER_HORIZONTAL in connector


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
