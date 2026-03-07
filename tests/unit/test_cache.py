"""Tests for fingerprint-based result caching."""

import os
import time

from slopmop.checks.base import BaseCheck, Flaw, GateCategory
from slopmop.core.cache import (
    compute_fingerprint,
    get_cached_result,
    load_cache,
    save_cache,
    store_result,
)
from slopmop.core.executor import CheckExecutor
from slopmop.core.registry import CheckRegistry
from slopmop.core.result import (
    CheckResult,
    CheckStatus,
    Finding,
    FindingLevel,
    ScopeInfo,
)


class TestComputeFingerprint:
    """Tests for compute_fingerprint()."""

    def test_same_files_same_fingerprint(self, tmp_path):
        """Identical file state produces identical fingerprint."""
        (tmp_path / "main.py").write_text("print('hello')")
        fp1 = compute_fingerprint(str(tmp_path))
        fp2 = compute_fingerprint(str(tmp_path))
        assert fp1 == fp2

    def test_changed_file_changes_fingerprint(self, tmp_path):
        """Modifying a file changes the fingerprint."""
        src = tmp_path / "main.py"
        src.write_text("print('hello')")
        fp1 = compute_fingerprint(str(tmp_path))

        # Ensure mtime actually changes (some filesystems have 1s granularity)
        time.sleep(0.05)
        src.write_text("print('world')")
        # Force mtime to be different
        os.utime(src, (time.time() + 1, time.time() + 1))
        fp2 = compute_fingerprint(str(tmp_path))
        assert fp1 != fp2

    def test_new_file_changes_fingerprint(self, tmp_path):
        """Adding a new file changes the fingerprint."""
        (tmp_path / "main.py").write_text("print('hello')")
        fp1 = compute_fingerprint(str(tmp_path))
        (tmp_path / "other.py").write_text("x = 1")
        fp2 = compute_fingerprint(str(tmp_path))
        assert fp1 != fp2

    def test_config_change_changes_fingerprint(self, tmp_path):
        """Changing .sb_config.json changes the fingerprint."""
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / ".sb_config.json").write_text('{"version": "1.0"}')
        fp1 = compute_fingerprint(str(tmp_path))

        (tmp_path / ".sb_config.json").write_text('{"version": "2.0"}')
        fp2 = compute_fingerprint(str(tmp_path))
        assert fp1 != fp2

    def test_excludes_node_modules(self, tmp_path):
        """Files in excluded dirs don't affect fingerprint."""
        (tmp_path / "main.py").write_text("print('hello')")
        fp1 = compute_fingerprint(str(tmp_path))

        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("module.exports = {}")
        fp2 = compute_fingerprint(str(tmp_path))
        assert fp1 == fp2

    def test_excludes_git_dir(self, tmp_path):
        """Files in .git don't affect fingerprint."""
        (tmp_path / "main.py").write_text("print('hello')")
        fp1 = compute_fingerprint(str(tmp_path))

        git_dir = tmp_path / ".git" / "objects"
        git_dir.mkdir(parents=True)
        (git_dir / "abc123").write_text("blob data")
        fp2 = compute_fingerprint(str(tmp_path))
        assert fp1 == fp2

    def test_non_source_extensions_excluded(self, tmp_path):
        """Files with non-source extensions don't affect fingerprint."""
        (tmp_path / "main.py").write_text("print('hello')")
        fp1 = compute_fingerprint(str(tmp_path))

        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        (tmp_path / "data.csv").write_text("a,b,c")
        fp2 = compute_fingerprint(str(tmp_path))
        assert fp1 == fp2

    def test_empty_project(self, tmp_path):
        """Empty project produces a valid fingerprint."""
        fp = compute_fingerprint(str(tmp_path))
        assert isinstance(fp, str)
        assert len(fp) == 64  # SHA-256 hex digest

    def test_no_config_file(self, tmp_path):
        """Missing .sb_config.json doesn't crash."""
        (tmp_path / "main.py").write_text("x = 1")
        fp = compute_fingerprint(str(tmp_path))
        assert isinstance(fp, str)
        assert len(fp) == 64


