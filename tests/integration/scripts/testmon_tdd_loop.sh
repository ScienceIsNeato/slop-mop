#!/usr/bin/env bash
# TDD-loop scenario: exercises the full red→green cycle with testmon caching.
#
# Expects: CWD is /tmp/testmon-fixture (created by testmon_project_setup.sh)
#          with slopmop installed and sm init done.
#
# Flow:
#   1. Baseline sm swab → all pass (full pytest + coverage)
#   2. Seed testmon + coverage.xml
#   3. Add module_c.py (uncovered) → swab → coverage fails
#   4. Add test_c.py (failing test, TDD red) → swab → test fails
#   5. Fix test_c.py → swab → all green
#
# Key assertion points are printed as MARKER lines for the Python test
# harness to verify.

set -euo pipefail
cd /tmp/testmon-fixture

# ──────────────────────────────────────────────────────────
# Step 1: Baseline — full swab, everything passes
# ──────────────────────────────────────────────────────────
echo "=== STEP 1: BASELINE ==="
sm swab --no-fail-fast --no-json 2>&1
BASELINE_RC=$?
echo "BASELINE_RC=$BASELINE_RC"

# ──────────────────────────────────────────────────────────
# Step 2: Seed testmon and coverage for fast-path runs
# ──────────────────────────────────────────────────────────
echo "=== STEP 2: SEED ==="
.venv/bin/pytest --testmon -q 2>&1
.venv/bin/pytest --cov=. --cov-report=xml:coverage.xml -q --no-header 2>&1

[ -f .testmondata ] || { echo "ERROR: .testmondata not seeded"; exit 1; }
[ -f coverage.xml  ] || { echo "ERROR: coverage.xml not generated"; exit 1; }
echo "SEED_OK=yes"

git add .
git commit -m "seed testmon data" --quiet --allow-empty-message

# ──────────────────────────────────────────────────────────
# Step 3: Add uncovered source → coverage should fail
# ──────────────────────────────────────────────────────────
echo "=== STEP 3: ADD UNCOVERED SOURCE ==="
cat > src/module_c.py << 'PYEOF'
def divide(a, b):
    if b == 0:
        raise ValueError("division by zero")
    return a / b
PYEOF

git add src/module_c.py
git commit -m "add module_c (no tests)" --quiet

BEFORE_MTIME=$(stat -c %Y .testmondata)
sleep 1

sm swab --no-fail-fast --no-json 2>&1
UNCOVERED_RC=$?
echo "UNCOVERED_RC=$UNCOVERED_RC"

# ──────────────────────────────────────────────────────────
# Step 4: TDD red — add a failing test for module_c
# ──────────────────────────────────────────────────────────
echo "=== STEP 4: TDD RED ==="
cat > tests/test_c.py << 'PYEOF'
from src.module_c import divide

def test_divide():
    # Intentionally wrong expectation — TDD red phase
    assert divide(10, 2) == 6
PYEOF

git add tests/test_c.py
git commit -m "add failing test_c (TDD red)" --quiet

sm swab -g overconfidence:untested-code.py --no-fail-fast --no-json 2>&1
TDD_RED_RC=$?
echo "TDD_RED_RC=$TDD_RED_RC"

# ──────────────────────────────────────────────────────────
# Step 5: TDD green — fix the test expectation
# ──────────────────────────────────────────────────────────
echo "=== STEP 5: TDD GREEN ==="
cat > tests/test_c.py << 'PYEOF'
from src.module_c import divide

def test_divide():
    assert divide(10, 2) == 5.0

def test_divide_by_zero():
    import pytest
    with pytest.raises(ValueError, match="division by zero"):
        divide(1, 0)
PYEOF

git add tests/test_c.py
git commit -m "fix test_c (TDD green)" --quiet

sm swab -g overconfidence:untested-code.py --no-fail-fast --no-json 2>&1
TDD_GREEN_RC=$?
echo "TDD_GREEN_RC=$TDD_GREEN_RC"

AFTER_MTIME=$(stat -c %Y .testmondata)
if [ "$AFTER_MTIME" != "$BEFORE_MTIME" ]; then
    echo "TESTMON_UPDATED=yes"
else
    echo "TESTMON_UPDATED=no"
fi

# ──────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────
echo "=== SUMMARY ==="
echo "baseline=$BASELINE_RC uncovered=$UNCOVERED_RC red=$TDD_RED_RC green=$TDD_GREEN_RC"
