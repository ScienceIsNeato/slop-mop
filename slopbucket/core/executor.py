"""Parallel execution engine for quality gate checks.

The executor manages running multiple checks in parallel, respecting
dependencies, and implementing fail-fast behavior.
"""

import concurrent.futures
import logging
import threading
import time
from typing import Callable, Dict, List, Optional, Set

from slopbucket.checks.base import BaseCheck
from slopbucket.core.registry import CheckRegistry, get_registry
from slopbucket.core.result import CheckResult, CheckStatus, ExecutionSummary

logger = logging.getLogger(__name__)


class CheckExecutor:
    """Parallel executor for quality gate checks.

    Features:
    - Parallel execution for independent checks
    - Dependency resolution
    - Fail-fast mode
    - Progress callbacks
    - Configurable thread pool
    """

    DEFAULT_MAX_WORKERS = 4

    def __init__(
        self,
        registry: Optional[CheckRegistry] = None,
        max_workers: int = DEFAULT_MAX_WORKERS,
        fail_fast: bool = True,
    ):
        """Initialize the executor.

        Args:
            registry: Check registry to use (default: global registry)
            max_workers: Maximum parallel workers
            fail_fast: Stop on first failure
        """
        self._registry = registry or get_registry()
        self._max_workers = max_workers
        self._fail_fast = fail_fast
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._results: Dict[str, CheckResult] = {}
        self._on_check_complete: Optional[Callable[[CheckResult], None]] = None

    def set_progress_callback(self, callback: Callable[[CheckResult], None]) -> None:
        """Set callback for check completion events.

        Args:
            callback: Function called with CheckResult when each check completes
        """
        self._on_check_complete = callback

    def run_checks(
        self,
        project_root: str,
        check_names: List[str],
        config: Optional[Dict] = None,
        auto_fix: bool = True,
    ) -> ExecutionSummary:
        """Run specified checks against a project.

        Args:
            project_root: Path to project root directory
            check_names: List of check names or aliases to run
            config: Configuration dictionary
            auto_fix: Whether to attempt auto-fixing issues

        Returns:
            ExecutionSummary with all results
        """
        start_time = time.time()
        config = config or {}

        # Reset state
        self._stop_event.clear()
        self._results.clear()

        # Get check instances
        checks = self._registry.get_checks(check_names, config)
        if not checks:
            logger.warning("No checks to run")
            return ExecutionSummary.from_results([], 0)

        # Auto-include dependencies that weren't explicitly requested
        checks = self._expand_dependencies(checks, config)

        # Filter to applicable checks
        applicable = [c for c in checks if c.is_applicable(project_root)]
        skipped = [c for c in checks if c not in applicable]

        # Log skipped checks
        for check in skipped:
            logger.info(f"Skipping {check.full_name}: not applicable to this project")
            self._results[check.full_name] = CheckResult(
                name=check.full_name,
                status=CheckStatus.SKIPPED,
                duration=0,
                output="Check not applicable to this project",
            )

        if not applicable:
            duration = time.time() - start_time
            return ExecutionSummary.from_results(list(self._results.values()), duration)

        # Build dependency graph
        dep_graph = self._build_dependency_graph(applicable)

        # Execute checks respecting dependencies
        self._execute_with_dependencies(applicable, dep_graph, project_root, auto_fix)

        duration = time.time() - start_time
        return ExecutionSummary.from_results(list(self._results.values()), duration)

    def _expand_dependencies(
        self, checks: List[BaseCheck], config: Dict
    ) -> List[BaseCheck]:
        """Expand check list to include all dependencies.

        If a check depends on another check that wasn't explicitly requested,
        automatically add the dependency to the check list.

        Args:
            checks: Initial list of checks
            config: Configuration dictionary

        Returns:
            Expanded list including all dependencies
        """
        check_map = {c.full_name: c for c in checks}
        to_process = list(checks)
        processed: Set[str] = set()

        while to_process:
            check = to_process.pop(0)
            if check.full_name in processed:
                continue
            processed.add(check.full_name)

            # Check each dependency
            for dep_name in check.depends_on:
                if dep_name not in check_map:
                    # Dependency not in our list - try to get it
                    dep_checks = self._registry.get_checks([dep_name], config)
                    if dep_checks:
                        dep_check = dep_checks[0]
                        check_map[dep_check.full_name] = dep_check
                        to_process.append(dep_check)
                        logger.info(
                            f"Auto-including {dep_check.full_name} "
                            f"(dependency of {check.full_name})"
                        )

        return list(check_map.values())

    def _build_dependency_graph(self, checks: List[BaseCheck]) -> Dict[str, Set[str]]:
        """Build dependency graph for checks.

        Args:
            checks: List of checks to analyze

        Returns:
            Dict mapping check full_name to set of dependency full_names
        """
        check_names = {c.full_name for c in checks}
        graph: Dict[str, Set[str]] = {}

        for check in checks:
            # Only include dependencies that are in our check list
            deps = set(check.depends_on) & check_names
            graph[check.full_name] = deps

        return graph

    def _execute_with_dependencies(
        self,
        checks: List[BaseCheck],
        dep_graph: Dict[str, Set[str]],
        project_root: str,
        auto_fix: bool,
    ) -> None:
        """Execute checks respecting dependencies.

        Uses topological ordering to ensure dependencies run first.

        Args:
            checks: Checks to execute
            dep_graph: Dependency graph
            project_root: Project root path
            auto_fix: Whether to auto-fix
        """
        check_map = {c.full_name: c for c in checks}
        completed: Set[str] = set()
        pending = set(check_map.keys())

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self._max_workers
        ) as executor:
            futures: Dict[concurrent.futures.Future, str] = {}

            while (pending or futures) and not self._stop_event.is_set():
                # Find checks whose dependencies are all completed
                ready = []
                skipped_due_to_deps = []
                for name in list(pending):  # Iterate over a copy
                    deps = dep_graph.get(name, set())
                    if deps <= completed:
                        # Check if dependencies all passed
                        deps_passed = all(
                            self._results.get(
                                d, CheckResult(d, CheckStatus.PASSED, 0)
                            ).passed
                            for d in deps
                        )
                        if deps_passed or not deps:
                            ready.append(name)
                        else:
                            # Mark for skipping due to failed dependency
                            skipped_due_to_deps.append(name)

                # Process skipped checks
                for name in skipped_due_to_deps:
                    self._results[name] = CheckResult(
                        name=name,
                        status=CheckStatus.SKIPPED,
                        duration=0,
                        output="Skipped due to failed dependency",
                    )
                    pending.discard(name)
                    completed.add(name)

                # Submit ready checks
                for name in ready:
                    if name in pending:
                        check = check_map[name]
                        future = executor.submit(
                            self._run_single_check,
                            check,
                            project_root,
                            auto_fix,
                        )
                        futures[future] = name
                        pending.discard(name)

                # Wait for at least one check to complete
                if futures:
                    done, _ = concurrent.futures.wait(
                        futures.keys(),
                        return_when=concurrent.futures.FIRST_COMPLETED,
                    )

                    for future in done:
                        name = futures.pop(future)
                        try:
                            result = future.result()
                            with self._lock:
                                self._results[name] = result
                            completed.add(name)

                            # Notify callback
                            if self._on_check_complete:
                                self._on_check_complete(result)

                            # Fail fast
                            if self._fail_fast and result.failed:
                                logger.info(f"Fail-fast triggered by {name}")
                                self._stop_event.set()

                        except Exception as e:
                            logger.error(f"Check {name} raised exception: {e}")
                            with self._lock:
                                self._results[name] = CheckResult(
                                    name=name,
                                    status=CheckStatus.ERROR,
                                    duration=0,
                                    error=str(e),
                                )
                            completed.add(name)

                elif not ready:
                    # No checks ready and no futures pending - deadlock or done
                    break

        # Handle any remaining pending checks (due to fail-fast)
        for name in pending:
            if name not in self._results:
                self._results[name] = CheckResult(
                    name=name,
                    status=CheckStatus.SKIPPED,
                    duration=0,
                    output="Skipped due to fail-fast",
                )

    def _run_single_check(
        self,
        check: BaseCheck,
        project_root: str,
        auto_fix: bool,
    ) -> CheckResult:
        """Run a single check, optionally attempting auto-fix.

        Args:
            check: Check to run
            project_root: Project root path
            auto_fix: Whether to attempt auto-fix

        Returns:
            CheckResult
        """
        logger.info(f"Running {check.display_name}")

        # Try auto-fix first if enabled
        if auto_fix and check.can_auto_fix():
            try:
                fixed = check.auto_fix(project_root)
                if fixed:
                    logger.info(f"Auto-fixed issues for {check.name}")
            except Exception as e:
                logger.warning(f"Auto-fix failed for {check.name}: {e}")

        # Run the check
        try:
            result = check.run(project_root)
            return result
        except Exception as e:
            logger.error(f"Check {check.full_name} failed with exception: {e}")
            return CheckResult(
                name=check.full_name,
                status=CheckStatus.ERROR,
                duration=0,
                error=str(e),
            )


# Convenience function
def run_quality_checks(
    project_root: str,
    checks: List[str],
    config: Optional[Dict] = None,
    fail_fast: bool = True,
    auto_fix: bool = True,
) -> ExecutionSummary:
    """Run quality checks against a project.

    Args:
        project_root: Path to project root
        checks: List of check names or aliases
        config: Configuration dictionary
        fail_fast: Stop on first failure
        auto_fix: Attempt auto-fixing

    Returns:
        ExecutionSummary with all results
    """
    executor = CheckExecutor(fail_fast=fail_fast)
    return executor.run_checks(project_root, checks, config, auto_fix)
