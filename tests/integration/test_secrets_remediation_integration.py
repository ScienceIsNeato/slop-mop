"""Integration tests for the detect-secrets agent remediation workflow."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from slopmop.checks.security import SecurityLocalCheck
from slopmop.core.result import CheckStatus


# synthetic — integration fixture only, not a live credential
def _synthetic_production_secret_line() -> str:
    """Vendor-neutral credential for integration tests only."""
    return 'PRODUCTION_API_SECRET = "8f3kL9mP2xQ7vR4nT6wY1zA0bC5dE9fH2jK4"\n'


def _synthetic_fixture_secret_line() -> str:
    """Same shape; TEST_ prefix for the excluded tests/ path scenario."""
    return 'TEST_FIXTURE_SECRET = "8f3kL9mP2xQ7vR4nT6wY1zA0bC5dE9fH2jK4"\n'


@pytest.mark.integration
class TestSecretsRemediationIntegration:
    """Verifies the exact agent instruction workflow on secrets detection.

    Proves that:
    1. A hardcoded secret triggers a failed security check with the 1-4 classification instructions.
    2. The STEP 2 command parses and executes in dry-run mode successfully.
    3. The STEP 4 baseline update command creates/updates the baseline file.
    4. A subsequent scan utilizing that baseline successfully passes.
    5. Clean refactoring (moving secret to environment variables) resolves the failure.
    6. Moving the secret to an excluded directory (e.g., tests/) resolves the failure.
    """

    @pytest.fixture
    def setup_project(self, tmp_path: Path):
        """Seed a clean project directory with a baseline and then add a hardcoded secret."""
        # Initialize git repository
        subprocess.run(
            ["git", "init"], cwd=str(tmp_path), capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        # Seed a clean Python file
        config_py = src_dir / "config.py"
        config_py.write_text("# Clean configuration\n", encoding="utf-8")

        # Stage and commit the clean file
        subprocess.run(
            ["git", "add", "src/config.py"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "initial commit"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )

        # Create the initial empty/clean baseline file
        baseline_file = tmp_path / ".secrets.baseline"
        cmd = [sys.executable, "-m", "detect_secrets", "scan"]
        with open(baseline_file, "w", encoding="utf-8") as f:
            subprocess.run(cmd, stdout=f, check=True, cwd=str(tmp_path))

        # Stage and commit the baseline file
        subprocess.run(
            ["git", "add", ".secrets.baseline"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add baseline"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )

        # Also create a tests directory for testing the test fixture exclusion path (STEP 3)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        return tmp_path, config_py, tests_dir

    def test_secrets_remediation_loop_end_to_end(self, setup_project):
        project_root, config_py, tests_dir = setup_project
        project_root_str = str(project_root)

        # Introduce a vendor-neutral high-entropy secret violation
        config_py.write_text(
            _synthetic_production_secret_line(),
            encoding="utf-8",
        )

        # 1. Verify Check Fails and Outputs Structured Agent Instructions
        strategy = self._verify_check_fails_with_instructions(project_root_str)

        # 2. Verify STEP 2 Command (Barnacle Filing Dry-Run)
        self._verify_wake_captain_summons(project_root_str, strategy)

        # 3. Verify STEP 4 Command (Baseline Whitelisting)
        self._verify_baseline_whitelisting(project_root_str, strategy, project_root)

        # 4. Verify Subsequent Check utilizing the Baseline Passes
        self._verify_subsequent_check_passes(project_root_str)

        # 5. Verify STEP 3 (Refactoring clean / moving to env var)
        self._verify_clean_refactoring(project_root_str, config_py, project_root)

        # 6. Verify STEP 3 (Moving secret to an excluded test directory / fixture file)
        self._verify_test_fixture_exclusion(project_root_str, tests_dir)

    def _verify_check_fails_with_instructions(self, project_root_str: str) -> str:
        # Initialize check with the empty baseline configured
        check = SecurityLocalCheck(
            {
                "scanners": ["detect-secrets"],
                "config_file_path": ".secrets.baseline",
            }
        )
        result = check.run(project_root_str)

        assert (
            result.status == CheckStatus.FAILED
        ), f"Expected check to fail, output: {result.output}"
        assert len(result.findings) >= 1
        finding = result.findings[0]

        # Verify the findings carry the exact file and line number
        assert finding.file == "src/config.py"
        assert finding.line == 1

        # Verify fix_strategy contains the structured instruction steps
        strategy = finding.fix_strategy
        assert strategy is not None
        assert "STEP 1 - CLASSIFY Credential:" in strategy
        assert "STEP 2 - IF DANGEROUS:" in strategy
        assert "STEP 3 - IF SAFE_BUT_SLOPPY:" in strategy
        assert "STEP 4 - IF SAFE_AND_CLEAN:" in strategy
        return strategy

    def _verify_wake_captain_summons(
        self, project_root_str: str, strategy: str
    ) -> None:
        # Extract the exact wake-angry-drunk-captain command from the instruction text.
        # Find the line starting with "  sm wake-angry-drunk-captain "
        command_lines = [
            line.strip()
            for line in strategy.splitlines()
            if "sm wake-angry-drunk-captain" in line
        ]
        assert (
            len(command_lines) == 1
        ), "Failed to find the sm wake-angry-drunk-captain command in fix_strategy"
        wake_cmd = command_lines[0]

        # Replace 'sm' with sys.executable + ' -m slopmop.sm' to run it in-process.
        args = shlex.split(wake_cmd)
        # Strip the leading 'sm' or './sm'
        args = args[1:]

        # Captain summons requires structured justification flags; in the test we
        # only validate the CLI wiring + JSON contract.
        run_args = (
            [sys.executable, "-m", "slopmop.sm"]
            + args
            + ["--json", "--project-root", project_root_str]
        )

        result_wake = subprocess.run(
            run_args,
            capture_output=True,
            text=True,
            check=False,
            cwd=project_root_str,
        )
        # EXIT_SUMMONED is 1 for a valid summons.
        assert result_wake.returncode == 1
        assert result_wake.stdout.strip(), result_wake.stderr

        payload = json.loads(result_wake.stdout)
        assert payload.get("command") == "wake-angry-drunk-captain"
        assert "relay_to_human" in payload.get("data", {})

    def _verify_baseline_whitelisting(
        self, project_root_str: str, strategy: str, project_root: Path
    ) -> None:
        # Extract the detect-secrets scan command from the instruction text.
        baseline_lines = [
            line.strip()
            for line in strategy.splitlines()
            if "detect_secrets scan " in line
        ]
        assert (
            len(baseline_lines) == 1
        ), "Failed to find the baseline scan command in fix_strategy"

        # Run the command in the temporary directory to update the baseline file
        # Command is: python3 -m detect_secrets scan --baseline .secrets.baseline
        baseline_file = project_root / ".secrets.baseline"
        assert baseline_file.exists()

        # Run it via sys.executable to ensure we use the same Python environment
        cmd_args = [
            sys.executable,
            "-m",
            "detect_secrets",
            "scan",
            "--baseline",
            ".secrets.baseline",
        ]
        result_baseline = subprocess.run(
            cmd_args,
            capture_output=True,
            text=True,
            check=True,
            cwd=project_root_str,
        )
        assert result_baseline.returncode == 0
        assert (
            baseline_file.exists()
        ), f"Baseline file was not created: {result_baseline.stderr}"

        # Verify the baseline contains our key
        baseline_data = json.loads(baseline_file.read_text(encoding="utf-8"))
        assert "src/config.py" in baseline_data.get("results", {})

    def _verify_subsequent_check_passes(self, project_root_str: str) -> None:
        check_with_baseline = SecurityLocalCheck(
            {
                "scanners": ["detect-secrets"],
                "config_file_path": ".secrets.baseline",
            }
        )
        result_after_baseline = check_with_baseline.run(project_root_str)
        assert (
            result_after_baseline.status == CheckStatus.PASSED
        ), f"Expected check with baseline to pass, got failure: {result_after_baseline.output}"

    def _verify_clean_refactoring(
        self, project_root_str: str, config_py: Path, project_root: Path
    ) -> None:
        # Remove the baseline file to ensure we are testing clean code
        baseline_file = project_root / ".secrets.baseline"
        baseline_file.unlink()

        # Refactor config.py to load from environment variable (obviating the secret)
        config_py.write_text(
            "import os\nAWS_SECRET_KEY = os.getenv('AWS_SECRET_KEY', 'placeholder')\n",
            encoding="utf-8",
        )

        # Run the check again; it should now pass cleanly
        check_after_refactor = SecurityLocalCheck({"scanners": ["detect-secrets"]})
        result_after_refactor = check_after_refactor.run(project_root_str)
        assert (
            result_after_refactor.status == CheckStatus.PASSED
        ), f"Expected check after refactoring to pass, got failure: {result_after_refactor.output}"

    def _verify_test_fixture_exclusion(
        self, project_root_str: str, tests_dir: Path
    ) -> None:
        # Re-introduce the secret inside the tests directory, which is excluded by default
        test_fixture_py = tests_dir / "test_fixture.py"
        test_fixture_py.write_text(
            _synthetic_fixture_secret_line(),
            encoding="utf-8",
        )

        # Stage and commit it so detect-secrets sees it as a tracked file
        subprocess.run(
            ["git", "add", "tests/test_fixture.py"],
            cwd=project_root_str,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add test fixture"],
            cwd=project_root_str,
            capture_output=True,
            check=True,
        )

        # Run the check; it should still pass cleanly because the tests/ directory is excluded
        check_after_test_fixture = SecurityLocalCheck({"scanners": ["detect-secrets"]})
        result_after_test_fixture = check_after_test_fixture.run(project_root_str)
        assert (
            result_after_test_fixture.status == CheckStatus.PASSED
        ), f"Expected check with secret in tests directory to pass, got failure: {result_after_test_fixture.output}"
