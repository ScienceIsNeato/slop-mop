"""Tests for wall-clock time budget with budget-aware dual-lane scheduling."""

from unittest.mock import MagicMock

from slopmop.core.executor import CheckExecutor
from slopmop.core.registry import CheckRegistry
from slopmop.core.result import CheckStatus, SkipReason
from tests.unit.test_executor import make_mock_check_class


class TestSwabbingTimeBudget:
    """Tests for wall-clock time budget with budget-aware dual-lane scheduling.

    The executor uses wall-clock time to decide when to stop scheduling
    new gates.  Gates without timing history always run. Under budget,
    one timed slot is reserved for fast checks, while remaining timed
    slots are packed with heavier checks that fit projected time.

    Integration tests that verify actual budget expiry use checks that
    sleep >1s (since swabbing_timeout is int, minimum positive is 1).
    """

    def _make_registry(self, *check_specs):
        """Build a registry with named checks.

        Each spec is (name, duration, status).
        """
        registry = CheckRegistry()
        for name, duration, status in check_specs:
            cls = make_mock_check_class(name, status=status, duration=duration)
            registry.register(cls)
        return registry

    # ── Basic budget behaviour ────────────────────────────────────────

    def test_no_budget_runs_all(self, tmp_path):
        """Without swabbing_timeout, all checks run regardless of timings."""
        registry = self._make_registry(
            ("fast", 0.01, CheckStatus.PASSED),
            ("slow", 0.01, CheckStatus.PASSED),
        )
        timings = {"overconfidence:fast": 2.0, "overconfidence:slow": 50.0}

        executor = CheckExecutor(registry=registry, fail_fast=False)
        summary = executor.run_checks(
            str(tmp_path),
            ["overconfidence:fast", "overconfidence:slow"],
            swabbing_timeout=None,
            timings=timings,
        )
        assert summary.total_checks == 2
        assert summary.passed == 2

    def test_zero_budget_disables_limit(self, tmp_path):
        """swabbing_timeout=0 means no limit — all gates run."""
        registry = self._make_registry(
            ("check", 0.01, CheckStatus.PASSED),
        )
        timings = {"overconfidence:check": 999.0}

        executor = CheckExecutor(registry=registry, fail_fast=False)
        summary = executor.run_checks(
            str(tmp_path),
            ["overconfidence:check"],
            swabbing_timeout=0,
            timings=timings,
        )
        assert summary.passed == 1

    def test_negative_budget_disables_limit(self, tmp_path):
        """swabbing_timeout=-1 means no limit — all gates run."""
        registry = self._make_registry(
            ("check", 0.01, CheckStatus.PASSED),
        )
        timings = {"overconfidence:check": 999.0}

        executor = CheckExecutor(registry=registry, fail_fast=False)
        summary = executor.run_checks(
            str(tmp_path),
            ["overconfidence:check"],
            swabbing_timeout=-1,
            timings=timings,
        )
        assert summary.passed == 1

    def test_empty_timings_runs_all(self, tmp_path):
        """When timings dict is empty, every gate lacks history → all run."""
        registry = self._make_registry(
            ("a", 0.01, CheckStatus.PASSED),
            ("b", 0.01, CheckStatus.PASSED),
        )

        executor = CheckExecutor(registry=registry, fail_fast=False)
        summary = executor.run_checks(
            str(tmp_path),
            ["overconfidence:a", "overconfidence:b"],
            swabbing_timeout=1,
            timings={},
        )
        assert summary.passed == 2

    def test_gates_without_timing_data_always_run(self, tmp_path):
        """Gates with no historical timing always run (to establish a baseline)."""
        registry = self._make_registry(
            ("known", 0.01, CheckStatus.PASSED),
            ("unknown", 0.01, CheckStatus.PASSED),
        )
        timings = {"overconfidence:known": 2.0}

        executor = CheckExecutor(registry=registry, fail_fast=False)
        summary = executor.run_checks(
            str(tmp_path),
            ["overconfidence:known", "overconfidence:unknown"],
            swabbing_timeout=5,
            timings=timings,
        )

        results = {r.name: r for r in summary.results}
        assert results["unknown"].passed
        assert results["known"].passed

    # ── Wall-clock budget expiry (integration) ────────────────────────

    def test_budget_expiry_skips_pending_timed_gate(self, tmp_path):
        """Blocker sleeps 1.1s > budget 1s; pending timed gate skipped.

        max_workers=1 forces serial: blocker fills the slot, takes 1.1s
        real time.  When it finishes, elapsed > 1s budget → victim
        (which has timing data) is budget-skipped.
        """
        registry = self._make_registry(
            ("blocker", 1.1, CheckStatus.PASSED),
            ("victim", 0.01, CheckStatus.PASSED),
        )
        timings = {
            # Fast-lane should pick blocker first; it then overruns budget.
            "overconfidence:blocker": 0.1,
            "overconfidence:victim": 10.0,
        }

        executor = CheckExecutor(registry=registry, fail_fast=False, max_workers=1)
        summary = executor.run_checks(
            str(tmp_path),
            ["overconfidence:blocker", "overconfidence:victim"],
            swabbing_timeout=1,
            timings=timings,
        )

        results = {r.name: r for r in summary.results}
        # MockCheck.run() returns short name; budget-skip uses full name
        assert results["blocker"].passed
        victim = results["overconfidence:victim"]
        assert victim.skip_reason == SkipReason.TIME_BUDGET
        assert "budget 1s expired" in victim.output
        assert "estimated 10.0s" in victim.output

    def test_untimed_gate_runs_after_budget_expires(self, tmp_path):
        """Budget expires but untimed gate still runs; timed gate skipped."""
        registry = self._make_registry(
            ("blocker", 1.1, CheckStatus.PASSED),
            ("untimed", 0.01, CheckStatus.PASSED),
            ("timed-victim", 0.01, CheckStatus.PASSED),
        )
        timings = {
            # Fast-lane should pick blocker first; it then overruns budget.
            "overconfidence:blocker": 0.1,
            "overconfidence:timed-victim": 5.0,
            # "untimed" has NO entry → always runs
        }

        executor = CheckExecutor(registry=registry, fail_fast=False, max_workers=1)
        summary = executor.run_checks(
            str(tmp_path),
            [
                "overconfidence:blocker",
                "overconfidence:untimed",
                "overconfidence:timed-victim",
            ],
            swabbing_timeout=1,
            timings=timings,
        )

        results = {r.name: r for r in summary.results}
        # MockCheck.run() returns short name; budget-skip uses full name
        assert results["blocker"].passed
        assert results["untimed"].passed  # untimed always runs
        assert (
            results["overconfidence:timed-victim"].skip_reason == SkipReason.TIME_BUDGET
        )

    # ── _select_gates_for_submission unit tests ───────────────────────

    def test_select_no_budget_returns_all_longest_first(self):
        """Without budget, all ready gates returned sorted longest-first."""
        executor = CheckExecutor(fail_fast=False)
        timings = {"a": 1.0, "b": 10.0, "c": 5.0}

        result = executor._select_gates_for_submission(
            ready=["a", "b", "c"],
            pending={"a", "b", "c"},
            completed=set(),
            futures={},
            timings=timings,
            budget_active=False,
            budget_expired=False,
            budget_elapsed=0.0,
            swabbing_timeout=None,
        )
        assert result == ["b", "c", "a"]

    def test_select_budget_expired_skips_timed_returns_untimed(self):
        """When budget expired, timed gates skipped, untimed returned."""
        executor = CheckExecutor(fail_fast=False)
        pending = {"timed1", "timed2", "untimed1"}
        completed: set = set()
        timings = {"timed1": 5.0, "timed2": 10.0}

        result = executor._select_gates_for_submission(
            ready=["timed1", "timed2", "untimed1"],
            pending=pending,
            completed=completed,
            futures={},
            timings=timings,
            budget_active=True,
            budget_expired=True,
            budget_elapsed=25.0,
            swabbing_timeout=20,
        )

        assert result == ["untimed1"]
        assert "timed1" not in pending
        assert "timed2" not in pending
        # Budget-skipped gates added to completed for dependency resolution
        assert "timed1" in completed
        assert "timed2" in completed
        assert executor._results["timed1"].skip_reason == SkipReason.TIME_BUDGET
        assert executor._results["timed2"].skip_reason == SkipReason.TIME_BUDGET

    def test_select_budget_expired_output_format(self):
        """Budget-skip output contains wall-clock format fields."""
        executor = CheckExecutor(fail_fast=False)
        pending = {"gate1"}
        timings = {"gate1": 15.0}

        executor._select_gates_for_submission(
            ready=["gate1"],
            pending=pending,
            completed=set(),
            futures={},
            timings=timings,
            budget_active=True,
            budget_expired=True,
            budget_elapsed=22.5,
            swabbing_timeout=20,
        )

        output = executor._results["gate1"].output
        assert "estimated 15.0s" in output
        assert "budget 20s expired" in output
        assert "22.5s wall-clock" in output

    def test_select_budget_dual_lane_fast_plus_heavy_pack(self):
        """Under budget, pick one fast gate then pack heavy lanes."""
        executor = CheckExecutor(fail_fast=False, max_workers=4)
        timings = {"a": 10.0, "b": 8.0, "c": 5.0, "d": 3.0, "e": 1.0}

        result = executor._select_gates_for_submission(
            ready=["a", "b", "c", "d", "e"],
            pending={"a", "b", "c", "d", "e"},
            completed=set(),
            futures={},
            timings=timings,
            budget_active=True,
            budget_expired=False,
            budget_elapsed=0.0,
            swabbing_timeout=60,
        )

        assert len(result) == 4
        assert result == ["e", "a", "b", "c"]

    def test_select_with_untimed_priority_then_fast_plus_heavy(self):
        """Untimed first; timed uses fast lane + heavy packing."""
        executor = CheckExecutor(fail_fast=False, max_workers=4)
        timings = {"t1": 10.0, "t2": 5.0, "t3": 1.0}

        result = executor._select_gates_for_submission(
            ready=["t1", "t2", "t3", "u1", "u2"],
            pending={"t1", "t2", "t3", "u1", "u2"},
            completed=set(),
            futures={},
            timings=timings,
            budget_active=True,
            budget_expired=False,
            budget_elapsed=0.0,
            swabbing_timeout=60,
        )

        # 2 untimed fill 2 slots; timed picks fast lane t3 then heavy lane t1.
        assert result == ["u1", "u2", "t3", "t1"]

    def test_select_single_slot_takes_fastest(self):
        """With 1 available slot, submit the fastest timed gate."""
        executor = CheckExecutor(fail_fast=False, max_workers=4)
        timings = {"a": 10.0, "b": 1.0}

        mock_futures = {MagicMock(): f"f{i}" for i in range(3)}

        result = executor._select_gates_for_submission(
            ready=["a", "b"],
            pending={"a", "b"},
            completed=set(),
            futures=mock_futures,
            timings=timings,
            budget_active=True,
            budget_expired=False,
            budget_elapsed=0.0,
            swabbing_timeout=60,
        )

        assert result == ["b"]

    def test_select_respects_projected_budget_with_inflight_work(self):
        """Do not submit timed gates when projected budget has no room."""
        executor = CheckExecutor(fail_fast=False, max_workers=2)
        timings = {"running-heavy": 9.0, "candidate": 2.0}

        running_future = MagicMock()
        futures = {running_future: "running-heavy"}

        result = executor._select_gates_for_submission(
            ready=["candidate"],
            pending={"candidate"},
            completed=set(),
            futures=futures,
            timings=timings,
            budget_active=True,
            budget_expired=False,
            budget_elapsed=2.0,
            swabbing_timeout=10,
        )

        assert result == []

    def test_select_no_slots_returns_empty(self):
        """When all slots are busy, no gates submitted."""
        executor = CheckExecutor(fail_fast=False, max_workers=2)
        timings = {"a": 10.0}

        mock_futures = {MagicMock(): f"f{i}" for i in range(2)}

        result = executor._select_gates_for_submission(
            ready=["a"],
            pending={"a"},
            completed=set(),
            futures=mock_futures,
            timings=timings,
            budget_active=True,
            budget_expired=False,
            budget_elapsed=0.0,
            swabbing_timeout=60,
        )

        assert result == []

    def test_select_two_timed_gates_two_slots(self):
        """With 2 slots and 2 timed gates, select shortest-first order."""
        executor = CheckExecutor(fail_fast=False, max_workers=2)
        timings = {"heavy": 10.0, "light": 1.0}

        result = executor._select_gates_for_submission(
            ready=["heavy", "light"],
            pending={"heavy", "light"},
            completed=set(),
            futures={},
            timings=timings,
            budget_active=True,
            budget_expired=False,
            budget_elapsed=0.0,
            swabbing_timeout=60,
        )

        assert len(result) == 2
        assert result[0] == "light"
        assert result[1] == "heavy"

    def test_select_untimed_does_not_exceed_available_slots(self):
        """Untimed submissions are capped to free worker slots."""
        executor = CheckExecutor(fail_fast=False, max_workers=2)

        result = executor._select_gates_for_submission(
            ready=["u1", "u2", "u3"],
            pending={"u1", "u2", "u3"},
            completed=set(),
            futures={},
            timings={},
            budget_active=True,
            budget_expired=False,
            budget_elapsed=0.0,
            swabbing_timeout=60,
        )

        assert result == ["u1", "u2"]

    # ── _record_budget_skips unit test ────────────────────────────────

    def test_record_budget_skips_creates_results(self):
        """_record_budget_skips records results with correct format."""
        executor = CheckExecutor(fail_fast=False)
        completed = []
        executor._on_check_complete = completed.append

        executor._record_budget_skips(
            names=["gate-a", "gate-b"],
            timings={"gate-a": 15.0, "gate-b": 8.5},
            elapsed=22.5,
            swabbing_timeout=20,
        )

        assert len(executor._results) == 2
        assert executor._results["gate-a"].skip_reason == SkipReason.TIME_BUDGET
        assert "estimated 15.0s" in executor._results["gate-a"].output
        assert "budget 20s expired" in executor._results["gate-a"].output
        assert "22.5s wall-clock" in executor._results["gate-a"].output
        assert executor._results["gate-b"].skip_reason == SkipReason.TIME_BUDGET
        assert len(completed) == 2
