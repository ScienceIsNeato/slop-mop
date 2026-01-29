"""Specialized test type checks targeting specific test directories.

These checks isolate different test tiers:
- smoke: Critical-path browser tests (Selenium, requires server)
- integration: Database-backed tests (requires seeded DB)
- e2e: End-to-end browser tests (Playwright, requires server)

Each check targets a specific tests/{type}/ directory and has
environmental prerequisites. The CI workflow is responsible for
starting servers and seeding databases before invoking slopbucket.
"""

import os
import sys
import time
from typing import List, Optional

from slopbucket.checks.base import (
    BaseCheck,
    ConfigField,
    GateCategory,
    PythonCheckMixin,
)
from slopbucket.core.result import CheckResult, CheckStatus


class SmokeTestCheck(BaseCheck, PythonCheckMixin):
    """Smoke tests — critical-path browser validation against a live server."""

    @property
    def name(self) -> str:
        return "smoke-tests"

    @property
    def display_name(self) -> str:
        return "💨 Smoke Tests (Selenium)"

    @property
    def category(self) -> GateCategory:
        return GateCategory.INTEGRATION

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="test_dir",
                field_type="string",
                default="tests/smoke",
                description="Directory containing smoke tests",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        smoke_dir = os.path.join(project_root, "tests", "smoke")
        return os.path.isdir(smoke_dir)

    def _detect_server_port(self) -> Optional[str]:
        return os.environ.get("TEST_PORT") or os.environ.get("PORT")

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()
        smoke_dir = os.path.join(project_root, "tests", "smoke")

        if not os.path.isdir(smoke_dir):
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=time.time() - start_time,
                output="No tests/smoke/ directory found.",
            )

        port = self._detect_server_port()
        if not port:
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=time.time() - start_time,
                output="No server port configured (set TEST_PORT or PORT). "
                "Smoke tests require a running server.",
            )

        cmd = [sys.executable, "-m", "pytest", "tests/smoke", "--tb=short", "-v"]
        result = self._run_command(cmd, cwd=project_root, timeout=300)
        duration = time.time() - start_time

        if result.success:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=self._summary_line(result.output),
            )

        if result.returncode == 2:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                error="Smoke test collection error",
                output=result.output,
                fix_suggestion=f"Install selenium: pip install selenium. "
                f"Ensure server is running on port {port}.",
            )

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=result.output,
            error="Smoke tests failed",
            fix_suggestion=f"Verify server is healthy on port {port}.",
        )

    @staticmethod
    def _summary_line(output: str) -> str:
        for line in reversed(output.splitlines()):
            if "passed" in line or "failed" in line:
                return line.strip()
        return "Smoke tests completed"


class IntegrationTestCheck(BaseCheck, PythonCheckMixin):
    """Integration tests targeting tests/integration/ with database."""

    @property
    def name(self) -> str:
        return "integration-tests"

    @property
    def display_name(self) -> str:
        return "🔗 Integration Tests (database-backed)"

    @property
    def category(self) -> GateCategory:
        return GateCategory.INTEGRATION

    @property
    def depends_on(self) -> List[str]:
        return ["integration:smoke-tests"]

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="test_dir",
                field_type="string",
                default="tests/integration",
                description="Directory containing integration tests",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        integration_dir = os.path.join(project_root, "tests", "integration")
        return os.path.isdir(integration_dir)

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()
        integration_dir = os.path.join(project_root, "tests", "integration")

        if not os.path.isdir(integration_dir):
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=time.time() - start_time,
                output="No tests/integration/ directory found.",
            )

        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=time.time() - start_time,
                output="DATABASE_URL not set. Integration tests require a seeded database.",
            )

        cmd = [sys.executable, "-m", "pytest", "tests/integration", "--tb=short", "-v"]
        result = self._run_command(cmd, cwd=project_root, timeout=300)
        duration = time.time() - start_time

        if result.success:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=self._summary_line(result.output),
            )

        if result.returncode == 2:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                error="Integration test collection error",
                output=result.output,
                fix_suggestion="Check test file syntax and database configuration.",
            )

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=result.output,
            error="Integration tests failed",
            fix_suggestion="Verify DATABASE_URL is correctly seeded.",
        )

    @staticmethod
    def _summary_line(output: str) -> str:
        for line in reversed(output.splitlines()):
            if "passed" in line or "failed" in line:
                return line.strip()
        return "Integration tests completed"


class E2ETestCheck(BaseCheck, PythonCheckMixin):
    """End-to-end Playwright browser tests."""

    @property
    def name(self) -> str:
        return "e2e-tests"

    @property
    def display_name(self) -> str:
        return "🎭 E2E Tests (Playwright)"

    @property
    def category(self) -> GateCategory:
        return GateCategory.INTEGRATION

    @property
    def depends_on(self) -> List[str]:
        return ["integration:integration-tests"]

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="test_dir",
                field_type="string",
                default="tests/e2e",
                description="Directory containing E2E tests",
            ),
            ConfigField(
                name="test_command",
                field_type="string",
                default=None,
                description="Custom test command (optional)",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        e2e_dir = os.path.join(project_root, "tests", "e2e")
        return os.path.isdir(e2e_dir)

    def _detect_server_port(self) -> Optional[str]:
        return (
            os.environ.get("E2E_PORT")
            or os.environ.get("TEST_PORT")
            or os.environ.get("PORT")
        )

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()
        e2e_dir = os.path.join(project_root, "tests", "e2e")

        if not os.path.isdir(e2e_dir):
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=time.time() - start_time,
                output="No tests/e2e/ directory found.",
            )

        port = self._detect_server_port()
        if not port:
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=time.time() - start_time,
                output="No E2E server port configured. "
                "Set LOOPCLOSER_DEFAULT_PORT_E2E or TEST_PORT.",
            )

        # Verify playwright is available
        probe = self._run_command(
            [sys.executable, "-c", "import playwright"],
            cwd=project_root,
            timeout=10,
        )
        if not probe.success:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=time.time() - start_time,
                error="Playwright is not installed",
                fix_suggestion="Install: pip install playwright && "
                "python -m playwright install --with-deps chromium",
            )

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "tests/e2e",
            "--tb=short",
            "-v",
            "--timeout=30",
        ]
        result = self._run_command(cmd, cwd=project_root, timeout=600)
        duration = time.time() - start_time

        if result.success:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=self._summary_line(result.output),
            )

        if result.returncode == 2:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                error="E2E test collection error",
                output=result.output,
                fix_suggestion="Check test file syntax and playwright installation.",
            )

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=result.output,
            error="E2E tests failed",
            fix_suggestion=f"Verify server is healthy on port {port}. "
            "Check browser screenshots if generated.",
        )

    @staticmethod
    def _summary_line(output: str) -> str:
        for line in reversed(output.splitlines()):
            if "passed" in line or "failed" in line:
                return line.strip()
        return "E2E tests completed"