class TestCacheIO:
    """Tests for load_cache / save_cache."""

    def test_save_and_load(self, tmp_path):
        """Round-trip: save then load returns same data."""
        cache = {"check1": {"fingerprint": "abc", "result": {"name": "check1"}}}
        save_cache(str(tmp_path), cache)
        loaded = load_cache(str(tmp_path))
        assert loaded == cache

    def test_load_nonexistent(self, tmp_path):
        """Loading from a path with no cache file returns empty dict."""
        loaded = load_cache(str(tmp_path))
        assert loaded == {}

    def test_load_corrupt_json(self, tmp_path):
        """Corrupt JSON returns empty dict."""
        cache_dir = tmp_path / ".slopmop"
        cache_dir.mkdir()
        (cache_dir / "cache.json").write_text("{corrupt")
        loaded = load_cache(str(tmp_path))
        assert loaded == {}

    def test_load_non_dict(self, tmp_path):
        """Non-dict JSON returns empty dict."""
        cache_dir = tmp_path / ".slopmop"
        cache_dir.mkdir()
        (cache_dir / "cache.json").write_text("[1, 2, 3]")
        loaded = load_cache(str(tmp_path))
        assert loaded == {}

    def test_save_creates_directory(self, tmp_path):
        """save_cache creates .slopmop directory if needed."""
        cache = {"a": 1}
        save_cache(str(tmp_path), cache)
        assert (tmp_path / ".slopmop" / "cache.json").exists()


class TestGetCachedResult:
    """Tests for get_cached_result()."""

    def test_cache_hit(self):
        """Returns result when fingerprint matches."""
        result = CheckResult(
            name="check1", status=CheckStatus.PASSED, duration=1.5, output="ok"
        )
        cache = {"check1": {"fingerprint": "abc123", "result": result.to_dict()}}
        cached = get_cached_result(cache, "check1", "abc123")
        assert cached is not None
        assert cached.name == "check1"
        assert cached.status == CheckStatus.PASSED
        assert cached.duration == 0.0  # Cached results have zero duration
        assert cached.cached is True

    def test_cache_miss_different_fingerprint(self):
        """Returns None when fingerprint doesn't match."""
        result = CheckResult(name="check1", status=CheckStatus.PASSED, duration=1.5)
        cache = {"check1": {"fingerprint": "abc123", "result": result.to_dict()}}
        cached = get_cached_result(cache, "check1", "different")
        assert cached is None

    def test_cache_miss_no_entry(self):
        """Returns None when check isn't in cache."""
        cached = get_cached_result({}, "check1", "abc123")
        assert cached is None

    def test_cache_miss_bad_entry(self):
        """Returns None when cache entry is malformed."""
        cache = {"check1": "not a dict"}
        cached = get_cached_result(cache, "check1", "abc123")
        assert cached is None

    def test_preserves_findings(self):
        """Cached result preserves structured findings."""
        result = CheckResult(
            name="check1",
            status=CheckStatus.FAILED,
            duration=2.0,
            output="issues found",
            findings=[
                Finding(
                    message="unused import",
                    level=FindingLevel.WARNING,
                    file="main.py",
                    line=5,
                )
            ],
        )
        cache = {"check1": {"fingerprint": "fp1", "result": result.to_dict()}}
        cached = get_cached_result(cache, "check1", "fp1")
        assert cached is not None
        assert len(cached.findings) == 1
        assert cached.findings[0].message == "unused import"
        assert cached.findings[0].file == "main.py"

    def test_preserves_scope(self):
        """Cached result preserves scope info."""
        result = CheckResult(
            name="check1",
            status=CheckStatus.PASSED,
            duration=1.0,
            scope=ScopeInfo(files=42, lines=3000),
        )
        cache = {"check1": {"fingerprint": "fp1", "result": result.to_dict()}}
        cached = get_cached_result(cache, "check1", "fp1")
        assert cached is not None
        assert cached.scope is not None
        assert cached.scope.files == 42
        assert cached.scope.lines == 3000


