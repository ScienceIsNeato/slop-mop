"""Docker lifecycle manager for slop-mop integration tests.

Provides ``DockerManager``, a context-manager / pytest fixture that handles:

- Building the slop-mop Docker image (once per session, result is cached).
- Cloning the ``bucket-o-slop`` fixture repo from GitHub inside each
  container so every run gets a pristine copy — no local checkout required.
- Running ``sm`` inside a container with a chosen branch checked out.
- Reporting stdout / stderr / exit code in a clean ``RunResult`` dataclass.

Usage (direct)::

    with DockerManager() as dm:
        result = dm.run_sm(branch="main")
        assert result.exit_code == 0

Usage (pytest fixture, defined in conftest.py)::

    def test_happy_path(docker_manager):
        result = docker_manager.run_sm(branch="main")
        assert result.exit_code == 0
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent  # slop-mop root
INTEGRATION_DIR = Path(__file__).parent
DOCKERFILE = INTEGRATION_DIR / "Dockerfile"

DEFAULT_IMAGE_NAME = "slop-mop-integration-test"

# The fixture repo is cloned from GitHub inside each container.
BUCKET_O_SLOP_REPO = "https://github.com/ScienceIsNeato/bucket-o-slop.git"


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


# Distinct exit codes for each phase so tests can tell failures apart.
# Exit 0  = install OK, init OK, validate OK (happy path)
# Exit 1  = install OK, init OK, validate found issues (expected on broken branches)
# Exit 2  = pip install slopmop failed  (never expected)
# Exit 3  = git checkout failed         (never expected)
# Exit 4  = sm init failed              (never expected)
# Exit 5  = git clone failed            (never expected)
INSTALL_FAILED_EXIT = 2
CHECKOUT_FAILED_EXIT = 3
INIT_FAILED_EXIT = 4
CLONE_FAILED_EXIT = 5


@dataclass
class RunResult:
    """The outcome of a single end-to-end container run.

    A run executes four phases in sequence inside a fresh container:

    0. ``git clone bucket-o-slop``    (phase 0 — clone fixture repo)
    1. ``pip install /slopmop-src``   (phase A — install)
    2. ``sm init --non-interactive``  (phase B — init)
    3. ``sm validate commit``         (phase C — validate)

    Each phase has a sentinel exit code so tests can identify which phase
    failed when the result is unexpected.
    """

    exit_code: int
    stdout: str
    stderr: str
    branch: str
    command: list[str]

    @property
    def output(self) -> str:
        """Combined stdout + stderr (the format most assertions need)."""
        return self.stdout + self.stderr

    @property
    def passed(self) -> bool:
        """True only when all phases succeeded (exit 0)."""
        return self.exit_code == 0

    @property
    def clone_succeeded(self) -> bool:
        """False when git clone exited with the sentinel code 5."""
        return self.exit_code != CLONE_FAILED_EXIT

    @property
    def install_succeeded(self) -> bool:
        """True only when clone passed and pip install didn't fail."""
        return self.clone_succeeded and self.exit_code != INSTALL_FAILED_EXIT

    @property
    def init_succeeded(self) -> bool:
        """True only when install passed and sm init didn't fail."""
        return self.install_succeeded and self.exit_code != INIT_FAILED_EXIT

    @property
    def validation_ran(self) -> bool:
        """True when install + init both passed and sm validate actually ran."""
        return self.exit_code in (0, 1)

    def assert_prerequisites(self) -> None:
        """Raise AssertionError if clone, install, or init failed.

        Call this at the top of every gate-assertion test so failures in
        earlier phases surface with a clear message instead of a confusing
        output-matching failure.
        """
        assert self.clone_succeeded, (
            f"git clone bucket-o-slop failed (exit {CLONE_FAILED_EXIT}) on "
            f"branch {self.branch!r}.\n{self}"
        )
        assert self.install_succeeded, (
            f"pip install slopmop failed (exit {INSTALL_FAILED_EXIT}) on "
            f"branch {self.branch!r}.\n{self}"
        )
        assert self.init_succeeded, (
            f"sm init --non-interactive failed (exit {INIT_FAILED_EXIT}) on "
            f"branch {self.branch!r}.\n{self}"
        )
        assert self.validation_ran, (
            f"sm validate never ran (exit {self.exit_code}) on "
            f"branch {self.branch!r}.\n{self}"
        )

    def __str__(self) -> str:  # noqa: D105
        return (
            f"RunResult(branch={self.branch!r}, exit_code={self.exit_code}\n"
            f"  clone_ok={self.clone_succeeded}  "
            f"install_ok={self.install_succeeded}  "
            f"init_ok={self.init_succeeded}  "
            f"validation_ran={self.validation_ran})\n"
            f"--- stdout ---\n{self.stdout}\n"
            f"--- stderr ---\n{self.stderr}"
        )


# ---------------------------------------------------------------------------
# DockerManager
# ---------------------------------------------------------------------------


