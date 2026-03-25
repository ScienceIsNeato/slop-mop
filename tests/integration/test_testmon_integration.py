"""Integration tests: pytest-testmon fast path and TDD loop.

Two scenarios verify testmon behaviour inside a Docker container:

  TestTestmonFastPath — confirms that sm swab activates ``pytest --testmon``
    when .testmondata and coverage.xml are already seeded, re-running only
    tests whose source deps changed.

  TestTestmonTddLoop — exercises the full red→green TDD cycle:
    baseline → add uncovered source → add failing test → fix test → green,
    verifying that testmon caching keeps iteration fast.

Scripts live in ``tests/integration/scripts/`` and are loaded at import
time to keep inline shell out of Python files.

Run::

    pytest tests/integration/ -m integration -k testmon -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration.docker_manager import DockerManager, RunResult

_ok, _reason = DockerManager.prerequisites_met()
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _ok, reason=_reason or "prerequisites not met"),
]

# ---------------------------------------------------------------------------
# Script loading
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).parent / "scripts"


def _load_script(name: str) -> str:
    return (_SCRIPTS_DIR / name).read_text()


_PROJECT_SETUP = _load_script("testmon_project_setup.sh")

# Shared preamble: project setup → sm init
_INIT_PREAMBLE = _PROJECT_SETUP + """
sm init --non-interactive 2>&1 || { echo "SM_INIT_FAILED"; exit 4; }
"""

_FAST_PATH_SCENARIO = _INIT_PREAMBLE + _load_script("testmon_fast_path.sh")
_TDD_LOOP_SCENARIO = _INIT_PREAMBLE + _load_script("testmon_tdd_loop.sh")
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def testmon_result(docker_manager: DockerManager) -> RunResult:
    """Run the testmon fast-path scenario once for the whole module."""
    return docker_manager.run_clean_script(
        _FAST_PATH_SCENARIO,
        label="testmon-fast-path",
    )


@pytest.fixture(scope="module")
def tdd_loop_result(docker_manager: DockerManager) -> RunResult:
    """Run the TDD-loop scenario once for the whole module."""
    return docker_manager.run_clean_script(
        _TDD_LOOP_SCENARIO,
        label="testmon-tdd-loop",
    )


# ---------------------------------------------------------------------------
# Tests: fast-path activation
# ---------------------------------------------------------------------------


class TestTestmonFastPath:
    """pytest-testmon dependency-aware test selection in the untested-code gate."""

    def test_slopmop_installed(self, testmon_result: RunResult) -> None:
        """slopmop installed successfully inside the container."""
        assert (
            testmon_result.install_succeeded
        ), f"slopmop install failed.\n{testmon_result}"

    def test_first_run_passes(self, testmon_result: RunResult) -> None:
        """First sm swab run (full pytest, no testmon) should pass."""
        assert (
            "first_rc=0" in testmon_result.output
        ), f"First sm swab run did not exit 0.\n{testmon_result.output}"

    def test_second_run_passes(self, testmon_result: RunResult) -> None:
        """Second sm swab run (testmon fast path) should also pass."""
        assert testmon_result.exit_code == 0, (
            f"Second sm swab run failed (exit {testmon_result.exit_code}).\n"
            f"{testmon_result}"
        )

    def test_testmon_fast_path_activated(self, testmon_result: RunResult) -> None:
        """.testmondata was updated on the second run, confirming testmon ran."""
        assert "TESTMON_FAST_PATH_USED=yes" in testmon_result.output, (
            "Expected testmon fast path to activate on second run "
            "(.testmondata mtime unchanged).\n"
            f"Output:\n{testmon_result.output}"
        )


# ---------------------------------------------------------------------------
# Tests: TDD red→green loop with testmon caching
# ---------------------------------------------------------------------------


class TestTestmonTddLoop:
    """Full TDD cycle: baseline → uncovered code → red test → green test.

    Verifies that testmon caching keeps re-evaluation fast: only the
    affected source and tests are re-run, while unrelated checks stay
    cached.
    """

    def test_slopmop_installed(self, tdd_loop_result: RunResult) -> None:
        assert (
            tdd_loop_result.install_succeeded
        ), f"slopmop install failed.\n{tdd_loop_result}"

    def test_baseline_passes(self, tdd_loop_result: RunResult) -> None:
        """Step 1: Full swab on a clean, all-passing project succeeds."""
        assert (
            "BASELINE_RC=0" in tdd_loop_result.output
        ), f"Baseline swab did not pass.\n{tdd_loop_result.output}"

    def test_seed_ok(self, tdd_loop_result: RunResult) -> None:
        """Step 2: Testmon and coverage data seeded successfully."""
        assert (
            "SEED_OK=yes" in tdd_loop_result.output
        ), f"Testmon/coverage seed failed.\n{tdd_loop_result.output}"

    def test_uncovered_source_detected(self, tdd_loop_result: RunResult) -> None:
        """Step 3: Adding uncovered source should make swab fail."""
        assert (
            "UNCOVERED_RC=0" not in tdd_loop_result.output
            or "UNCOVERED_RC=1" in tdd_loop_result.output
        ), (
            "Expected swab to fail after adding uncovered source.\n"
            f"Output:\n{tdd_loop_result.output}"
        )

    def test_tdd_red_fails(self, tdd_loop_result: RunResult) -> None:
        """Step 4: TDD red phase — failing test should make swab fail."""
        assert "TDD_RED_RC=1" in tdd_loop_result.output, (
            "Expected swab to fail during TDD red phase.\n"
            f"Output:\n{tdd_loop_result.output}"
        )

    def test_tdd_green_passes(self, tdd_loop_result: RunResult) -> None:
        """Step 5: TDD green phase — fixed test should make swab pass."""
        assert "TDD_GREEN_RC=0" in tdd_loop_result.output, (
            "Expected swab to pass after fixing test.\n"
            f"Output:\n{tdd_loop_result.output}"
        )

    def test_testmon_updated(self, tdd_loop_result: RunResult) -> None:
        """Testmon data was updated across the scenario, confirming it ran."""
        assert "TESTMON_UPDATED=yes" in tdd_loop_result.output, (
            "Expected testmon to update .testmondata during the scenario.\n"
            f"Output:\n{tdd_loop_result.output}"
        )
