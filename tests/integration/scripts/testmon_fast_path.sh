#!/usr/bin/env bash
# Testmon fast-path scenario: verifies that sm swab uses pytest --testmon
# when .testmondata and coverage.xml are already seeded.
#
# Expects: CWD is /tmp/testmon-fixture (created by testmon_project_setup.sh)
#          with slopmop installed and sm init done.

set -euo pipefail
cd /tmp/testmon-fixture

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
