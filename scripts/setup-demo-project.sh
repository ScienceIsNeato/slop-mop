#!/usr/bin/env bash
# Set up a throwaway project at /tmp/slopdemo that triggers three distinct
# slop-mop findings when scoured:
#
#   1. deceptiveness:bogus-tests.py  — a test that asserts True (proves nothing)
#   2. overconfidence:coverage-gaps.py — two functions with no test coverage
#   3. laziness:silenced-gates        — two gates parked in disabled_gates
#
# Used by scripts/claude-skill-demo.tape to record the live TUI for the README.
# Idempotent: nukes /tmp/slopdemo if it exists and rebuilds.

set -euo pipefail

PROJ="${SLOPDEMO_DIR:-/tmp/slopdemo}"

rm -rf "$PROJ"
mkdir -p "$PROJ/src" "$PROJ/tests"
cd "$PROJ"

git init -q
git config user.email "demo@slop-mop.local"
git config user.name "slopdemo"

# ── Source: three functions, only `discount` will have a real test ──
: > src/__init__.py
cat > src/pricing.py <<'PY'
"""Pricing utilities."""


def discount(price, pct):
    """Apply a percentage discount to a price."""
    return price * (1 - pct / 100)


def total_with_tax(price, tax_rate):
    """Add tax (tax_rate as a percentage, e.g. 8.25 for 8.25%)."""
    return price * (1 + tax_rate / 100)


def bulk_discount(price, qty):
    """Tiered bulk discount — intentionally untested."""
    if qty >= 100:
        return price * 0.7
    if qty >= 25:
        return price * 0.85
    if qty >= 10:
        return price * 0.92
    return price
PY

# ── Tests: one bogus + one real ──
: > tests/__init__.py
cat > tests/test_pricing.py <<'PY'
"""Tests for pricing module."""

import unittest

from src.pricing import discount


class TestPricing(unittest.TestCase):
    def test_discount_basic(self):
        # BOGUS — this assertion proves nothing about discount()
        assert True

    def test_discount_real(self):
        self.assertAlmostEqual(discount(100, 10), 90.0)
PY

# ── Per-project venv with the test deps that sm needs ──
python3 -m venv venv
"$PROJ/venv/bin/pip" install -q pytest pytest-cov pytest-testmon coverage

git add -A
git commit -q -m "demo: pricing module with bogus test + uncovered code"

# ── Slop-mop config ──
sm init >/dev/null 2>&1 || true
sm config --enable deceptiveness:bogus-tests.py     >/dev/null
sm config --enable laziness:sloppy-formatting.py    >/dev/null
sm config --enable overconfidence:untested-code.py  >/dev/null
sm config --enable overconfidence:coverage-gaps.py  >/dev/null
sm config --enable laziness:silenced-gates          >/dev/null

# Inject a top-level disabled_gates list — silenced-gates flags this as
# config debt (a "stop pretending these gates don't exist" nudge).
python3 - <<'PY'
import json
p = ".sb_config.json"
with open(p) as f:
    c = json.load(f)
c["disabled_gates"] = [
    "overconfidence:type-blindness.py",
    "laziness:complexity-creep.py",
]
with open(p, "w") as f:
    json.dump(c, f, indent=2)
PY

echo "ready: $PROJ"
echo
echo "Next: vhs scripts/claude-skill-demo.tape"
