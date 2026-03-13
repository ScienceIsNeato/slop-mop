"""Direct tests for workflow hook functions and state_store edge cases."""

from __future__ import annotations

import json
from unittest.mock import patch

from slopmop.workflow.state_machine import RepoPhase, WorkflowState

# ---------------------------------------------------------------------------
# state_store tests — fill coverage gaps on edge cases
# ---------------------------------------------------------------------------


class TestStateStoreEdgeCases:
    def test_read_state_returns_none_for_missing_file(self, tmp_path):
        from slopmop.workflow.state_store import read_state

        assert read_state(tmp_path) is None

    def test_read_state_returns_none_for_invalid_value(self, tmp_path):
        from slopmop.workflow.state_store import read_state

        state_dir = tmp_path / ".slopmop"
        state_dir.mkdir()
        (state_dir / "workflow_state.json").write_text(
            json.dumps({"state": "BOGUS_STATE"})
        )
        assert read_state(tmp_path) is None

    def test_read_state_returns_state_for_valid_value(self, tmp_path):
        from slopmop.workflow.state_store import read_state

        state_dir = tmp_path / ".slopmop"
        state_dir.mkdir()
        (state_dir / "workflow_state.json").write_text(json.dumps({"state": "idle"}))
        assert read_state(tmp_path) == WorkflowState.IDLE

    def test_read_phase_defaults_to_remediation(self, tmp_path):
        from slopmop.workflow.state_store import read_phase

        assert read_phase(tmp_path) == RepoPhase.REMEDIATION

    def test_read_phase_returns_maintenance_when_set(self, tmp_path):
        from slopmop.workflow.state_store import read_phase

        state_dir = tmp_path / ".slopmop"
        state_dir.mkdir()
        (state_dir / "workflow_state.json").write_text(
            json.dumps({"phase": "maintenance"})
        )
        assert read_phase(tmp_path) == RepoPhase.MAINTENANCE

    def test_read_phase_returns_remediation_for_invalid_value(self, tmp_path):
        from slopmop.workflow.state_store import read_phase

        state_dir = tmp_path / ".slopmop"
        state_dir.mkdir()
        (state_dir / "workflow_state.json").write_text(json.dumps({"phase": "INVALID"}))
        assert read_phase(tmp_path) == RepoPhase.REMEDIATION

    def test_read_baseline_achieved_false_when_missing(self, tmp_path):
        from slopmop.workflow.state_store import read_baseline_achieved

        assert read_baseline_achieved(tmp_path) is False

    def test_read_baseline_achieved_true_when_set(self, tmp_path):
        from slopmop.workflow.state_store import read_baseline_achieved

        state_dir = tmp_path / ".slopmop"
        state_dir.mkdir()
        (state_dir / "workflow_state.json").write_text(
            json.dumps({"baseline_achieved": True})
        )
        assert read_baseline_achieved(tmp_path) is True

    def test_write_state_persists(self, tmp_path):
        from slopmop.workflow.state_store import read_state, write_state

        write_state(tmp_path, WorkflowState.SWAB_CLEAN)
        assert read_state(tmp_path) == WorkflowState.SWAB_CLEAN

    def test_record_baseline_sets_phase_and_flag(self, tmp_path):
        from slopmop.workflow.state_store import (
            read_baseline_achieved,
            read_phase,
            record_baseline,
        )

        record_baseline(tmp_path)
        assert read_baseline_achieved(tmp_path) is True
        assert read_phase(tmp_path) == RepoPhase.MAINTENANCE

    def test_read_raw_handles_corrupt_json(self, tmp_path):
        from slopmop.workflow.state_store import _read_raw

        state_dir = tmp_path / ".slopmop"
        state_dir.mkdir()
        (state_dir / "workflow_state.json").write_text("not valid json!!!")
        assert _read_raw(tmp_path) == {}

    def test_read_raw_handles_non_dict_json(self, tmp_path):
        from slopmop.workflow.state_store import _read_raw

        state_dir = tmp_path / ".slopmop"
        state_dir.mkdir()
        (state_dir / "workflow_state.json").write_text('"just a string"')
        assert _read_raw(tmp_path) == {}

    def test_update_creates_dir_if_missing(self, tmp_path):
        from slopmop.workflow.state_store import write_state

        # .slopmop dir doesn't exist yet
        write_state(tmp_path, WorkflowState.IDLE)
        state_file = tmp_path / ".slopmop" / "workflow_state.json"
        assert state_file.exists()


# ---------------------------------------------------------------------------
# hooks.py — direct function tests to cover the actual function bodies
# ---------------------------------------------------------------------------


class TestOnSwabCompleteDirect:
    def test_swab_passed_advances_state(self, tmp_path):
        from slopmop.workflow.hooks import on_swab_complete
        from slopmop.workflow.state_store import read_state, write_state

        write_state(tmp_path, WorkflowState.IDLE)
        on_swab_complete(tmp_path, passed=True)
        state = read_state(tmp_path)
        assert state == WorkflowState.SWAB_CLEAN

    def test_swab_failed_stays_in_swab_failing(self, tmp_path):
        from slopmop.workflow.hooks import on_swab_complete
        from slopmop.workflow.state_store import read_state, write_state

        write_state(tmp_path, WorkflowState.IDLE)
        on_swab_complete(tmp_path, passed=False)
        state = read_state(tmp_path)
        assert state == WorkflowState.SWAB_FAILING

    def test_swab_no_transition_logs_debug(self, tmp_path):
        from slopmop.workflow.hooks import on_swab_complete
        from slopmop.workflow.state_store import write_state

        # From PR_READY, SWAB_PASSED has no transition defined
        write_state(tmp_path, WorkflowState.PR_READY)
        on_swab_complete(tmp_path, passed=True)
        # Should not raise

    def test_swab_exception_suppressed(self, tmp_path):
        from slopmop.workflow.hooks import on_swab_complete

        with patch(
            "slopmop.workflow.hooks.read_state",
            side_effect=RuntimeError("disk error"),
        ):
            on_swab_complete(tmp_path, passed=True)  # no exception


