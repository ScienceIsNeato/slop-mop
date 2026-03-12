"""Tests for WorkflowState numbered-state properties.

Verifies that every state has a position (S1–S8), a state_id label,
a human-readable next_action string, and a display_label.
"""

import pytest

from slopmop.workflow.state_machine import WorkflowState


class TestWorkflowStatePosition:
    """WorkflowState.position returns a 1-based integer for every member."""

    @pytest.mark.parametrize(
        "state, expected_position",
        [
            (WorkflowState.IDLE, 1),
            (WorkflowState.SWAB_FAILING, 2),
            (WorkflowState.SWAB_CLEAN, 3),
            (WorkflowState.SCOUR_FAILING, 4),
            (WorkflowState.SCOUR_CLEAN, 5),
            (WorkflowState.PR_OPEN, 6),
            (WorkflowState.BUFF_FAILING, 7),
            (WorkflowState.PR_READY, 8),
        ],
    )
    def test_position_mapping(
        self, state: WorkflowState, expected_position: int
    ) -> None:
        assert state.position == expected_position

    def test_all_states_have_positions(self) -> None:
        """Every enum member must have a position — no gaps allowed."""
        for state in WorkflowState:
            assert isinstance(state.position, int)
            assert 1 <= state.position <= len(WorkflowState)

    def test_positions_are_unique(self) -> None:
        positions = [s.position for s in WorkflowState]
        assert len(positions) == len(set(positions))

    def test_positions_are_consecutive(self) -> None:
        positions = sorted(s.position for s in WorkflowState)
        assert positions == list(range(1, len(WorkflowState) + 1))


class TestWorkflowStateId:
    """WorkflowState.state_id returns 'S1' through 'S8'."""

    @pytest.mark.parametrize(
        "state, expected_id",
        [
            (WorkflowState.IDLE, "S1"),
            (WorkflowState.SWAB_FAILING, "S2"),
            (WorkflowState.SWAB_CLEAN, "S3"),
            (WorkflowState.SCOUR_FAILING, "S4"),
            (WorkflowState.SCOUR_CLEAN, "S5"),
            (WorkflowState.PR_OPEN, "S6"),
            (WorkflowState.BUFF_FAILING, "S7"),
            (WorkflowState.PR_READY, "S8"),
        ],
    )
    def test_state_id(self, state: WorkflowState, expected_id: str) -> None:
        assert state.state_id == expected_id

    def test_state_id_format(self) -> None:
        """Every state_id starts with 'S' followed by an integer."""
        for state in WorkflowState:
            sid = state.state_id
            assert sid.startswith("S")
            assert sid[1:].isdigit()


class TestWorkflowStateNextAction:
    """WorkflowState.next_action returns a non-empty instruction string."""

    def test_all_states_have_next_actions(self) -> None:
        for state in WorkflowState:
            action = state.next_action
            assert isinstance(action, str)
            assert len(action) > 0

    @pytest.mark.parametrize(
        "state, expected_substring",
        [
            (WorkflowState.IDLE, "sm swab"),
            (WorkflowState.SWAB_FAILING, "sm swab"),
            (WorkflowState.SWAB_CLEAN, "commit"),
            (WorkflowState.SCOUR_FAILING, "sm swab"),
            (WorkflowState.SCOUR_CLEAN, "push"),
            (WorkflowState.PR_OPEN, "sm buff"),
            (WorkflowState.BUFF_FAILING, "sm swab"),
            (WorkflowState.PR_READY, "sm buff finalize"),
        ],
    )
    def test_next_action_contains_expected_command(
        self, state: WorkflowState, expected_substring: str
    ) -> None:
        assert expected_substring in state.next_action


class TestWorkflowStateDisplayLabel:
    """WorkflowState.display_label returns a non-empty human-readable string."""

    def test_all_states_have_display_labels(self) -> None:
        for state in WorkflowState:
            label = state.display_label
            assert isinstance(label, str)
            assert len(label) > 0

    def test_display_labels_are_unique(self) -> None:
        labels = [s.display_label for s in WorkflowState]
        assert len(labels) == len(set(labels))

    @pytest.mark.parametrize(
        "state, expected_substring",
        [
            (WorkflowState.IDLE, "Ready"),
            (WorkflowState.SWAB_FAILING, "Swab failed"),
            (WorkflowState.SWAB_CLEAN, "Swab passed"),
            (WorkflowState.SCOUR_FAILING, "Scour failed"),
            (WorkflowState.SCOUR_CLEAN, "Scour passed"),
            (WorkflowState.PR_OPEN, "PR"),
            (WorkflowState.BUFF_FAILING, "Buff"),
            (WorkflowState.PR_READY, "PR"),
        ],
    )
    def test_display_label_content(
        self, state: WorkflowState, expected_substring: str
    ) -> None:
        assert expected_substring in state.display_label


class TestWorkflowStateEnumValuesUnchanged:
    """Guard rail: enum string values must not change — they're persisted in JSON."""

    @pytest.mark.parametrize(
        "state, expected_value",
        [
            (WorkflowState.IDLE, "idle"),
            (WorkflowState.SWAB_FAILING, "swab_failing"),
            (WorkflowState.SWAB_CLEAN, "swab_clean"),
            (WorkflowState.SCOUR_FAILING, "scour_failing"),
            (WorkflowState.SCOUR_CLEAN, "scour_clean"),
            (WorkflowState.PR_OPEN, "pr_open"),
            (WorkflowState.BUFF_FAILING, "buff_failing"),
            (WorkflowState.PR_READY, "pr_ready"),
        ],
    )
    def test_enum_values_stable(
        self, state: WorkflowState, expected_value: str
    ) -> None:
        assert state.value == expected_value
