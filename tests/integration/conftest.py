"""Pytest fixtures for integration tests.

Key design decision: each branch is run **once** and the result is cached
for the entire session.  Individual tests just inspect the cached
``RunResult``.  This keeps the suite at ~3 container runs (one per branch)
instead of spinning up a fresh container for every test method.

Fixture pinning
---------------
Each branch is pinned to a specific ``bucket-o-slop`` commit SHA via
the ``FIXTURE_REFS`` dict below.  This decouples the two repos — both
can be reviewed and merged independently.  When ``bucket-o-slop``
content changes, update the SHA here and the integration tests pick up
the new fixtures automatically.

To update a ref::

    cd /path/to/bucket-o-slop
    git log --oneline -1 main        # → copy the full SHA
    # paste into FIXTURE_REFS["main"] below
"""

from __future__ import annotations

import pytest

from tests.integration.docker_manager import DockerManager, RunResult

# ---------------------------------------------------------------------------
# Pinned bucket-o-slop fixture refs
#
# Maps logical branch name → exact git ref (SHA preferred, tag or branch
# also accepted).  Keeps integration tests deterministic and decoupled
# from bucket-o-slop's HEAD.
#
# When bucket-o-slop PRs merge, update the SHA for each affected branch.
# ---------------------------------------------------------------------------
FIXTURE_REFS: dict[str, str] = {
    # feat/add-js-slop-main — Python + JS tests with assertions (gate passes)
    "main": "41f826dd563cff648734bcb4c482119239127dec",  # pragma: allowlist secret
    # feat/add-js-slop-all-fail — Python slop + JS tests without assertions (gate fails)
    "all-fail": "37dc23351b3bc9f89bd8b4b94c014dbe3d37f1bb",  # pragma: allowlist secret
    # feat/add-js-slop-mixed — Python slop + JS tests with assertions (gate passes)
    "mixed": "386922908f3226653bbb47eb66277ad7c305ada2",  # pragma: allowlist secret
}


@pytest.fixture(scope="session")
def docker_manager():
    """Session-scoped DockerManager.

    Builds the image once, then provides a shared manager instance for all
    integration tests.
    """
    with DockerManager() as dm:
        yield dm


# ------------------------------------------------------------------
# Per-branch result fixtures (one container run per branch, cached)
# ------------------------------------------------------------------


@pytest.fixture(scope="session")
def result_main(docker_manager: DockerManager) -> RunResult:
    """Run sm against the ``main`` fixtures once and cache the result."""
    return docker_manager.run_sm(branch="main", ref=FIXTURE_REFS["main"])


@pytest.fixture(scope="session")
def result_all_fail(docker_manager: DockerManager) -> RunResult:
    """Run sm against the ``all-fail`` fixtures once and cache the result."""
    return docker_manager.run_sm(branch="all-fail", ref=FIXTURE_REFS["all-fail"])


@pytest.fixture(scope="session")
def result_mixed(docker_manager: DockerManager) -> RunResult:
    """Run sm against the ``mixed`` fixtures once and cache the result."""
    return docker_manager.run_sm(branch="mixed", ref=FIXTURE_REFS["mixed"])