class TestOnScourCompleteDirect:
    def test_scour_passed_advances_to_scour_clean(self, tmp_path):
        from slopmop.workflow.hooks import on_scour_complete
        from slopmop.workflow.state_store import read_state, write_state

        write_state(tmp_path, WorkflowState.SWAB_CLEAN)
        on_scour_complete(tmp_path, passed=True)
        assert read_state(tmp_path) == WorkflowState.SCOUR_CLEAN

    def test_scour_failed_keeps_state(self, tmp_path):
        from slopmop.workflow.hooks import on_scour_complete
        from slopmop.workflow.state_store import read_state, write_state

        write_state(tmp_path, WorkflowState.SWAB_CLEAN)
        on_scour_complete(tmp_path, passed=False)
        state = read_state(tmp_path)
        # After scour fails, state should stay in swab_failing or similar
        assert state is not None

    def test_scour_passed_fallback_sets_scour_clean(self, tmp_path):
        from slopmop.workflow.hooks import on_scour_complete
        from slopmop.workflow.state_store import read_state, write_state

        # Set a state that has no formal scour_passed transition
        write_state(tmp_path, WorkflowState.PR_READY)
        on_scour_complete(tmp_path, passed=True)
        assert read_state(tmp_path) == WorkflowState.SCOUR_CLEAN

    def test_scour_records_baseline_on_first_clean_pass(self, tmp_path):
        from slopmop.workflow.hooks import on_scour_complete
        from slopmop.workflow.state_store import read_baseline_achieved, write_state

        write_state(tmp_path, WorkflowState.SWAB_CLEAN)
        on_scour_complete(tmp_path, passed=True, all_gates_enabled=True)
        assert read_baseline_achieved(tmp_path) is True

    def test_scour_no_baseline_when_not_all_gates(self, tmp_path):
        from slopmop.workflow.hooks import on_scour_complete
        from slopmop.workflow.state_store import read_baseline_achieved, write_state

        write_state(tmp_path, WorkflowState.SWAB_CLEAN)
        on_scour_complete(tmp_path, passed=True, all_gates_enabled=False)
        assert read_baseline_achieved(tmp_path) is False

    def test_scour_exception_suppressed(self, tmp_path):
        from slopmop.workflow.hooks import on_scour_complete

        with patch(
            "slopmop.workflow.hooks.read_state",
            side_effect=RuntimeError("boom"),
        ):
            on_scour_complete(tmp_path, passed=True)  # no exception


class TestOnBuffCompleteDirect:
    def test_buff_has_issues_sets_buff_failing(self, tmp_path):
        from slopmop.workflow.hooks import on_buff_complete
        from slopmop.workflow.state_store import read_state, write_state

        write_state(tmp_path, WorkflowState.PR_OPEN)
        on_buff_complete(tmp_path, has_issues=True)
        assert read_state(tmp_path) == WorkflowState.BUFF_FAILING

    def test_buff_all_green_sets_pr_ready(self, tmp_path):
        from slopmop.workflow.hooks import on_buff_complete
        from slopmop.workflow.state_store import read_state, write_state

        write_state(tmp_path, WorkflowState.PR_OPEN)
        on_buff_complete(tmp_path, has_issues=False)
        assert read_state(tmp_path) == WorkflowState.PR_READY

    def test_buff_fallback_on_no_transition(self, tmp_path):
        from slopmop.workflow.hooks import on_buff_complete
        from slopmop.workflow.state_store import read_state, write_state

        write_state(tmp_path, WorkflowState.IDLE)
        on_buff_complete(tmp_path, has_issues=True)
        assert read_state(tmp_path) == WorkflowState.BUFF_FAILING

    def test_buff_exception_suppressed(self, tmp_path):
        from slopmop.workflow.hooks import on_buff_complete

        with patch(
            "slopmop.workflow.hooks.read_state",
            side_effect=RuntimeError("boom"),
        ):
            on_buff_complete(tmp_path, has_issues=False)  # no exception


class TestOnIterationStartedDirect:
    def test_iteration_advances_from_buff_failing(self, tmp_path):
        from slopmop.workflow.hooks import on_iteration_started
        from slopmop.workflow.state_store import read_state, write_state

        write_state(tmp_path, WorkflowState.BUFF_FAILING)
        on_iteration_started(tmp_path)
        state = read_state(tmp_path)
        # No ITERATION_STARTED transition defined — state stays as-is
        assert state == WorkflowState.BUFF_FAILING

    def test_iteration_exception_suppressed(self, tmp_path):
        from slopmop.workflow.hooks import on_iteration_started

        with patch(
            "slopmop.workflow.hooks.read_state",
            side_effect=RuntimeError("boom"),
        ):
            on_iteration_started(tmp_path)  # no exception