class TestStoreResult:
    """Tests for store_result()."""

    def test_stores_passed_result(self):
        """Passing results are stored."""
        cache: dict = {}
        result = CheckResult(name="check1", status=CheckStatus.PASSED, duration=1.0)
        store_result(cache, "check1", "fp1", result)
        assert "check1" in cache
        assert cache["check1"]["fingerprint"] == "fp1"

    def test_stores_failed_result(self):
        """Failing results are stored (user explicitly requested this)."""
        cache: dict = {}
        result = CheckResult(name="check1", status=CheckStatus.FAILED, duration=1.0)
        store_result(cache, "check1", "fp1", result)
        assert "check1" in cache

    def test_skips_error_result(self):
        """ERROR results are not cached (transient)."""
        cache: dict = {}
        result = CheckResult(
            name="check1", status=CheckStatus.ERROR, duration=0.0, error="boom"
        )
        store_result(cache, "check1", "fp1", result)
        assert "check1" not in cache

    def test_skips_auto_fixed_result(self):
        """Auto-fixed results are not cached (side-effecting)."""
        cache: dict = {}
        result = CheckResult(
            name="check1",
            status=CheckStatus.PASSED,
            duration=1.0,
            auto_fixed=True,
        )
        store_result(cache, "check1", "fp1", result)
        assert "check1" not in cache

    def test_overwrites_previous_entry(self):
        """New result overwrites previous cache entry."""
        cache: dict = {"check1": {"fingerprint": "old", "result": {"name": "check1"}}}
        result = CheckResult(name="check1", status=CheckStatus.PASSED, duration=0.5)
        store_result(cache, "check1", "new_fp", result)
        assert cache["check1"]["fingerprint"] == "new_fp"


class TestCheckResultFromDict:
    """Tests for CheckResult.from_dict()."""

    def test_round_trip(self):
        """to_dict → from_dict preserves all fields."""
        original = CheckResult(
            name="my-check",
            status=CheckStatus.FAILED,
            duration=2.5,
            output="some output",
            error="something broke",
            fix_suggestion="fix it",
            category="python",
            scope=ScopeInfo(files=10, lines=500),
            status_detail="detail",
            role="foundation",
            findings=[
                Finding(
                    message="issue",
                    level=FindingLevel.WARNING,
                    file="a.py",
                    line=10,
                    column=5,
                    rule_id="E001",
                    fix_strategy="do this",
                )
            ],
        )
        d = original.to_dict()
        restored = CheckResult.from_dict(d)
        assert restored.name == original.name
        assert restored.status == original.status
        assert restored.duration == original.duration
        assert restored.output == original.output
        assert restored.error == original.error
        assert restored.fix_suggestion == original.fix_suggestion
        assert restored.category == original.category
        assert restored.scope is not None
        assert restored.scope.files == 10
        assert restored.scope.lines == 500
        assert restored.status_detail == original.status_detail
        assert restored.role == original.role
        assert len(restored.findings) == 1
        assert restored.findings[0].message == "issue"
        assert restored.findings[0].level == FindingLevel.WARNING
        assert restored.findings[0].file == "a.py"
        assert restored.findings[0].line == 10
        assert restored.findings[0].column == 5
        assert restored.findings[0].rule_id == "E001"
        assert restored.findings[0].fix_strategy == "do this"

    def test_minimal_dict(self):
        """from_dict handles minimal input gracefully."""
        restored = CheckResult.from_dict({"name": "x", "status": "passed"})
        assert restored.name == "x"
        assert restored.status == CheckStatus.PASSED
        assert restored.duration == 0.0
        assert restored.output == ""
        assert restored.findings == []

    def test_unknown_status_defaults_to_passed(self):
        """Unknown status value falls back to PASSED."""
        restored = CheckResult.from_dict({"name": "x", "status": "unknown_thing"})
        assert restored.status == CheckStatus.PASSED

    def test_cached_field_preserved(self):
        """The cached flag survives round-trip."""
        result = CheckResult(
            name="x", status=CheckStatus.PASSED, duration=0, cached=True
        )
        d = result.to_dict()
        assert d.get("cached") is True
        restored = CheckResult.from_dict(d)
        assert restored.cached is True


# -- Executor-level cache integration tests ----------------------------------


class _SlowCheck(BaseCheck):
    """A check that takes measurable time, for cache timing tests."""

    _name = "slow-check"
    run_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def display_name(self) -> str:
        return "Slow Check"

    @property
    def category(self) -> GateCategory:
        return GateCategory.OVERCONFIDENCE

    @property
    def flaw(self) -> Flaw:
        return Flaw.OVERCONFIDENCE

    @property
    def depends_on(self) -> list:
        return []

    def is_applicable(self, project_root: str) -> bool:
        return True

    def run(self, project_root: str) -> CheckResult:
        type(self).run_count += 1
        time.sleep(0.1)  # Simulate real work
        return CheckResult(
            name=self.full_name,
            status=CheckStatus.PASSED,
            duration=0.1,
            output="OK",
        )


