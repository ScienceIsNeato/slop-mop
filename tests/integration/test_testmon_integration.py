"""Integration test: pytest-testmon fast path in the untested-code gate.

Verifies that when pytest-testmon is installed and .testmondata has been
seeded, sm swab uses ``pytest --testmon`` rather than a full
coverage-regenerating run.  The fast path only re-runs tests whose source
dependencies have changed, dramatically reducing iteration time on large
suites.

Test structure
--------------
A minimal Python project is created from scratch inside the container:

  src/module_a.py   — add()
  src/module_b.py   — multiply()
  tests/test_a.py   — covers module_a
  tests/test_b.py   — covers module_b

Scenario:

  1. First ``sm swab``: no .testmondata → full pytest run.
  2. Seed .testmondata via ``pytest --testmon`` + generate coverage.xml.
  3. Touch src/module_b.py (only test_b.py should re-run).
  4. Second ``sm swab``: testmon fast path activates, .testmondata is
     updated (mtime changes), confirming testmon ran.

Run::

    pytest tests/integration/ -m integration -k testmon -v
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
# Scenario script
# ---------------------------------------------------------------------------

_PROJECT_SETUP = r"""
mkdir -p /tmp/testmon-fixture/src /tmp/testmon-fixture/tests
cd /tmp/testmon-fixture

cat > src/__init__.py << 'PYEOF'
PYEOF

cat > src/module_a.py << 'PYEOF'
def add(a, b):
    return a + b
PYEOF

cat > src/module_b.py << 'PYEOF'
def multiply(a, b):
    return a * b
PYEOF

cat > tests/__init__.py << 'PYEOF'
PYEOF

cat > tests/test_a.py << 'PYEOF'
from src.module_a import add

def test_add():
    assert add(2, 3) == 5
PYEOF

cat > tests/test_b.py << 'PYEOF'
from src.module_b import multiply

def test_multiply():
    assert multiply(2, 3) == 6
PYEOF

cat > setup.py << 'PYEOF'
from setuptools import setup, find_packages
setup(name="testmon-fixture", packages=find_packages())
PYEOF

# Project venv — install test tools
python3 -m venv .venv
.venv/bin/pip install pytest pytest-cov pytest-testmon --quiet 2>&1

# Git repo so sm init doesn't complain
git init --quiet
git add .
git commit -m "initial" --quiet --allow-empty-message
"""

_TESTMON_SCENARIO = _PROJECT_SETUP + r"""
# sm init in the fixture project
sm init --non-interactive 2>&1 || { echo "SM_INIT_FAILED"; exit 4; }

# --- First run: no .testmondata → full pytest with coverage ---
echo "=== FIRST RUN ==="
sm swab -g overconfidence:untested-code.py --no-fail-fast --no-json 2>&1
FIRST_RC=$?
echo "first_rc=$FIRST_RC"

# Seed .testmondata and generate coverage.xml so the fast path can activate
.venv/bin/pytest --testmon -q 2>&1
.venv/bin/pytest --cov=. --cov-report=xml:coverage.xml -q --no-header 2>&1

[ -f .testmondata ] || { echo "ERROR: .testmondata not seeded"; exit 1; }
[ -f coverage.xml  ] || { echo "ERROR: coverage.xml not generated"; exit 1; }

# Record .testmondata mtime before the second run
BEFORE=$(stat -c %Y .testmondata)
sleep 1

# Touch module_b.py — testmon should re-run only test_b.py
echo "# modified" >> src/module_b.py

# --- Second run: .testmondata + coverage.xml exist → testmon fast path ---
echo "=== SECOND RUN ==="
sm swab -g overconfidence:untested-code.py --no-fail-fast --no-json 2>&1
SECOND_RC=$?
echo "second_rc=$SECOND_RC"

AFTER=$(stat -c %Y .testmondata)

if [ "$AFTER" != "$BEFORE" ]; then
    echo "TESTMON_FAST_PATH_USED=yes"
else
    echo "TESTMON_FAST_PATH_USED=no"
fi

exit $SECOND_RC
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def testmon_result(docker_manager: DockerManager) -> RunResult:
    """Run the testmon integration scenario once for the whole module."""
    return docker_manager.run_clean_script(
        _TESTMON_SCENARIO,
        label="testmon-fast-path",
    )


# ---------------------------------------------------------------------------
# Tests
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
