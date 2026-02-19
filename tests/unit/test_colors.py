"""Tests for terminal color utilities."""

import pytest

from slopmop.core.result import CheckStatus
from slopmop.reporting.display.colors import (
    STATUS_COLORS,
    Color,
    ansi_rgb,
    category_header_color,
    colorize,
    reset_color,
    status_color,
    supports_color,
    supports_truecolor,
)


class TestColorConstants:
    """Tests for color constants."""

    def test_status_colors_mapping_exists(self) -> None:
        """Test all check statuses have a color mapping."""
        for status in CheckStatus:
            assert status in STATUS_COLORS

    def test_color_codes_are_escape_sequences(self) -> None:
        """Test color codes start with escape character."""
        for color in Color:
            assert color.value.startswith("\033[")


class TestSupportsColor:
    """Tests for supports_color detection."""

    def test_returns_bool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test supports_color returns a boolean."""
        # Force conditions that disable color
        monkeypatch.setenv("NO_COLOR", "1")
        assert supports_color() is False

    def test_no_color_env_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test NO_COLOR environment variable disables colors."""
        monkeypatch.setenv("NO_COLOR", "1")
        assert supports_color() is False


class TestColorize:
    """Tests for colorize function."""

    def test_colorize_with_colors_enabled(self) -> None:
        """Test colorize applies color when enabled."""
        result = colorize("test", Color.RED, colors_enabled=True)
        assert result == f"{Color.RED.value}test{Color.RESET.value}"

    def test_colorize_without_colors(self) -> None:
        """Test colorize returns plain text when disabled."""
        result = colorize("test", Color.RED, colors_enabled=False)
        assert result == "test"

    def test_colorize_empty_string(self) -> None:
        """Test colorize handles empty string."""
        result = colorize("", Color.GREEN, colors_enabled=True)
        assert result == f"{Color.GREEN.value}{Color.RESET.value}"


class TestStatusColor:
    """Tests for status_color function."""

    def test_status_color_enabled(self) -> None:
        """Test status_color returns color code when enabled."""
        result = status_color(CheckStatus.PASSED, colors_enabled=True)
        assert result == Color.GREEN.value

    def test_status_color_disabled(self) -> None:
        """Test status_color returns empty string when disabled."""
        result = status_color(CheckStatus.PASSED, colors_enabled=False)
        assert result == ""

    def test_status_color_failed(self) -> None:
        """Test failed status is red."""
        result = status_color(CheckStatus.FAILED, colors_enabled=True)
        assert result == Color.RED.value

    def test_status_color_warned(self) -> None:
        """Test warned status is yellow."""
        result = status_color(CheckStatus.WARNED, colors_enabled=True)
        assert result == Color.YELLOW.value

    def test_status_color_skipped(self) -> None:
        """Test skipped status is gray."""
        result = status_color(CheckStatus.SKIPPED, colors_enabled=True)
        assert result == Color.GRAY.value


class TestResetColor:
    """Tests for reset_color function."""

    def test_reset_color_enabled(self) -> None:
        """Test reset_color returns reset code when enabled."""
        result = reset_color(colors_enabled=True)
        assert result == Color.RESET.value

    def test_reset_color_disabled(self) -> None:
        """Test reset_color returns empty string when disabled."""
        result = reset_color(colors_enabled=False)
        assert result == ""


