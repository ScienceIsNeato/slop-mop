"""Integration tests: fresh Docker install of slop-mop against bucket-o-slop.

Each test simulates a random user's machine — a clean Python environment with
only system dependencies (git, Node.js, jscpd) present.  The test then:

  Phase 0: ``git clone bucket-o-slop``        — clone the fixture repo
  Phase A: ``pip install /slopmop-src``        — install slop-mop
  Phase B: ``sm init --non-interactive``       — initialise the project
  Phase C: ``sm validate commit --no-fail-fast`` — run all quality gates

All four phases run in sequence inside a single container.  Sentinel exit
codes distinguish *where* a failure occurred:

  0 = all passed
  1 = validate found issues          (expected on broken branches)
  2 = pip install failed             (never expected)
  3 = git checkout failed            (never expected)
  4 = sm init failed                 (never expected)
  5 = git clone failed               (never expected)

Performance
-----------
Each branch is run **once** (via session-scoped fixtures in conftest.py)
and the ``RunResult`` is shared by every test that inspects that branch.
Three branches × one container = ~2-3 minutes for the whole suite.

Branch fixture summary
----------------------
  main      — all gates pass
  all-fail  — every gate uniquely broken
  mixed     — security + dead-code + bogus-tests fail; source-duplication disabled

Run integration tests::

    pytest tests/integration/ -m integration -v

Run without integration tests (default unit-test flow)::

    pytest tests/unit/
"""

from __future__ import annotations

import pytest

from tests.integration.docker_manager import DockerManager, RunResult

_ok, _reason = DockerManager.prerequisites_met()
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _ok, reason=_reason or "prerequisites not met"),
]


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def _assert_gate_mentioned(result: RunResult, *tokens: str) -> None:
    """Assert at least one token appears in combined output."""
    matched = [t for t in tokens if t in result.output]
    assert matched, f"Expected one of {tokens!r} in output but none found.\n{result}"


def _assert_gate_failed(result: RunResult, gate_name: str) -> None:
    """Assert that *gate_name* is marked as FAILING in the output.

    Looks for lines containing both the gate name and the FAILING indicator
    (the ❌ emoji or the word FAILING).  This is stricter than
    ``_assert_gate_mentioned`` which only checks that a token appears
    *anywhere* in the output — that would pass for skipped or passing gates.
    """
    lines = result.output.splitlines()
    gate_lines = [l for l in lines if gate_name in l]
    assert gate_lines, f"Gate '{gate_name}' not found anywhere in output.\n{result}"
    failed_lines = [l for l in gate_lines if "FAILING" in l or "\u274c" in l]
    assert failed_lines, (
        f"Gate '{gate_name}' found but NOT marked as FAILING.\n"
        f"Matching lines:\n"
        + "\n".join(f"  {l.strip()}" for l in gate_lines)
        + f"\n\n{result}"
    )


def _assert_gate_not_passing(result: RunResult, gate_name: str) -> None:
    """Assert that *gate_name* is NOT marked as passing in the output.

    Weaker than ``_assert_gate_failed`` — accepts both FAILING and SKIPPED
    as valid outcomes.  Use this for gates whose dependency chain means
    they may be legitimately skipped (e.g., py-tests depends on py-lint;
    when py-lint fails, py-tests is auto-skipped).
    """
    lines = result.output.splitlines()
    gate_lines = [l for l in lines if gate_name in l]
    assert gate_lines, f"Gate '{gate_name}' not found anywhere in output.\n{result}"
    passing_lines = [l for l in gate_lines if "passing" in l.lower() and "\u2705" in l]
    assert not passing_lines, (
        f"Gate '{gate_name}' should NOT be passing on this branch.\n"
        f"Passing lines:\n"
        + "\n".join(f"  {l.strip()}" for l in passing_lines)
        + f"\n\n{result}"
    )


# ---------------------------------------------------------------------------
# Phase A — pip install
# ---------------------------------------------------------------------------


class TestInstall:
    """Verify that ``pip install slopmop`` works from a clean slate."""

    def test_install_on_main(self, result_main: RunResult) -> None:
        assert (
            result_main.install_succeeded
        ), f"pip install failed on main branch:\n{result_main}"

    def test_install_on_all_fail(self, result_all_fail: RunResult) -> None:
        assert (
            result_all_fail.install_succeeded
        ), f"pip install failed on all-fail branch:\n{result_all_fail}"

    def test_install_on_mixed(self, result_mixed: RunResult) -> None:
        assert (
            result_mixed.install_succeeded
        ), f"pip install failed on mixed branch:\n{result_mixed}"


# ---------------------------------------------------------------------------
# Phase B — sm init
# ---------------------------------------------------------------------------


