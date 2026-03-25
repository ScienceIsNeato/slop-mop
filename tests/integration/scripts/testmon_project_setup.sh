#!/usr/bin/env bash
# Shared setup: create a minimal Python project for testmon integration tests.
#
# Creates:
#   /tmp/testmon-fixture/
#     src/module_a.py   — add()
#     src/module_b.py   — multiply()
#     tests/test_a.py   — covers module_a
#     tests/test_b.py   — covers module_b
#     setup.py          — makes src importable
#     .venv/            — project venv with pytest, pytest-cov, pytest-testmon
#     .git/             — initialised repo
#
# After sourcing, CWD is /tmp/testmon-fixture.

set -euo pipefail

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
