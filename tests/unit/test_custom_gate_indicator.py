"""Tests for the custom gate asterisk indicator in dynamic display."""

from slopmop.core.result import CheckResult, CheckStatus
from slopmop.reporting.dynamic import DynamicDisplay


class TestCustomGateIndicator:
    """Tests for the custom gate asterisk indicator."""

    @staticmethod
    def _make_display() -> DynamicDisplay:
        """Create a DynamicDisplay with colors disabled for deterministic output."""
        display = DynamicDisplay(quiet=True)
        display._colors_enabled = False
        return display

    def test_custom_gate_asterisk_in_completed_line(self) -> None:
        """Custom gates show an asterisk suffix on the check name."""
        display = self._make_display()
        display.register_pending_checks([("laziness:stale-docs", "laziness", True)])
        display.on_check_start("laziness:stale-docs", "laziness")
        display.on_check_complete(
            CheckResult(
                name="laziness:stale-docs",
                status=CheckStatus.PASSED,
                duration=0.5,
            )
        )

        info = display._checks["laziness:stale-docs"]
        line = display._format_completed_line(info, 120)
        assert "*stale-docs" in line

    def test_builtin_gate_no_asterisk(self) -> None:
        """Built-in gates do NOT show an asterisk."""
        display = self._make_display()
        display.register_pending_checks([("laziness:dead-code", "laziness", False)])
        display.on_check_start("laziness:dead-code", "laziness")
        display.on_check_complete(
            CheckResult(
                name="laziness:dead-code",
                status=CheckStatus.PASSED,
                duration=1.0,
            )
        )

        info = display._checks["laziness:dead-code"]
        line = display._format_completed_line(info, 120)
        assert "*dead-code" not in line
        assert "dead-code" in line

    def test_no_custom_gate_footnote_in_footer(self) -> None:
        """Footer never shows '* = custom gate' legend (removed for brevity)."""
        display = self._make_display()
        display.register_pending_checks([("laziness:stale-docs", "laziness", True)])
        display.on_check_start("laziness:stale-docs", "laziness")
        display.on_check_complete(
            CheckResult(
                name="laziness:stale-docs",
                status=CheckStatus.PASSED,
                duration=0.5,
            )
        )

        lines: list[str] = []
        display._append_footer(lines, completed=1, running=0)
        footer_text = "\n".join(lines)
        assert "custom gate" not in footer_text
