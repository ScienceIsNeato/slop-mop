"""Tests for terminal color utilities."""

import pytest

from slopmop.core.result import CheckStatus
from slopmop.reporting.display.colors import (
    STATUS_COLORS,
    Color,
    colorize,
    reset_color,
    status_color,
    supports_color,
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
