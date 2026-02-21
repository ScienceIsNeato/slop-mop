"""Pytest fixtures for integration tests.

Key design decision: each branch is run **once** and the result is cached
for the entire session.  Individual tests just inspect the cached
``RunResult``.  This keeps the suite at ~3 container runs (one per branch)
instead of spinning up a fresh container for every test method.
"""

from __future__ import annotations

import pytest

from tests.integration.docker_manager import DockerManager, RunResult


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
    """Run sm against the ``main`` branch once and cache the result."""
    return docker_manager.run_sm(branch="main")


@pytest.fixture(scope="session")
def result_all_fail(docker_manager: DockerManager) -> RunResult:
    """Run sm against the ``all-fail`` branch once and cache the result."""
    return docker_manager.run_sm(branch="all-fail")


@pytest.fixture(scope="session")
def result_mixed(docker_manager: DockerManager) -> RunResult:
    """Run sm against the ``mixed`` branch once and cache the result."""
    return docker_manager.run_sm(branch="mixed")
