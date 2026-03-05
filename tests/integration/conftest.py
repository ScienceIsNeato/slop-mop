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
    # main — Python + JS tests with assertions (gate passes)
    "main": "fe7c32466d9985d92175c192a03a8a05603c8076",  # pragma: allowlist secret
    # all-fail — Python slop + JS tests without assertions (gate fails)
    "all-fail": "0816f6776a26d50ea052fa1cf1922dee6e783be0",  # pragma: allowlist secret
    # mixed — Python slop + JS tests with assertions (gate passes)
    "mixed": "a3d0675de0c59b59a7874ebb15860759ae3473f0",  # pragma: allowlist secret
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


# ------------------------------------------------------------------
# SARIF fixture — one extra container run, cached for all SARIF tests
# ------------------------------------------------------------------

# Delimiter printed between sm's console noise and the SARIF payload
# so tests can extract clean JSON from stdout.  The leading newline
# matters: swab's final "1 failed" summary line doesn't end with one.
_SARIF_MARKER = "___SARIF_PAYLOAD_BELOW___"


@pytest.fixture(scope="session")
def sarif_all_fail(docker_manager: DockerManager) -> dict[str, object]:
    """Run swab --sarif against ``all-fail`` and return the parsed document.

    This is the end-to-end acceptance check for the SARIF feature.  Unit
    tests in ``test_sarif.py`` prove the reporter shapes documents
    correctly from hand-built fixtures; this proves the whole pipeline
    — real gates, real tool output, real parsing, real findings — emits
    a schema-valid document with actual ``physicalLocation`` entries.

    The ``all-fail`` branch is the right fixture because it trips every
    gate that CAN fail on that codebase.  Running against slop-mop
    itself produces an empty SARIF (everything passes) which validates
    the schema but not the content.

    One container run, session-scoped, consumed by every test in
    ``test_sarif_integration.py``.  Adds ~40s to the integration suite.
    """
    import json

    # Write SARIF to a file inside the container, then cat it behind a
    # marker.  swab's console output (progress lines, emoji, summary
    # box) precedes the marker; the SARIF JSON follows it.  We can't
    # use --sarif → stdout directly because the shell script in
    # docker_manager.run_sm prepends git/pip/init noise to the same
    # stream and there's no clean way to suppress that.
    result = docker_manager.run_sm(
        branch="all-fail",
        ref=FIXTURE_REFS["all-fail"],
        command=[
            "sm",
            "swab",
            "--no-fail-fast",
            "--no-json",
            "--sarif",
            "--output-file",
            "/tmp/out.sarif",
            ";",
            "echo",
            f"'{_SARIF_MARKER}'",
            ";",
            "cat",
            "/tmp/out.sarif",
        ],
    )

    # Prerequisites still apply — if clone/install/init failed, the
    # SARIF file won't exist and the split below will break with an
    # unhelpful error.  Fail loud and early with the real cause.
    result.assert_prerequisites()

    if _SARIF_MARKER not in result.stdout:
        pytest.fail(
            f"SARIF marker not found in container output — swab may "
            f"have crashed before writing /tmp/out.sarif.\n{result}"
        )

    _console, payload = result.stdout.split(_SARIF_MARKER, 1)
    try:
        return json.loads(payload.strip())
    except json.JSONDecodeError as e:
        pytest.fail(
            f"SARIF payload is not valid JSON: {e}\n"
            f"--- payload (first 500 chars) ---\n{payload[:500]}\n"
            f"--- full run ---\n{result}"
        )
