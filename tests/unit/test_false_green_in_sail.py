"""A verdict nobody computed is not a clean verdict.

`sail` printed "All CI green, no unresolved threads" over a PR carrying five
of them (#322). It ran the review-thread gate and read the exit status — but a
gate disabled in the repo config also exits 0, so nothing had queried the
threads and nothing said so.

Same shape as the semgrep gate reading an exit status instead of a report, and
the worktree run reporting all-passed with its suite skipped.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import pytest

from slopmop.checks.security import SecurityLocalCheck
from slopmop.checks.timeouts import SLOW_TOOL_TIMEOUT
from slopmop.cli.sail import _FEEDBACK_GATE, _feedback_gate_unavailable


def _write_sb_config(root: Path, config: Dict[str, Any]) -> None:
    (root / ".sb_config.json").write_text(json.dumps(config), encoding="utf-8")


class TestFeedbackGateAvailability:
    def test_enabled_gate_can_answer(self, tmp_path: Path) -> None:
        _write_sb_config(
            tmp_path,
            {
                "myopia": {
                    "enabled": True,
                    "gates": {"ignored-feedback": {"enabled": True}},
                }
            },
        )
        assert _feedback_gate_unavailable(tmp_path) == ""

    def test_disabled_gate_is_reported_unavailable(self, tmp_path: Path) -> None:
        """The reported case: disabled gate exits 0 and sail called it clean."""
        _write_sb_config(
            tmp_path,
            {
                "myopia": {
                    "enabled": True,
                    "gates": {"ignored-feedback": {"enabled": False}},
                }
            },
        )
        reason = _feedback_gate_unavailable(tmp_path)
        assert reason, "a disabled gate must not read as 'threads are clean'"
        assert "ignored-feedback" in reason or "disabled" in reason

    def test_disabled_category_is_reported_unavailable(self, tmp_path: Path) -> None:
        _write_sb_config(
            tmp_path,
            {
                "myopia": {
                    "enabled": False,
                    "gates": {"ignored-feedback": {"enabled": True}},
                }
            },
        )
        assert _feedback_gate_unavailable(tmp_path) != ""

    def test_unreadable_config_holds_rather_than_assuming(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Not knowing is a hold, not a pass."""
        import slopmop.sm as sm

        def _boom(_root):
            raise OSError("config is unreadable")

        monkeypatch.setattr(sm, "load_config", _boom)
        assert _feedback_gate_unavailable(tmp_path) != ""

    def test_the_gate_name_is_the_one_sail_runs(self) -> None:
        """A drifting name would silently make the check vacuous."""
        assert _FEEDBACK_GATE == "myopia:ignored-feedback"


class TestSailWillNotClaimUncheckedThreads:
    @staticmethod
    def _args() -> argparse.Namespace:
        return argparse.Namespace(verbose=False)

    def test_pr_open_holds_when_the_gate_cannot_run(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        from slopmop.cli import sail as sail_mod

        monkeypatch.setattr(
            sail_mod, "_feedback_gate_unavailable", lambda _root: "it is disabled"
        )
        # If the hold works, scour is never reached.
        import slopmop.cli as cli_mod

        monkeypatch.setattr(
            cli_mod, "cmd_scour", lambda _a: pytest.fail("ran the gate anyway")
        )

        assert sail_mod._sail_pr_open(self._args(), tmp_path) == 1
        out = capsys.readouterr().out
        assert "HOLD" in out
        assert "did not run" in out

    def test_pr_ready_says_threads_unverified_instead_of_clean(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """CI green is true; 'no unresolved threads' would not be."""
        from slopmop.cli import sail as sail_mod

        monkeypatch.setattr(sail_mod, "_get_pr_number", lambda _root: 1)
        monkeypatch.setattr(sail_mod, "write_sail_mode", lambda *_a: None)
        monkeypatch.setattr(
            sail_mod, "_feedback_gate_unavailable", lambda _root: "it is disabled"
        )
        import slopmop.cli as cli_mod

        monkeypatch.setattr(cli_mod, "cmd_buff", lambda _a: 0)

        assert sail_mod._sail_pr_ready(self._args(), tmp_path) == 0
        out = capsys.readouterr().out
        assert "UNVERIFIED" in out
        assert "no unresolved threads" not in out
        assert "sm buff inspect" in out

    def test_pr_ready_still_claims_clean_when_the_gate_ran(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """The fix must not make every run say 'unverified'."""
        from slopmop.cli import sail as sail_mod

        monkeypatch.setattr(sail_mod, "_get_pr_number", lambda _root: 1)
        monkeypatch.setattr(sail_mod, "write_sail_mode", lambda *_a: None)
        monkeypatch.setattr(sail_mod, "_feedback_gate_unavailable", lambda _root: "")
        import slopmop.cli as cli_mod

        monkeypatch.setattr(cli_mod, "cmd_buff", lambda _a: 0)

        assert sail_mod._sail_pr_ready(self._args(), tmp_path) == 0
        out = capsys.readouterr().out
        assert "no unresolved threads" in out
        assert "UNVERIFIED" not in out


class TestScannerBudgetIsConfigurable:
    """#323 — the same commit scans in 8s locally and was killed at 120s in CI."""

    def test_default_is_unchanged(self) -> None:
        assert SecurityLocalCheck({})._scanner_timeout() == SLOW_TOOL_TIMEOUT

    def test_a_repo_can_raise_it(self) -> None:
        assert SecurityLocalCheck({"scanner_timeout": 300})._scanner_timeout() == 300

    def test_nonsense_falls_back_rather_than_crashing(self) -> None:
        for bad in ("abc", None, 0, -5, [1]):
            assert (
                SecurityLocalCheck({"scanner_timeout": bad})._scanner_timeout()
                == SLOW_TOOL_TIMEOUT
            ), bad

    def test_it_is_declared_in_the_schema(self) -> None:
        names = {f.name for f in SecurityLocalCheck({}).config_schema}
        assert "scanner_timeout" in names

    def test_the_timeout_message_quotes_the_configured_budget(self) -> None:
        """A message naming 120s under a 300s budget sends people the wrong way."""
        from unittest.mock import MagicMock, patch

        check = SecurityLocalCheck({"scanner_timeout": 300})
        result = MagicMock()
        result.timed_out = True
        result.success = False
        result.stdout = ""
        result.stderr = ""
        result.output = ""
        result.returncode = -1

        with patch.object(check, "_run_command", return_value=result):
            sub = check._run_semgrep(".")

        assert sub.passed is False
        assert "300s" in sub.findings