class DockerManager:
    """Manages the Docker lifecycle for integration tests.

    The fixture repo (``bucket-o-slop``) is cloned from GitHub inside each
    container — no local checkout is required on the host machine.

    Parameters
    ----------
    image_name:
        Tag for the built Docker image.
    rebuild:
        If ``True``, always rebuild the Docker image even if it already
        exists.  Defaults to ``False`` (build only when missing).
    timeout:
        Per-container run timeout in seconds (default 120).
    """

    def __init__(
        self,
        image_name: str = DEFAULT_IMAGE_NAME,
        rebuild: bool = False,
        timeout: int = 120,
    ) -> None:
        self.image_name = image_name
        self.rebuild = rebuild
        self.timeout = timeout
        self._image_built = False

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> "DockerManager":
        self._validate_prerequisites()
        self.build_image()
        return self

    def __exit__(self, *_: object) -> None:
        pass  # nothing to clean up — containers are --rm

    # ------------------------------------------------------------------
    # Prerequisite checks
    # ------------------------------------------------------------------

    def _validate_prerequisites(self) -> None:
        """Raise ``RuntimeError`` if Docker or the Dockerfile is missing."""
        if shutil.which("docker") is None:
            raise RuntimeError("docker is not on PATH — cannot run integration tests")
        if not DOCKERFILE.exists():
            raise RuntimeError(f"Dockerfile missing: {DOCKERFILE}")

    # ------------------------------------------------------------------
    # Image build
    # ------------------------------------------------------------------

    def build_image(self, force: bool = False) -> None:
        """Build the Docker image if it hasn't been built this session.

        Parameters
        ----------
        force:
            Rebuild even if already built this session.
        """
        if self._image_built and not force and not self.rebuild:
            return

        result = subprocess.run(
            [
                "docker",
                "build",
                "-t",
                self.image_name,
                "-f",
                str(DOCKERFILE),
                str(REPO_ROOT),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Docker image build failed (exit {result.returncode}):\n"
                f"{result.stdout}\n{result.stderr}"
            )
        self._image_built = True

    # ------------------------------------------------------------------
    # Running sm
    # ------------------------------------------------------------------

    def run_sm(
        self,
        branch: str,
        command: Optional[list[str]] = None,
        extra_env: Optional[dict[str, str]] = None,
    ) -> RunResult:
        """Run ``sm`` inside a fresh container with *branch* checked out.

        The ``bucket-o-slop`` fixture repo is cloned from GitHub inside the
        container, giving each run a pristine working tree with no host-side
        dependencies beyond Docker itself.

        Parameters
        ----------
        branch:
            Git branch to check out inside the container.
        command:
            Override the default ``["sm", "validate", "commit"]``.
        extra_env:
            Extra ``-e KEY=VALUE`` flags passed to ``docker run``.
        """
        if not self._image_built:
            self.build_image()

        sm_command = command or ["sm", "validate", "commit", "--no-fail-fast"]

        docker_cmd = [
            "docker",
            "run",
            "--rm",
            # Mount slop-mop source read-only so the install reflects current code
            "-v",
            f"{REPO_ROOT}:/slopmop-src:ro",
            "--workdir",
            "/test-repo",
        ]

        # Inject any extra env vars the caller wants
        for key, val in (extra_env or {}).items():
            docker_cmd += ["-e", f"{key}={val}"]

        # Four-phase shell script.  Each phase has a distinct sentinel exit
        # code so tests can pinpoint where something went wrong.
        #
        #  Phase 0 (exit 5): git clone bucket-o-slop
        #  Phase A (exit 2): pip install slopmop
        #  Phase B (exit 4): sm init --non-interactive
        #  Phase C (exit 0 or 1): sm validate commit  ← becomes container exit
        #
        # Copy source to a writable location first: the read-only bind-mount
        # prevents pip from creating slopmop.egg-info inside /slopmop-src.
        #
        # The repo's committed .sb_config.json is saved before init and
        # restored after, because init overwrites it with auto-detected
        # defaults.  Validate should run with the repo's intended thresholds.
        shell_script = (
            f"git clone {BUCKET_O_SLOP_REPO} . 2>&1 "
            f"|| {{ echo 'REPO_CLONE_FAILED'; exit {CLONE_FAILED_EXIT}; }}; "
            f"git checkout {branch} 2>&1 "
            f"|| {{ echo 'BRANCH_CHECKOUT_FAILED'; exit {CHECKOUT_FAILED_EXIT}; }}; "
            f"cp -r /slopmop-src /tmp/slopmop-build 2>&1 "
            f"&& pip install /tmp/slopmop-build --quiet 2>&1 "
            f"|| {{ echo 'SLOPMOP_INSTALL_FAILED'; exit {INSTALL_FAILED_EXIT}; }}; "
            # Save the repo's committed config before init overwrites it
            f"[ -f .sb_config.json ] && cp .sb_config.json /tmp/repo_config.json; "
            f"sm init --non-interactive 2>&1 "
            f"|| {{ echo 'SM_INIT_FAILED'; exit {INIT_FAILED_EXIT}; }}; "
            # Restore the repo's committed config (custom thresholds etc.)
            f"[ -f /tmp/repo_config.json ] && cp /tmp/repo_config.json .sb_config.json; "
            + " ".join(sm_command)
        )
        docker_cmd += [self.image_name, "bash", "-c", shell_script]

        proc = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )

        return RunResult(
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            branch=branch,
            command=sm_command,
        )

    # ------------------------------------------------------------------
    # Convenience: check prerequisites without raising
    # ------------------------------------------------------------------

    @staticmethod
    def prerequisites_met() -> tuple[bool, str]:
        """Return ``(True, "")`` if all prerequisites are satisfied.

        On failure returns ``(False, reason)`` suitable for a skip message.
        """
        if shutil.which("docker") is None:
            return False, "docker not found on PATH"
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                return False, "Docker daemon is not running"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False, "Docker daemon is not responding"
        if not DOCKERFILE.exists():
            return False, f"Dockerfile missing at {DOCKERFILE}"
        return True, ""
