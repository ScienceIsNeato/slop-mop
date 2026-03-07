"""Parallel execution engine for quality gate checks.

The executor manages running multiple checks in parallel, respecting
dependencies, and implementing fail-fast behavior.
"""

import concurrent.futures
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, cast

from slopmop.checks.base import BaseCheck
from slopmop.core.cache import (
    compute_fingerprint,
    get_cached_result,
    load_cache,
    save_cache,
    store_result,
)
from slopmop.core.registry import CheckRegistry, get_registry
from slopmop.core.result import (
    CheckResult,
    CheckStatus,
    ExecutionSummary,
    ScopeInfo,
    SkipReason,
)

logger = logging.getLogger(__name__)

_SKIP_FAIL_FAST = "Skipped due to fail-fast"


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

    category_key = check.category.key  # e.g., "overconfidence", "laziness", "myopia"
    gate_name = check.name  # e.g., "lint-format", "dead-code.py"

    # Check if language/category is enabled
    category_val: object = config.get(category_key)
    if isinstance(category_val, dict):
        cat_dict = cast(Dict[str, Any], category_val)
        if cat_dict.get("enabled") is False:
            return False, f"{category_key} language is disabled in config"

        # Check if specific gate is disabled
        gates_val = cat_dict.get("gates")
        if isinstance(gates_val, dict) and gate_name in gates_val:
            gate_cfg = cast(Dict[str, Any], gates_val).get(gate_name)
            if isinstance(gate_cfg, dict):
                gate_dict = cast(Dict[str, Any], gate_cfg)
                if gate_dict.get("enabled") is False:
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
        self._cache: Dict[str, Any] = {}
        self._fingerprint: Optional[str] = None
        self._cache_dirty = False
        self._on_check_complete: Optional[Callable[[CheckResult], None]] = None
        self._on_check_start: Optional[Callable[[str, Optional[str]], None]] = None
        self._on_check_disabled: Optional[Callable[[str], None]] = None
        self._on_check_na: Optional[Callable[[str], None]] = None
        self._on_total_determined: Optional[Callable[[int], None]] = None
        self._on_pending_checks: Optional[
            Callable[[List[tuple[str, Optional[str], bool, Optional[str]]]], None]
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
        self,
        callback: Callable[
            [List[tuple[str, Optional[str], bool, Optional[str]]]], None
        ],
    ) -> None:
        """Set callback for registering all applicable checks as pending.

        Called after applicability filtering, before execution begins.

        Args:
            callback: Function called with list of
                (full_name, category_key, is_custom, role) tuples
        """
        self._on_pending_checks = callback

    def run_checks(
        self,
        project_root: str,
        check_names: List[str],
        config: Optional[Dict[str, Any]] = None,
        auto_fix: bool = True,
        swabbing_time: Optional[int] = None,
        timings: Optional[Dict[str, float]] = None,
    ) -> ExecutionSummary:
        """Run specified checks against a project.

        Args:
            project_root: Path to project root directory
            check_names: List of check names or aliases to run
            config: Configuration dictionary
            auto_fix: Whether to attempt auto-fixing issues
            swabbing_time: Wall-clock time budget in seconds.  Gates
                with historical timing data are scheduled using a
                dual-lane strategy until budget expires, then skipped.
                Gates without timing data always run (to establish a
                baseline).  ``None`` or ``<= 0`` means no limit.
            timings: Historical timing data mapping check full_name to
                average duration in seconds.  Typically loaded via
                ``slopmop.reporting.timings.load_timings()``.

        Returns:
            ExecutionSummary with all results
        """
        start_time = time.time()
        config = config or {}

        # Reset state
        self._stop_event.clear()
        self._results.clear()

        # Load cache and compute fingerprint for this run
        self._cache = load_cache(project_root)
        self._fingerprint = compute_fingerprint(project_root)
        self._cache_dirty = False

        # Get check instances
        checks = self._registry.get_checks(check_names, config)
        if not checks:
            logger.warning("No checks to run")
            return ExecutionSummary.from_results([], 0)

        # Auto-include dependencies that weren't explicitly requested
        checks = self._expand_dependencies(checks, config)

        # Filter superseded checks: if a check's superseded_by target is
        # also in the run set, skip the weaker check.  This happens during
        # scour runs where both vulnerability-blindness.py (swab) and
        # dependency-risk.py (scour) would otherwise both execute.
        requested_names = {c.full_name for c in checks}
        superseded: Set[str] = set()
        for check in checks:
            target = check.superseded_by
            if target and target in requested_names:
                superseded.add(check.full_name)
                logger.debug(
                    f"Superseded — {check.full_name}: "
                    f"replaced by {target} in this run"
                )
        if superseded:
            for check in checks:
                if check.full_name in superseded:
                    self._results[check.full_name] = CheckResult(
                        name=check.full_name,
                        status=CheckStatus.SKIPPED,
                        duration=0,
                        output=f"Superseded by {check.superseded_by} in this run",
                        skip_reason=SkipReason.SUPERSEDED,
                    )
            checks = [c for c in checks if c.full_name not in superseded]

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

        # Record disabled checks in results so they appear in the summary
        for check in checks:
            if check.full_name in disabled_gates:
                self._results[check.full_name] = CheckResult(
                    name=check.full_name,
                    status=CheckStatus.SKIPPED,
                    duration=0,
                    output="Disabled in config",
                    skip_reason=SkipReason.DISABLED,
                )

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
                skip_reason=SkipReason.NOT_APPLICABLE,
            )
            # Notify via dedicated N/A callback so display can label them
            # separately from config-disabled checks in the footer.
            if self._on_check_na:
                self._on_check_na(check.full_name)

        if not applicable:
            duration = time.time() - start_time
            return ExecutionSummary.from_results(list(self._results.values()), duration)

        # ── Time budget ───────────────────────────────────────────────
        # Budget enforcement now happens at runtime inside
        # _execute_with_dependencies() using wall-clock time, not as a
        # pre-filter.  swabbing_time is passed through so the execution
        # loop can stop scheduling timed gates once wall-clock time
        # exceeds the budget.

        # Notify total checks determined
        if self._on_total_determined:
            self._on_total_determined(len(applicable))

        # Register all applicable checks as pending (for display)
        if self._on_pending_checks:
            pending_info = [
                (
                    c.full_name,
                    c.category.key if c.category else None,
                    getattr(c, "is_custom_gate", False),
                    c.role.value if hasattr(c, "role") else None,
                )
                for c in applicable
            ]
            self._on_pending_checks(pending_info)

        # Build dependency graph
        dep_graph = self._build_dependency_graph(applicable)

        # Execute checks respecting dependencies
        self._execute_with_dependencies(
            applicable,
            dep_graph,
            project_root,
            auto_fix,
            timings=timings,
            swabbing_time=swabbing_time,
        )

        # Persist cache if any entries were added/updated
        if self._cache_dirty:
            save_cache(project_root, self._cache)

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
        timings: Optional[Dict[str, float]] = None,
        swabbing_time: Optional[int] = None,
    ) -> None:
        """Execute checks respecting dependencies with wall-clock budget.

        Uses a **dual-lane** scheduling strategy when a time budget is
        active.  Each scheduling round fills thread pool slots from two
        ends of the ready queue:

        * **Heavy lane** (``N − 1`` slots): longest-estimated gates
          first, so expensive work starts early.
        * **Light lane** (``1`` slot): shortest-estimated gate, making
          forward progress on quick wins while the heavy work runs.

        Wall-clock time determines when to stop: once elapsed time
        exceeds the budget, no new *timed* gates are submitted.
        Already-running gates finish naturally.  Gates without timing
        history always run regardless of budget (to build a baseline).

        Without a budget, all ready gates are submitted at once, sorted
        longest-first (existing behaviour preserved).

        Args:
            checks: Checks to execute
            dep_graph: Dependency graph
            project_root: Project root path
            auto_fix: Whether to auto-fix
            timings: Optional historical timing map (name → seconds)
            swabbing_time: Time budget in seconds (None or ≤0 = no limit)
        """
        check_map = {c.full_name: c for c in checks}
        completed: Set[str] = set()
        pending = set(check_map.keys())
        timings = timings or {}

        budget_active = swabbing_time is not None and swabbing_time > 0
        budget_start = time.time()
        budget_expired = False
        budget_elapsed: float = 0.0

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
                        skip_reason=SkipReason.FAILED_DEPENDENCY,
                    )
                    self._results[name] = result
                    pending.discard(name)
                    completed.add(name)
                    # Notify display so progress bar reaches 100%
                    if self._on_check_complete:
                        self._on_check_complete(result)

                # ── Wall-clock budget check ────────────────────────
                if budget_active and not budget_expired:
                    budget_elapsed = time.time() - budget_start
                    assert swabbing_time is not None  # for type checker
                    if budget_elapsed >= swabbing_time:
                        budget_expired = True

                # ── Determine which gates to submit ────────────────
                to_submit = self._select_gates_for_submission(
                    ready,
                    pending,
                    completed,
                    futures,
                    timings,
                    budget_active,
                    budget_expired,
                    budget_elapsed,
                    swabbing_time,
                )

                # Submit selected gates
                for name in to_submit:
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

                # Wait for at least one check to complete.
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
                # Fail-fast: cancel queued futures, then perform a
                # *waiting* shutdown.  The waiting shutdown is
                # deliberate — without it, Python's atexit handler
                # for ThreadPoolExecutor calls shutdown(wait=True)
                # during sys.exit(), blocking on worker threads that
                # are still finishing their current task.  By waiting
                # here (where we've already set the stop event so
                # newly-started checks short-circuit via the guard in
                # _run_single_check), all workers finish promptly and
                # the atexit handler becomes a no-op.
                for future in futures:
                    future.cancel()
                executor.shutdown(wait=True, cancel_futures=True)
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
                    output=_SKIP_FAIL_FAST,
                    skip_reason=SkipReason.FAIL_FAST,
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
                        output=_SKIP_FAIL_FAST,
                        skip_reason=SkipReason.FAIL_FAST,
                    )
                self._results[name] = result
                if self._on_check_complete:
                    self._on_check_complete(result)

    def _select_gates_for_submission(
        self,
        ready: List[str],
        pending: Set[str],
        completed: Set[str],
        futures: Dict[concurrent.futures.Future[CheckResult], str],
        timings: Dict[str, float],
        budget_active: bool,
        budget_expired: bool,
        budget_elapsed: float,
        swabbing_time: Optional[int],
    ) -> List[str]:
        """Choose which ready gates to submit this iteration.

        Implements three strategies depending on budget state:

        1. **No budget** — submit all ready gates, longest-first
           (maximise parallelism by starting slow work early).
        2. **Budget expired** — skip all timed ready gates
           (record TIME_BUDGET results), submit only untimed gates.
        3. **Budget active, not expired** — dual-lane slot-based
           submission: ``N − 1`` slots from the heavy end, ``1`` from
           the light end.  Untimed gates always get priority.

        Gates without timing history are *always* submitted regardless
        of budget state (they need to run to build a baseline).

        Budget-skipped gates are added to ``completed`` so that their
        dependents can be resolved (skipped via FAILED_DEPENDENCY).

        Args:
            ready: Names of checks whose dependencies are satisfied.
            pending: Mutable set of not-yet-submitted check names.  This
                method removes budget-skipped names from pending and adds
                TIME_BUDGET results to ``self._results``.
            completed: Mutable set of completed check names.  Budget-skipped
                gates are added here so dependents proceed correctly.
            futures: Currently in-flight futures (used to calculate
                available thread pool slots).
            timings: Historical timing map (name → seconds).
            budget_active: Whether a positive budget was configured.
            budget_expired: Whether wall-clock time exceeded the budget.
            budget_elapsed: Seconds elapsed since execution started.
            swabbing_time: The configured budget in seconds.

        Returns:
            List of check names to submit to the thread pool.
        """
        if not budget_active:
            # No budget: submit all, longest-first (original behaviour)
            if timings:
                ready.sort(key=lambda n: timings.get(n, 0), reverse=True)
            return ready

        # Split ready gates into timed (have estimates) and untimed
        timed = [n for n in ready if n in timings]
        untimed = [n for n in ready if n not in timings]

        if budget_expired:
            # Budget expired: skip all timed gates, run only untimed.
            # Add to completed so dependents get FAILED_DEPENDENCY.
            self._record_budget_skips(timed, timings, budget_elapsed, swabbing_time)
            for name in timed:
                pending.discard(name)
                completed.add(name)
            return untimed

        # Budget active, not yet expired — dual-lane slot-based submission.
        # Only submit to available slots so we maintain control over what
        # actually runs (vs queuing excess tasks in the thread pool).
        available_slots = self._max_workers - len(futures)
        if available_slots <= 0:
            return []

        # Untimed gates always submit first (they always run)
        to_submit = untimed[:]
        remaining_slots = max(0, available_slots - len(untimed))

        if remaining_slots > 0 and timed:
            # Sort timed gates: heaviest first for dual-lane selection
            timed.sort(key=lambda n: timings.get(n, 0), reverse=True)

            if remaining_slots >= 2 and len(timed) >= 2:
                # Dual-lane: N-1 from heavy end, 1 from light end
                heavy_count = min(remaining_slots - 1, len(timed) - 1)
                heavy = timed[:heavy_count]
                # Light lane: lightest gate not already in heavy set
                light = [timed[-1]] if timed[-1] not in set(heavy) else []
                to_submit.extend(heavy + light)
            else:
                # 1 slot or 1 timed gate: take the heaviest (start
                # expensive work early — the core dual-lane insight)
                to_submit.extend(timed[:remaining_slots])

        return to_submit

    def _record_budget_skips(
        self,
        names: List[str],
        timings: Dict[str, float],
        elapsed: float,
        swabbing_time: Optional[int],
    ) -> None:
        """Record TIME_BUDGET skip results and fire callbacks.

        Called when the wall-clock budget has expired and timed gates
        can no longer be scheduled.

        Args:
            names: Gate names to mark as budget-skipped.
            timings: Historical timing map (name → seconds).
            elapsed: Wall-clock seconds elapsed when budget expired.
            swabbing_time: Configured budget in seconds.
        """
        for name in names:
            est = timings.get(name, 0)
            result = CheckResult(
                name=name,
                status=CheckStatus.SKIPPED,
                duration=0,
                output=(
                    f"Skipped — estimated {est:.1f}s "
                    f"(budget {swabbing_time}s expired "
                    f"after {elapsed:.1f}s wall-clock)"
                ),
                skip_reason=SkipReason.TIME_BUDGET,
            )
            self._results[name] = result
            # Advance progress bar
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
        # Short-circuit if fail-fast already triggered — avoids
        # starting expensive work after a failure is detected.
        if self._stop_event.is_set():
            return CheckResult(
                name=check.full_name,
                status=CheckStatus.SKIPPED,
                duration=0,
                output=_SKIP_FAIL_FAST,
                skip_reason=SkipReason.FAIL_FAST,
            )

        # Notify start callback NOW — when the thread pool worker
        # actually picks up this task, not when it was submitted.
        # This ensures start_time aligns with actual execution time,
        # so progress estimates compare apples to apples with the
        # historical durations stored in timings.json.
        if self._on_check_start:
            category = check.category.key if check.category else None
            self._on_check_start(check.full_name, category)

        # ── Cache check ───────────────────────────────────────────
        # If the project fingerprint hasn't changed since the last run,
        # return the cached result instantly.  Results that involved
        # auto-fix side effects are excluded at storage time (see
        # store_result), so a cache hit here is always safe to replay.
        if self._fingerprint:
            cached = get_cached_result(self._cache, check.full_name, self._fingerprint)
            if cached is not None:
                logger.debug(
                    f"Cache hit for {check.full_name} "
                    f"(status={cached.status.value})"
                )
                return cached

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
            # Store result in cache for next run
            if self._fingerprint:
                store_result(self._cache, check.full_name, self._fingerprint, result)
                self._cache_dirty = True
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