def _make_slow_check_class(name: str, status: CheckStatus = CheckStatus.PASSED):
    """Factory for slow check classes with unique names."""

    class DynamicSlowCheck(_SlowCheck):
        _name = name
        run_count = 0

        def run(self, project_root: str) -> CheckResult:
            type(self).run_count += 1
            time.sleep(0.1)
            return CheckResult(
                name=self.full_name,
                status=status,
                duration=0.1,
                output=f"Output from {name}",
            )

    return DynamicSlowCheck


class TestExecutorCache:
    """Integration tests: back-to-back executor runs use cache."""

    def test_second_run_uses_cache(self, tmp_path):
        """Back-to-back runs: second run returns cached results, no re-run."""
        # Create a source file so the fingerprint has something to hash
        (tmp_path / "main.py").write_text("print('hello')")

        check_cls = _make_slow_check_class("cached-test")
        registry = CheckRegistry()
        registry.register(check_cls)

        executor = CheckExecutor(registry=registry, fail_fast=False)

        # First run: check actually executes
        s1 = executor.run_checks(str(tmp_path), ["overconfidence:cached-test"])
        assert s1.passed == 1
        assert check_cls.run_count == 1

        # Second run: same source, should hit cache
        s2 = executor.run_checks(str(tmp_path), ["overconfidence:cached-test"])
        assert s2.passed == 1
        assert check_cls.run_count == 1  # No additional run
        # Verify the result is marked as cached
        cached_results = [r for r in s2.results if r.cached]
        assert len(cached_results) == 1

    def test_second_run_is_fast(self, tmp_path):
        """Back-to-back runs: second run takes virtually zero time."""
        (tmp_path / "main.py").write_text("print('hello')")

        # Register multiple slow checks
        checks = []
        for i in range(5):
            cls = _make_slow_check_class(f"speed-{i}")
            checks.append(cls)

        registry = CheckRegistry()
        for cls in checks:
            registry.register(cls)

        executor = CheckExecutor(registry=registry, fail_fast=False)
        names = [f"overconfidence:speed-{i}" for i in range(5)]

        # First run: takes real time
        t0 = time.time()
        s1 = executor.run_checks(str(tmp_path), names)
        first_duration = time.time() - t0
        assert s1.passed == 5

        # Second run: should be near-instant
        t0 = time.time()
        s2 = executor.run_checks(str(tmp_path), names)
        second_duration = time.time() - t0
        assert s2.passed == 5

        # Second run should be at least 5x faster (it's instant vs ~0.5s)
        assert second_duration < first_duration / 5

    def test_cache_invalidated_on_file_change(self, tmp_path):
        """Cache is invalidated when source files change."""
        src = tmp_path / "main.py"
        src.write_text("print('v1')")

        check_cls = _make_slow_check_class("invalidation-test")
        registry = CheckRegistry()
        registry.register(check_cls)
        executor = CheckExecutor(registry=registry, fail_fast=False)

        # First run
        executor.run_checks(str(tmp_path), ["overconfidence:invalidation-test"])
        assert check_cls.run_count == 1

        # Change the source file
        time.sleep(0.05)
        src.write_text("print('v2')")
        os.utime(src, (time.time() + 1, time.time() + 1))

        # Second run: cache should miss, check re-runs
        executor.run_checks(str(tmp_path), ["overconfidence:invalidation-test"])
        assert check_cls.run_count == 2

    def test_failed_results_cached(self, tmp_path):
        """Failed results are cached too (user explicitly requested this)."""
        (tmp_path / "main.py").write_text("x = 1")

        check_cls = _make_slow_check_class("fail-cache", CheckStatus.FAILED)
        registry = CheckRegistry()
        registry.register(check_cls)
        executor = CheckExecutor(registry=registry, fail_fast=False)

        # First run
        s1 = executor.run_checks(str(tmp_path), ["overconfidence:fail-cache"])
        assert s1.failed == 1
        assert check_cls.run_count == 1

        # Second run: uses cached failure
        s2 = executor.run_checks(str(tmp_path), ["overconfidence:fail-cache"])
        assert s2.failed == 1
        assert check_cls.run_count == 1  # Not re-run

    def test_cache_persists_across_executor_instances(self, tmp_path):
        """Cache works across different executor instances (file-based)."""
        (tmp_path / "main.py").write_text("x = 1")

        check_cls = _make_slow_check_class("persist-test")
        registry = CheckRegistry()
        registry.register(check_cls)

        # First executor instance: populates cache
        e1 = CheckExecutor(registry=registry, fail_fast=False)
        e1.run_checks(str(tmp_path), ["overconfidence:persist-test"])
        assert check_cls.run_count == 1

        # Second executor instance: reads cache from disk
        e2 = CheckExecutor(registry=registry, fail_fast=False)
        s2 = e2.run_checks(str(tmp_path), ["overconfidence:persist-test"])
        assert s2.passed == 1
        assert check_cls.run_count == 1  # Still 1 — served from disk cache


