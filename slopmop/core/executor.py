"""Parallel execution engine for quality gate checks.

The executor manages running multiple checks in parallel, respecting
dependencies, and implementing fail-fast behavior.
"""

import concurrent.futures
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from slopmop.checks.base import BaseCheck
from slopmop.core.registry import CheckRegistry, get_registry
from slopmop.core.result import CheckResult, CheckStatus, ExecutionSummary, ScopeInfo

logger = logging.getLogger(__name__)


def _is_gate_enabled_in_config(
    check: BaseCheck, config: Dict[str, Any]
) -> Tuple[bool, str]:
    """Check if a gate is enabled in the config.

    Args:
        check: The check instance
        config: Configuration dictionary from .sb_config.json

    Returns:
        Tuple of (is_enabled, reason_if_disabled)
    """
    # Check the disabled_gates list first (sm config --disable uses this)
    disabled_gates_val: object = config.get("disabled_gates", [])
    if isinstance(disabled_gates_val, list) and check.full_name in disabled_gates_val:
        return False, f"{check.full_name} is in disabled_gates list"

    category_key = check.category.key  # e.g., "python", "javascript", "quality"
    gate_name = check.name  # e.g., "lint-format", "dead-code"

    # Check if language/category is enabled
    category_val: object = config.get(category_key)
    if isinstance(category_val, dict):
        enabled_val = category_val.get("enabled")  # type: ignore[reportUnknownMemberType]
        if enabled_val is False:
            return False, f"{category_key} language is disabled in config"

        # Check if specific gate is disabled
        gates_val = category_val.get("gates")  # type: ignore[reportUnknownMemberType]
        if isinstance(gates_val, dict) and gate_name in gates_val:
            gate_cfg = gates_val.get(gate_name)  # type: ignore[reportUnknownMemberType]
            if isinstance(gate_cfg, dict) and gate_cfg.get("enabled") is False:  # type: ignore[reportUnknownMemberType]
                return False, f"{check.full_name} is disabled in config"

    return True, ""


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
        self._on_check_start: Optional[Callable[[str, Optional[str]], None]] = None
        self._on_check_disabled: Optional[Callable[[str], None]] = None
        self._on_check_na: Optional[Callable[[str], None]] = None
        self._on_total_determined: Optional[Callable[[int], None]] = None
        self._on_pending_checks: Optional[
            Callable[[List[tuple[str, Optional[str]]]], None]
        ] = None

    def set_progress_callback(self, callback: Callable[[CheckResult], None]) -> None:
        """Set callback for check completion events.

        Args:
            callback: Function called with CheckResult when each check completes
        """
        self._on_check_complete = callback

    def set_start_callback(
        self, callback: Callable[[str, Optional[str]], None]
    ) -> None:
        """Set callback for check start events.

        Args:
            callback: Function called with (check_name, category) when a check starts
        """
        self._on_check_start = callback

    def set_disabled_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for check disabled events.

        Args:
            callback: Function called with check name when a check is disabled
        """
        self._on_check_disabled = callback

    def set_na_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for not-applicable check events.

        Args:
            callback: Function called with check name when a check is N/A
        """
        self._on_check_na = callback

    def set_total_callback(self, callback: Callable[[int], None]) -> None:
        """Set callback for when total check count is determined.

        Args:
            callback: Function called with total number of checks to run
        """
        self._on_total_determined = callback

    def set_pending_callback(
        self, callback: Callable[[List[tuple[str, Optional[str]]]], None]
    ) -> None:
        """Set callback for registering all applicable checks as pending.

        Called after applicability filtering, before execution begins.

        Args:
            callback: Function called with list of (full_name, category_key) tuples
        """
        self._on_pending_checks = callback

    def run_checks(
        self,
        project_root: str,
        check_names: List[str],
        config: Optional[Dict[str, Any]] = None,
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

        # Filter out disabled checks (by config), including dependents
        disabled_gates: Set[str] = set()
        for check in checks:
            is_enabled, reason = _is_gate_enabled_in_config(check, config)
            if not is_enabled:
                disabled_gates.add(check.full_name)
                if self._on_check_disabled:
                    self._on_check_disabled(check.full_name)
                else:
                    logger.info(f"Disabled — {check.full_name}: {reason}")

        # Propagate: if a dependency is disabled, disable its dependents too
        changed = True
        while changed:
            changed = False
            for check in checks:
                if check.full_name not in disabled_gates:
                    for dep in check.depends_on:
                        if dep in disabled_gates:
                            disabled_gates.add(check.full_name)
                            if self._on_check_disabled:
                                self._on_check_disabled(check.full_name)
                            else:
                                logger.info(
                                    f"Disabled — {check.full_name}: "
                                    f"dependency {dep} is disabled"
                                )
                            changed = True
                            break

        enabled_checks: List[BaseCheck] = [
            c for c in checks if c.full_name not in disabled_gates
        ]

        if not enabled_checks:
            logger.warning("All checks are disabled")
            duration = time.time() - start_time
            return ExecutionSummary.from_results(list(self._results.values()), duration)

        # Filter to applicable checks
        applicable = [c for c in enabled_checks if c.is_applicable(project_root)]
        skipped = [c for c in enabled_checks if c not in applicable]

        # Log non-applicable checks with reason
        for check in skipped:
            reason = check.skip_reason(project_root)
            logger.debug(f"Not applicable — {check.full_name}: {reason}")
            self._results[check.full_name] = CheckResult(
                name=check.full_name,
                status=CheckStatus.NOT_APPLICABLE,
                duration=0,
                output=reason,
            )
            # Notify via dedicated N/A callback so display can label them
            # separately from config-disabled checks in the footer.
            if self._on_check_na:
                self._on_check_na(check.full_name)

        if not applicable:
            duration = time.time() - start_time
            return ExecutionSummary.from_results(list(self._results.values()), duration)

        # Notify total checks determined
        if self._on_total_determined:
            self._on_total_determined(len(applicable))

        # Register all applicable checks as pending (for display)
        if self._on_pending_checks:
            pending_info = [
                (c.full_name, c.category.key if c.category else None)
                for c in applicable
            ]
            self._on_pending_checks(pending_info)

        # Build dependency graph
        dep_graph = self._build_dependency_graph(applicable)

        # Execute checks respecting dependencies
        self._execute_with_dependencies(applicable, dep_graph, project_root, auto_fix)

        duration = time.time() - start_time
        return ExecutionSummary.from_results(list(self._results.values()), duration)

    def _expand_dependencies(
        self, checks: List[BaseCheck], config: Dict[str, Any]
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

        # Don't use `with` — we need to control shutdown behavior for fail-fast.
        # The context manager calls shutdown(wait=True) which blocks until all
        # in-flight futures complete, causing a multi-second hang after fail-fast.
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=self._max_workers)
        futures: Dict[concurrent.futures.Future[CheckResult], str] = {}

        try:
            while (pending or futures) and not self._stop_event.is_set():
                # Find checks whose dependencies are all completed
                ready: List[str] = []
                skipped_due_to_deps: List[str] = []
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
                    result = CheckResult(
                        name=name,
                        status=CheckStatus.SKIPPED,
                        duration=0,
                        output="Skipped due to failed dependency",
                    )
                    self._results[name] = result
                    pending.discard(name)
                    completed.add(name)
                    # Notify display so progress bar reaches 100%
                    if self._on_check_complete:
                        self._on_check_complete(result)

                # Submit ready checks
                for name in ready:
                    if name in pending:
                        check = check_map[name]

                        # Notify start callback before submitting
                        if self._on_check_start:
                            category = check.category.key if check.category else None
                            self._on_check_start(name, category)

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
                                logger.debug(f"Fail-fast triggered by {name}")
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
        finally:
            if self._stop_event.is_set():
                # Fail-fast: cancel queued futures and don't wait for running ones
                for future in futures:
                    future.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
            else:
                # Normal exit: wait for everything to finish cleanly
                executor.shutdown(wait=True)

        # Handle any remaining pending checks (due to fail-fast)
        for name in pending:
            if name not in self._results:
                result = CheckResult(
                    name=name,
                    status=CheckStatus.SKIPPED,
                    duration=0,
                    output="Skipped due to fail-fast",
                )
                self._results[name] = result
                if self._on_check_complete:
                    self._on_check_complete(result)

        # Handle submitted-but-cancelled futures (fail-fast cancelled them after submission)
        for future, name in list(futures.items()):
            if name not in self._results:
                try:
                    # Future may have completed before cancel took effect
                    result = future.result(timeout=0)
                except Exception:
                    result = CheckResult(
                        name=name,
                        status=CheckStatus.SKIPPED,
                        duration=0,
                        output="Skipped due to fail-fast",
                    )
                self._results[name] = result
                if self._on_check_complete:
                    self._on_check_complete(result)

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
        logger.debug(f"Running {check.display_name}")

        # Measure scope before running (lightweight file count)
        scope: Optional[ScopeInfo] = None
        measure_fn = getattr(check, "measure_scope", None)
        if callable(measure_fn):
            try:
                scope_result = measure_fn(project_root)
                if isinstance(scope_result, ScopeInfo):
                    scope = scope_result
            except Exception as e:
                logger.debug(f"Scope measurement failed for {check.full_name}: {e}")

        # Try auto-fix first if enabled
        if auto_fix and check.can_auto_fix():
            try:
                fixed = check.auto_fix(project_root)
                if fixed:
                    logger.debug(f"Auto-fixed issues for {check.name}")
            except Exception as e:
                logger.warning(f"Auto-fix failed for {check.name}: {e}")

        # Run the check
        try:
            result = check.run(project_root)
            # Attach scope metrics if the check reported them
            if scope is not None and result.scope is None:
                result.scope = scope
            return result
        except Exception as e:
            logger.error(f"Check {check.full_name} failed with exception: {e}")
            return CheckResult(
                name=check.full_name,
                status=CheckStatus.ERROR,
                duration=0,
                error=str(e),
                scope=scope,
            )


# Convenience function
def run_quality_checks(
    project_root: str,
    checks: List[str],
    config: Optional[Dict[str, Any]] = None,
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