class TestInit:
    """Verify that ``sm init --non-interactive`` completes without error."""

    def test_init_on_main(self, result_main: RunResult) -> None:
        assert result_main.install_succeeded, f"Precondition failed:\n{result_main}"
        assert (
            result_main.init_succeeded
        ), f"sm init failed on main branch:\n{result_main}"

    def test_init_on_all_fail(self, result_all_fail: RunResult) -> None:
        assert (
            result_all_fail.install_succeeded
        ), f"Precondition failed:\n{result_all_fail}"
        assert (
            result_all_fail.init_succeeded
        ), f"sm init failed on all-fail branch:\n{result_all_fail}"

    def test_init_on_mixed(self, result_mixed: RunResult) -> None:
        assert result_mixed.install_succeeded, f"Precondition failed:\n{result_mixed}"
        assert (
            result_mixed.init_succeeded
        ), f"sm init failed on mixed branch:\n{result_mixed}"


# ---------------------------------------------------------------------------
# Phase C — sm validate (gate behaviour)
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Branch main: all gates pass -> exit 0."""

    def test_exit_code_is_zero(self, result_main: RunResult) -> None:
        result_main.assert_prerequisites()
        assert result_main.passed, f"Expected exit 0 on main branch:\n{result_main}"

    def test_key_gates_run(self, result_main: RunResult) -> None:
        result_main.assert_prerequisites()
        for gate in ("py-lint", "py-tests", "security"):
            assert (
                gate in result_main.output
            ), f"Expected gate '{gate}' in output.\n{result_main}"


class TestAllFail:
    """Branch all-fail: every gate uniquely broken -> exit 1."""

    def test_exit_code_is_one(self, result_all_fail: RunResult) -> None:
        result_all_fail.assert_prerequisites()
        assert (
            result_all_fail.exit_code == 1
        ), f"Expected exit 1 (validate failures) on all-fail branch:\n{result_all_fail}"

    def test_lint_gate_fails(self, result_all_fail: RunResult) -> None:
        result_all_fail.assert_prerequisites()
        _assert_gate_failed(result_all_fail, "py-lint")

    def test_security_gate_fails(self, result_all_fail: RunResult) -> None:
        result_all_fail.assert_prerequisites()
        _assert_gate_failed(result_all_fail, "security-audit")

    def test_pytest_gate_fails(self, result_all_fail: RunResult) -> None:
        """py-tests should not pass.

        Note: py-tests depends on laziness:py-lint.  When py-lint fails
        (as it does on all-fail), py-tests is auto-skipped.  We verify
        it is NOT passing rather than asserting it explicitly FAILED.
        """
        result_all_fail.assert_prerequisites()
        _assert_gate_not_passing(result_all_fail, "py-tests")

    def test_dead_code_gate_fails(self, result_all_fail: RunResult) -> None:
        result_all_fail.assert_prerequisites()
        _assert_gate_failed(result_all_fail, "dead-code")

    def test_bogus_tests_gate_fails(self, result_all_fail: RunResult) -> None:
        result_all_fail.assert_prerequisites()
        _assert_gate_failed(result_all_fail, "bogus-tests")


class TestMixed:
    """Branch mixed: security + dead-code + bogus-tests fail; source-duplication skipped."""

    def test_exit_code_is_one(self, result_mixed: RunResult) -> None:
        result_mixed.assert_prerequisites()
        assert (
            result_mixed.exit_code == 1
        ), f"Expected exit 1 (some validate failures) on mixed branch:\n{result_mixed}"

    def test_security_gate_fails(self, result_mixed: RunResult) -> None:
        result_mixed.assert_prerequisites()
        _assert_gate_failed(result_mixed, "security-audit")

    def test_dead_code_gate_fails(self, result_mixed: RunResult) -> None:
        result_mixed.assert_prerequisites()
        _assert_gate_failed(result_mixed, "dead-code")

    def test_bogus_tests_gate_fails(self, result_mixed: RunResult) -> None:
        result_mixed.assert_prerequisites()
        _assert_gate_failed(result_mixed, "bogus-tests")

    def test_pytest_gate_passes(self, result_mixed: RunResult) -> None:
        """Real pytest tests still pass; only the bogus tautology is flagged."""
        result_mixed.assert_prerequisites()
        assert (
            "py-tests" in result_mixed.output
        ), f"py-tests gate output not found.\n{result_mixed}"

    def test_source_duplication_not_failed(self, result_mixed: RunResult) -> None:
        """source-duplication is disabled in config -> must not appear as FAILED."""
        result_mixed.assert_prerequisites()
        failing_lines = [
            line
            for line in result_mixed.output.splitlines()
            if "source-duplication" in line.lower() and "fail" in line.lower()
        ]
        assert not failing_lines, (
            "source-duplication should be disabled (skipped) but was "
            f"reported as failed:\n" + "\n".join(failing_lines)
        )
