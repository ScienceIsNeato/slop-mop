"""Functional tests for the doctor preflight → cmd_refit blocking path.

These tests exercise the real doctor infrastructure (run_checks, StateLockCheck)
with no mocks on _run_doctor_preflight.  They exist to guard against a regression
to the pre-#130 world where _run_doctor_preflight was a stub that always returned
True — a stub that would have let these tests pass for the wrong reason.

What makes these "functional" rather than "unit":
  - run_checks is not patched; the real StateLockCheck.run() executes.
  - The FAIL is triggered by a hand-crafted .slopmop/sm.lock file rather than
    by mocking DoctorStatus — so we're testing what the lock check actually
    returns, not what we told it to return.

No Docker, no external tools.  Self-contained and safe for the normal CI suite.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from slopmop.cli import refit as refit_mod


def _stale_lock_payload() -> str:
    """Minimal lock metadata that StateLockCheck will classify as stale."""
    return json.dumps(
        {
            "pid": 999999,  # virtually guaranteed to be a dead PID
            "verb": "swab",
            "started_at": 0.0,  # Unix epoch — maximally old
            "expected_done_at": 1.0,
        }
    )


def _write_stale_lock(project_root: Path) -> None:
    slopmop_dir = project_root / ".slopmop"
    slopmop_dir.mkdir(exist_ok=True)
    (slopmop_dir / "sm.lock").write_text(_stale_lock_payload(), encoding="utf-8")


class TestDoctorPreflightFunctional:
    """Real run_checks, real lock file — proves the preflight wiring is live."""

    def test_stale_lock_causes_preflight_fail(self, tmp_path: Path) -> None:
        """StateLockCheck real path: stale lock → FAIL → _run_doctor_preflight False."""
        _write_stale_lock(tmp_path)

        ok, detail = refit_mod._run_doctor_preflight(tmp_path)

        assert ok is False
        assert "doctor preflight failed" in detail
        # state.lock appears in the comma-joined names of all failing checks.
        assert "state.lock" in detail

    def test_stale_lock_blocks_cmd_refit_start_with_json_event(
        self, capsys, tmp_path: Path
    ) -> None:
        """cmd_refit --start emits preflight_doctor_failed when real doctor detects stale lock.

        This is the end-to-end regression test for the pre-#130 stub bug:
        if _run_doctor_preflight were still a no-op stub, this test would
        fail because the event would be plan_generated (or an error) rather
        than preflight_doctor_failed.
        """
        (tmp_path / ".sb_config.json").write_text("{}", encoding="utf-8")
        _write_stale_lock(tmp_path)

        args = argparse.Namespace(
            start=True,
            iterate=False,
            finish=False,
            skip=None,
            project_root=str(tmp_path),
            json_output=True,
            output_file=None,
            approve_gate=[],
            record_blocker=None,
            blocker_issue=None,
            blocker_reason=None,
        )

        exit_code = refit_mod.cmd_refit(args)

        assert exit_code == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["event"] == "preflight_doctor_failed"
        assert payload["status"] == "preflight_doctor_failed"
        assert "state.lock" in payload["details"]["doctor_detail"]
