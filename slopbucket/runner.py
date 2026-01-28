"""
Runner — Parallel check orchestration with fail-fast support.

Executes checks concurrently via ThreadPoolExecutor. Supports:
- Configurable parallelism (parallel mode or sequential)
- Fail-fast: stops remaining checks on first failure
- Result aggregation and summary generation
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from slopbucket.base_check import BaseCheck
from slopbucket.config import RunnerConfig
from slopbucket.result import CheckResult, CheckStatus, RunSummary

logger = logging.getLogger(__name__)


class Runner:
    """Orchestrates check execution with parallel support."""

    def __init__(self, config: Optional[RunnerConfig] = None):
        self.config = config or RunnerConfig()
        self._stop_flag = False

    def run(
        self,
        checks: List[BaseCheck],
        profile_name: str = "",
    ) -> RunSummary:
        """Execute a list of checks and return aggregated results.

        Args:
            checks: Ordered list of BaseCheck instances to run.
            profile_name: Label for the results summary (e.g. 'commit').

        Returns:
            RunSummary with all results, timing, and pass/fail state.
        """
        summary = RunSummary(profile_name=profile_name)
        self._stop_flag = False

        if self.config.verbose:
            logger.info(
                "Running %d checks (parallel=%s, fail_fast=%s)",
                len(checks),
                self.config.parallel,
                self.config.fail_fast,
            )

        if self.config.parallel and len(checks) > 1:
            summary.results = self._run_parallel(checks)
        else:
            summary.results = self._run_sequential(checks)

        summary.end_time = time.time()
        return summary

    def _run_sequential(self, checks: List[BaseCheck]) -> list:
        """Run checks one at a time. Respects fail-fast."""
        results = []
        for check in checks:
            if self._stop_flag:
                break

            if self.config.verbose:
                logger.info("  Running: %s", check.name)

            result = check.run_timed(self.config.working_dir)
            results.append(result)

            if result.failed and self.config.fail_fast:
                self._stop_flag = True
                if self.config.verbose:
                    logger.info("  FAIL-FAST triggered by: %s", check.name)

        return results

    # Checks that consume artifacts produced by Wave 1 (e.g. coverage.xml).
    # These must run after python-tests completes to avoid race conditions.
    _WAVE_2_CHECKS = {
        "python-coverage",
        "python-diff-coverage",
        "python-new-code-coverage",
    }

    def _run_parallel(self, checks: List[BaseCheck]) -> list:
        """Run checks in parallel with dependency ordering.

        Wave 1: all checks except coverage consumers (run in parallel).
        Wave 2: coverage checks that depend on Wave 1 artifacts.
        """
        wave1 = [c for c in checks if c.name not in self._WAVE_2_CHECKS]
        wave2 = [c for c in checks if c.name in self._WAVE_2_CHECKS]

        results = self._run_wave(wave1)
        if not self._stop_flag and wave2:
            results.extend(self._run_wave(wave2))

        # Sort results to match original check order
        check_order = {check.name: i for i, check in enumerate(checks)}
        results.sort(key=lambda r: check_order.get(r.name, 999))

        return results

    def _run_wave(self, checks: List[BaseCheck]) -> list:
        """Execute a batch of checks in parallel."""
        results = []
        results_lock = __import__("threading").Lock()

        def _execute(check: BaseCheck) -> CheckResult:
            if self._stop_flag:
                return CheckResult(
                    name=check.name,
                    status=CheckStatus.SKIPPED,
                    output="Skipped (fail-fast triggered)",
                )
            return check.run_timed(self.config.working_dir)

        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            futures = {executor.submit(_execute, check): check for check in checks}

            for future in as_completed(futures):
                result = future.result()
                with results_lock:
                    results.append(result)

                    if result.failed and self.config.fail_fast:
                        self._stop_flag = True
                        if self.config.verbose:
                            logger.info("  FAIL-FAST triggered by: %s", result.name)

        return results
