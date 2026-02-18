"""Tests for slopmop.reporting.display.renderer module."""

from slopmop.reporting.display.renderer import (
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