class TestSupportsTruecolor:
    """Tests for supports_truecolor detection."""

    def test_returns_false_when_no_color(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """True-color is off when NO_COLOR is set."""
        monkeypatch.setenv("NO_COLOR", "1")
        assert supports_truecolor() is False

    def test_returns_true_for_truecolor_colorterm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns True when COLORTERM=truecolor and the terminal is a TTY."""
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("COLORTERM", "truecolor")
        # Patch isatty so supports_color() passes
        import sys

        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        monkeypatch.delenv("TERM", raising=False)
        assert supports_truecolor() is True

    def test_returns_true_for_24bit_colorterm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns True when COLORTERM=24bit."""
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("COLORTERM", "24bit")
        import sys

        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        monkeypatch.delenv("TERM", raising=False)
        assert supports_truecolor() is True

    def test_returns_false_for_unknown_colorterm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns False when COLORTERM is set but not a recognised value."""
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("COLORTERM", "256color")
        import sys

        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        monkeypatch.delenv("TERM", raising=False)
        assert supports_truecolor() is False


class TestAnsiRgb:
    """Tests for ansi_rgb helper."""

    def test_returns_truecolor_sequence_on_truecolor_terminal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns 24-bit escape code when truecolor is supported."""
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("COLORTERM", "truecolor")
        import sys

        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        monkeypatch.delenv("TERM", raising=False)
        # #6366F1 → r=99 g=102 b=241
        result = ansi_rgb("#6366F1", Color.BRIGHT_BLUE)
        assert result == "\033[38;2;99;102;241m"

    def test_returns_truecolor_sequence_without_hash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Accepts hex strings without the leading #."""
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("COLORTERM", "truecolor")
        import sys

        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        monkeypatch.delenv("TERM", raising=False)
        result = ansi_rgb("10B981", Color.BRIGHT_GREEN)
        assert result == "\033[38;2;16;185;129m"

    def test_falls_back_to_named_color_on_basic_terminal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns fallback Color value when truecolor is unavailable."""
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("COLORTERM", raising=False)
        import sys

        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        monkeypatch.delenv("TERM", raising=False)
        result = ansi_rgb("#913364", Color.BRIGHT_MAGENTA)
        assert result == Color.BRIGHT_MAGENTA.value


class TestCategoryHeaderColor:
    """Tests for category_header_color function."""

    def test_returns_empty_when_colors_disabled(self) -> None:
        """Returns empty string when colors are disabled."""
        assert category_header_color("overconfidence", colors_enabled=False) == ""

    def test_returns_escape_sequence_when_colors_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns a non-empty ANSI escape sequence when colors are enabled."""
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("COLORTERM", raising=False)
        import sys

        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        monkeypatch.delenv("TERM", raising=False)
        result = category_header_color("overconfidence", colors_enabled=True)
        assert result.startswith("\033[")

    def test_all_known_categories_return_a_code(self) -> None:
        """Every palette category produces a non-empty code."""
        for cat in (
            "overconfidence",
            "deceptiveness",
            "laziness",
            "myopia",
            "pr",
            "general",
        ):
            assert category_header_color(cat, colors_enabled=True) != ""

    def test_unknown_category_returns_white(self) -> None:
        """Unknown category falls back to white."""
        result = category_header_color("unknown-cat", colors_enabled=True)
        assert result == Color.WHITE.value

    def test_truecolor_sequence_for_overconfidence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On truecolor terminal, overconfidence uses #6366F1 (99,102,241)."""
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("COLORTERM", "truecolor")
        import sys

        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        monkeypatch.delenv("TERM", raising=False)
        result = category_header_color("overconfidence", colors_enabled=True)
        assert result == "\033[38;2;99;102;241m"

    def test_truecolor_sequence_for_myopia(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On truecolor terminal, myopia uses #10B981 (16,185,129)."""
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("COLORTERM", "truecolor")
        import sys

        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        monkeypatch.delenv("TERM", raising=False)
        result = category_header_color("myopia", colors_enabled=True)
        assert result == "\033[38;2;16;185;129m"

    def test_fallback_sequence_for_overconfidence_on_basic_terminal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On basic ANSI terminal, overconfidence falls back to BRIGHT_BLUE."""
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("COLORTERM", raising=False)
        import sys

        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        monkeypatch.delenv("TERM", raising=False)
        result = category_header_color("overconfidence", colors_enabled=True)
        assert result == Color.BRIGHT_BLUE.value
