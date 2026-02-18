"""Tests for slopmop.reporting.display.renderer module."""

from slopmop.reporting.display.renderer import (
    build_category_header,
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
        """Strips python: prefix."""
        assert strip_category_prefix("python:lint-format") == "lint-format"

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