class TestNoCacheFlag:
    """Tests for use_cache=False (--no-cache CLI flag)."""

    def test_no_cache_forces_rerun(self, tmp_path):
        """use_cache=False forces checks to run even with unchanged sources."""
        (tmp_path / "main.py").write_text("print('hello')")

        check_cls = _make_slow_check_class("no-cache-rerun")
        registry = CheckRegistry()
        registry.register(check_cls)
        executor = CheckExecutor(registry=registry, fail_fast=False)

        # First run: populates cache
        s1 = executor.run_checks(str(tmp_path), ["overconfidence:no-cache-rerun"])
        assert s1.passed == 1
        assert check_cls.run_count == 1

        # Second run WITH cache: hits cache, no re-run
        s2 = executor.run_checks(str(tmp_path), ["overconfidence:no-cache-rerun"])
        assert s2.passed == 1
        assert check_cls.run_count == 1

        # Third run WITHOUT cache: must re-run
        s3 = executor.run_checks(
            str(tmp_path),
            ["overconfidence:no-cache-rerun"],
            use_cache=False,
        )
        assert s3.passed == 1
        assert check_cls.run_count == 2  # Ran again

    def test_no_cache_skips_disk_write(self, tmp_path):
        """use_cache=False doesn't write cache.json to disk."""
        (tmp_path / "main.py").write_text("x = 1")

        check_cls = _make_slow_check_class("no-write")
        registry = CheckRegistry()
        registry.register(check_cls)
        executor = CheckExecutor(registry=registry, fail_fast=False)

        cache_file = tmp_path / ".slopmop" / "cache.json"
        assert not cache_file.exists()

        # Run with cache disabled
        executor.run_checks(str(tmp_path), ["overconfidence:no-write"], use_cache=False)
        assert check_cls.run_count == 1
        # Cache file should NOT have been created
        assert not cache_file.exists()

    def test_no_cache_results_not_marked_cached(self, tmp_path):
        """Results from a no-cache run are never marked as cached."""
        (tmp_path / "main.py").write_text("x = 1")

        check_cls = _make_slow_check_class("no-cached-flag")
        registry = CheckRegistry()
        registry.register(check_cls)
        executor = CheckExecutor(registry=registry, fail_fast=False)

        # First run WITH cache to populate
        executor.run_checks(str(tmp_path), ["overconfidence:no-cached-flag"])

        # Second run WITHOUT cache: results should not be cached
        s2 = executor.run_checks(
            str(tmp_path),
            ["overconfidence:no-cached-flag"],
            use_cache=False,
        )
        cached_results = [r for r in s2.results if r.cached]
        assert len(cached_results) == 0

    def test_no_cache_does_not_pollute_future_cached_runs(self, tmp_path):
        """A no-cache run doesn't affect subsequent cached runs."""
        (tmp_path / "main.py").write_text("x = 1")

        check_cls = _make_slow_check_class("no-pollute")
        registry = CheckRegistry()
        registry.register(check_cls)
        executor = CheckExecutor(registry=registry, fail_fast=False)

        # First run: populates cache
        executor.run_checks(str(tmp_path), ["overconfidence:no-pollute"])
        assert check_cls.run_count == 1

        # No-cache run: forces re-run but doesn't write
        executor.run_checks(
            str(tmp_path), ["overconfidence:no-pollute"], use_cache=False
        )
        assert check_cls.run_count == 2

        # Cached run: should still hit original cache (not polluted)
        s3 = executor.run_checks(str(tmp_path), ["overconfidence:no-pollute"])
        assert s3.passed == 1
        assert check_cls.run_count == 2  # Served from original cache
