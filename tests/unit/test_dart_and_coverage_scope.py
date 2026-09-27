"""Cache fingerprinting, Dart suite reuse, and coverage scoping.

Barnacles from a Flutter repo (#362, #363, #364) plus the scope and
interpreter bugs found while fixing them. Some are about work being
repeated; the rest are about work being skipped while a pass is reported.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Tuple

import pytest

from slopmop.checks.base import SOURCE_EXTENSIONS
from slopmop.checks.dart.common import DART_CACHE_EXTENSIONS
from slopmop.checks.python.tests import (
    PythonTestsCheck,
    _project_declares_coverage_source,
)
from slopmop.core.cache import _SOURCE_EXTENSIONS, compute_fingerprint


def _make_git_repo(root: Path) -> None:
    """Named for what it makes, not the tool it uses.

    A bare `_init_repo` collides with the one in
    test_refit_drain_functional.py — different signature, different
    behaviour, same name. That is the ambiguity the myopia gate catches,
    and this is the second one this week.
    """
    for args in (
        ("init", "-q", "."),
        ("config", "user.email", "t@t.t"),
        ("config", "user.name", "t"),
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def dart_repo(tmp_path: Path) -> Path:
    (tmp_path / "lib").mkdir()
    (tmp_path / "pubspec.yaml").write_text("name: demo\n")
    (tmp_path / "lib" / "main.dart").write_text("void main() {}\n")
    (tmp_path / "README.md").write_text("# demo\n")
    (tmp_path / "tool.py").write_text("x = 1\n")
    _make_git_repo(tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", "init"], cwd=tmp_path, check=True, capture_output=True
    )
    return tmp_path


class TestFingerprintCoversEveryLanguage:
    """#364 — the cache kept its own extension list, and it drifted.

    ``.dart`` was never added, so a Dart-only edit left the fingerprint
    unchanged and every Dart gate replayed its last cached PASS: a formatter
    rejecting a file while slop-mop called it clean.
    """

    def test_dart_is_fingerprinted(self) -> None:
        assert ".dart" in _SOURCE_EXTENSIONS

    def test_every_supported_language_is_fingerprinted(self) -> None:
        """The guard that stops this drifting again.

        A language slop-mop can measure but cannot notice changing is a
        cached false pass waiting to happen.
        """
        missing = SOURCE_EXTENSIONS - _SOURCE_EXTENSIONS
        assert not missing, f"languages invisible to the cache: {sorted(missing)}"

    def test_docs_and_config_still_counted(self) -> None:
        """Some gates read docs and config; dropping them would cache stale."""
        for ext in (".md", ".json", ".cfg", ".ini"):
            assert ext in _SOURCE_EXTENSIONS, ext

    def test_a_dart_edit_changes_the_fingerprint(self, dart_repo: Path) -> None:
        before = compute_fingerprint(str(dart_repo))
        (dart_repo / "lib" / "main.dart").write_text("void main() { print(1); }\n")
        assert compute_fingerprint(str(dart_repo)) != before


class TestDartGatesAreScopedToDartInputs:
    """#364's other half — a .md edit reran a one-to-three-minute suite."""

    @staticmethod
    def _dart_checks():
        from slopmop.checks.dart.analyze import FlutterAnalyzeCheck
        from slopmop.checks.dart.bogus_tests import DartBogusTestsCheck
        from slopmop.checks.dart.coverage import DartCoverageCheck
        from slopmop.checks.dart.format import DartFormatCheck
        from slopmop.checks.dart.generated_artifacts import (
            DartGeneratedArtifactsCheck,
        )
        from slopmop.checks.dart.tests import FlutterTestsCheck

        return [
            FlutterTestsCheck({}),
            DartCoverageCheck({}),
            FlutterAnalyzeCheck({}),
            DartFormatCheck({}),
            DartBogusTestsCheck({}),
            DartGeneratedArtifactsCheck({}),
        ]

    def test_every_dart_gate_scopes_its_cache(self, dart_repo: Path) -> None:
        for check in self._dart_checks():
            assert check.cache_inputs(str(dart_repo)) is not None, check.name

    def test_dart_edit_invalidates(self, dart_repo: Path) -> None:
        for check in self._dart_checks():
            before = check.cache_inputs(str(dart_repo))
            (dart_repo / "lib" / "main.dart").write_text(
                f"void main() {{ print('{check.name}'); }}\n"
            )
            assert check.cache_inputs(str(dart_repo)) != before, check.name

    def test_unrelated_edit_does_not_invalidate(self, dart_repo: Path) -> None:
        """The saving: a docs or Python edit must not rerun a Flutter suite."""
        for check in self._dart_checks():
            before = check.cache_inputs(str(dart_repo))
            (dart_repo / "README.md").write_text(f"# {check.name}\n")
            (dart_repo / "tool.py").write_text(f"x = '{check.name}'\n")
            assert check.cache_inputs(str(dart_repo)) == before, check.name

    def test_pubspec_and_lockfile_count(self, dart_repo: Path) -> None:
        """They decide what a build resolves to, so they change the verdict."""
        assert ".yaml" in DART_CACHE_EXTENSIONS
        assert ".lock" in DART_CACHE_EXTENSIONS

        check = self._dart_checks()[0]
        before = check.cache_inputs(str(dart_repo))
        (dart_repo / "pubspec.yaml").write_text("name: demo\nversion: 2.0.0\n")
        assert check.cache_inputs(str(dart_repo)) != before


class TestDartSuiteRunsOnce:
    """#363 — two gates each ran the full Flutter suite, the two slowest."""

    def test_tests_gate_produces_coverage(self) -> None:
        """One run has to serve both, so it must be the --coverage one."""
        source = Path("slopmop/checks/dart/tests.py").read_text(encoding="utf-8")
        assert '[flutter_path, "test", "--coverage"]' in source

    def test_coverage_gate_depends_on_the_tests_gate(self) -> None:
        from slopmop.checks.dart.coverage import DartCoverageCheck

        assert DartCoverageCheck({}).depends_on == ["overconfidence:untested-code.dart"]

    def test_fresh_lcov_is_reused(self, tmp_path: Path) -> None:
        from slopmop.checks.dart.coverage import _wait_for_lcov

        lcov = tmp_path / "coverage" / "lcov.info"
        lcov.parent.mkdir(parents=True)
        lcov.write_text("TN:\nSF:lib/main.dart\nend_of_record\n")
        assert _wait_for_lcov(lcov, newer_than=time.time() - 60) is True

    def test_stale_lcov_is_not_reused(self, tmp_path: Path) -> None:
        """A report from an earlier run describes code that has since changed.

        Reading it would report coverage for tests nobody just ran — the same
        believed-green failure these barnacles are about.
        """
        from slopmop.checks.dart.coverage import _wait_for_lcov

        lcov = tmp_path / "coverage" / "lcov.info"
        lcov.parent.mkdir(parents=True)
        lcov.write_text("TN:\n")
        assert _wait_for_lcov(lcov, newer_than=time.time() + 60) is False

    def test_missing_lcov_is_not_reused(self, tmp_path: Path) -> None:
        from slopmop.checks.dart.coverage import _wait_for_lcov

        assert (
            _wait_for_lcov(tmp_path / "nope" / "lcov.info", newer_than=time.time() + 60)
            is False
        )


class TestCoverageIsScopeable:
    """#362 — `--cov=.` measured the whole repo and beat every scoping key.

    A command-line ``--cov`` overrides the config file, so a repo could set
    ``.coveragerc`` source and see no effect at all.
    """

    def test_include_dirs_scopes_the_measurement(self) -> None:
        check = PythonTestsCheck({"include_dirs": ["paperbot"]})
        assert check._coverage_args(".") == ["--cov=paperbot"]

    def test_several_packages(self) -> None:
        check = PythonTestsCheck({"include_dirs": ["a", "b"]})
        assert check._coverage_args(".") == ["--cov=a", "--cov=b"]

    def test_a_declared_coverage_source_is_not_overridden(self, tmp_path: Path) -> None:
        (tmp_path / ".coveragerc").write_text("[run]\nsource = paperbot\n")
        args = PythonTestsCheck({})._coverage_args(str(tmp_path))
        assert args == ["--cov"], "a bare --cov lets coverage read its own config"

    def test_pyproject_coverage_source_is_detected(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[tool.coverage.run]\nsource = ["pkg"]\n'
        )
        assert _project_declares_coverage_source(str(tmp_path)) is True

    def test_setup_cfg_coverage_source_is_detected(self, tmp_path: Path) -> None:
        (tmp_path / "setup.cfg").write_text("[coverage:run]\nsource = pkg\n")
        assert _project_declares_coverage_source(str(tmp_path)) is True

    def test_unscoped_project_still_measures_everything(self, tmp_path: Path) -> None:
        """The default must not change for a repo that asked for nothing."""
        assert PythonTestsCheck({})._coverage_args(str(tmp_path)) == ["--cov=."]

    def test_gate_config_beats_a_declared_source(self, tmp_path: Path) -> None:
        """The most specific thing anyone said wins."""
        (tmp_path / ".coveragerc").write_text("[run]\nsource = other\n")
        check = PythonTestsCheck({"include_dirs": ["paperbot"]})
        assert check._coverage_args(str(tmp_path)) == ["--cov=paperbot"]

    def test_include_dirs_is_declared_in_the_schema(self) -> None:
        names = {f.name for f in PythonTestsCheck({}).config_schema}
        assert "include_dirs" in names

    def test_malformed_config_does_not_raise(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("this is not valid toml {{{")
        assert _project_declares_coverage_source(str(tmp_path)) is False

    def test_category_level_include_dirs_reaches_the_gate(self) -> None:
        """Set once for the category, as the reporting repo had it."""
        from slopmop.core.registry import get_registry

        config = {
            "overconfidence": {
                "enabled": True,
                "include_dirs": ["paperbot"],
                "gates": {"untested-code.py": {"enabled": True}},
            }
        }
        gate_cfg = get_registry()._extract_gate_config(
            "overconfidence:untested-code.py", config
        )
        assert gate_cfg.get("include_dirs") == ["paperbot"]


class TestRootInIncludeDirsMeansEverything:
    """Adding a directory to include_dirs must never shrink the scope to nothing.

    ``include_dirs: [".", "src"]`` — the value ``sm init`` writes — matched
    zero files. "." was special-cased only as the exact list ``["."]``; in any
    longer list it was compared as a literal path prefix, and no repo-relative
    path starts with "./". The gate then passed in hundredths of a second
    having looked at nothing.

    Found because it had been silently disabling this repo's own
    ambiguity-mines gate locally while CI, reading a different config, kept
    catching what it missed.
    """

    @pytest.fixture
    def tree(self, tmp_path: Path) -> Path:
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "mod.py").write_text("x = 1\n")
        (tmp_path / "other").mkdir()
        (tmp_path / "other" / "thing.py").write_text("y = 2\n")
        (tmp_path / "root.py").write_text("z = 3\n")
        return tmp_path

    @staticmethod
    def _both(root: Path, include_dirs):
        from slopmop.checks.base import iter_project_files, resolve_tool_paths

        return (
            len(
                iter_project_files(
                    str(root), extensions={".py"}, include_dirs=include_dirs
                )
            ),
            len(
                resolve_tool_paths(
                    str(root), extensions={".py"}, include_dirs=include_dirs
                )
            ),
        )

    def test_root_plus_another_dir_scans_everything(self, tree: Path) -> None:
        """The exact reported shape."""
        assert self._both(tree, [".", "src"]) == (3, 3)

    def test_bare_root_scans_everything(self, tree: Path) -> None:
        assert self._both(tree, ["."]) == (3, 3)

    def test_unset_scans_everything(self, tree: Path) -> None:
        assert self._both(tree, None) == (3, 3)

    def test_a_real_subdir_still_narrows(self, tree: Path) -> None:
        """The fix must not turn every scope into no scope."""
        assert self._both(tree, ["pkg"]) == (1, 1)

    def test_several_subdirs_accumulate(self, tree: Path) -> None:
        assert self._both(tree, ["pkg", "other"]) == (2, 2)

    def test_a_nonexistent_dir_still_scans_nothing(self, tree: Path) -> None:
        """Naming only a directory that isn't there is a real empty scope."""
        assert self._both(tree, ["src"]) == (0, 0)

    def test_dot_slash_spellings_agree(self, tree: Path) -> None:
        assert self._both(tree, ["./pkg"]) == self._both(tree, ["pkg"])

    def test_the_two_resolvers_never_disagree(self, tree: Path) -> None:
        """They are separately implemented; a divergence is a silent scope bug."""
        for include_dirs in (
            None,
            ["."],
            [".", "src"],
            ["pkg"],
            ["pkg", "other"],
            ["src"],
        ):
            a, b = self._both(tree, include_dirs)
            assert a == b, f"{include_dirs}: iter={a} resolve={b}"


class TestCoverageReuseSurvivesOrdering:
    """The reuse in #363 saved nothing, because of how it decided freshness.

    `depends_on` orders the suite before the coverage gate, so the report is
    always written *before* that gate starts. Comparing the report's mtime
    against the coverage gate's own start therefore rejected every report it
    existed to reuse: it waited out the poll and ran the whole suite again.
    Measured saving: zero.

    The baseline has to be when the run began, not when the reader began.
    """

    @pytest.fixture
    def report(self, tmp_path: Path) -> Path:
        lcov = tmp_path / "coverage" / "lcov.info"
        lcov.parent.mkdir(parents=True)
        lcov.write_text("TN:\nSF:lib/main.dart\nend_of_record\n")
        return lcov

    def test_a_report_written_before_this_gate_started_is_reused(
        self, report: Path
    ) -> None:
        """The real ordering. This is the case that regressed."""
        from slopmop.checks.dart.coverage import _wait_for_lcov
        from slopmop.core.run_context import RUN_STARTED_AT

        time.sleep(0.02)
        gate_start = time.time()
        assert gate_start > report.stat().st_mtime, "fixture must predate the gate"

        assert _wait_for_lcov(report, newer_than=RUN_STARTED_AT) is True

    def test_a_report_from_an_earlier_run_is_still_rejected(self, report: Path) -> None:
        """Staleness protection must survive the fix.

        A report from a previous run describes code that has since changed.
        """
        import os

        from slopmop.checks.dart.coverage import _wait_for_lcov
        from slopmop.core.run_context import RUN_STARTED_AT

        stale = RUN_STARTED_AT - 3600
        os.utime(report, (stale, stale))
        assert _wait_for_lcov(report, newer_than=RUN_STARTED_AT) is False

    def test_the_run_baseline_precedes_any_gate(self) -> None:
        """Whatever a gate later compares, the run started before it."""
        from slopmop.core.run_context import RUN_STARTED_AT

        assert RUN_STARTED_AT <= time.time()


class TestOneSearchForTheProjectPython:
    """#367's other half: two implementations of the same search, one fixed.

    The worktree fallback went into `resolve_project_python`, but the test
    gate calls `get_project_python`, which carried its own copy. So
    `has_project_venv` began reporting a borrowable venv while pytest was
    still handed slop-mop's own interpreter — the gate stopped skipping and
    started failing against the wrong Python, which is a worse outcome than
    the bug being fixed.
    """

    @pytest.fixture
    def worktree(self, tmp_path: Path) -> Tuple[Path, Path]:
        main = tmp_path / "main"
        main.mkdir()

        def git(*args: str) -> None:
            subprocess.run(["git", *args], cwd=main, check=True, capture_output=True)

        git("init", "-q", ".")
        git("config", "user.email", "t@t.t")
        git("config", "user.name", "t")
        (main / ".gitignore").write_text("venv/\n")
        (main / "mod.py").write_text("x = 1\n")
        git("add", "-A")
        git("commit", "-qm", "init")

        venv_bin = main / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        python = venv_bin / "python"
        python.write_text("#!/bin/sh\necho py\n")
        python.chmod(0o755)

        wt = tmp_path / "wt"
        git("worktree", "add", "-q", str(wt), "-b", "feat/x")
        return main, wt

    @staticmethod
    def _fresh_check():
        from slopmop.checks.mixins import PythonCheckMixin
        from slopmop.checks.python.tests import PythonTestsCheck

        PythonCheckMixin._python_cache.clear()
        PythonCheckMixin._venv_warning_shown.clear()
        return PythonTestsCheck({})

    def test_the_gate_runs_the_projects_python_from_a_worktree(
        self, worktree: Tuple[Path, Path]
    ) -> None:
        main, wt = worktree
        assert self._fresh_check().get_project_python(str(wt)) == str(
            main / "venv" / "bin" / "python"
        )

    def test_both_searches_agree(self, worktree: Tuple[Path, Path]) -> None:
        """A divergence here is invisible until a gate runs the wrong Python."""
        from slopmop.checks.mixins import resolve_project_python

        _, wt = worktree
        assert self._fresh_check().get_project_python(str(wt)) == (
            resolve_project_python(str(wt))[0]
        )

    def test_they_agree_in_the_main_checkout_too(
        self, worktree: Tuple[Path, Path]
    ) -> None:
        from slopmop.checks.mixins import resolve_project_python

        main, _ = worktree
        assert self._fresh_check().get_project_python(str(main)) == (
            resolve_project_python(str(main))[0]
        )

    def test_a_venvless_project_still_falls_back(self, tmp_path: Path) -> None:
        """Delegation must not invent a venv where there is none."""
        import sys

        from slopmop.checks.mixins import resolve_project_python

        chosen = self._fresh_check().get_project_python(str(tmp_path))
        assert chosen == resolve_project_python(str(tmp_path))[0]
        assert chosen == sys.executable

    def test_the_result_is_cached_per_project(
        self, worktree: Tuple[Path, Path]
    ) -> None:
        from slopmop.checks.mixins import PythonCheckMixin

        _, wt = worktree
        check = self._fresh_check()
        first = check.get_project_python(str(wt))
        assert PythonCheckMixin._python_cache[str(wt)] == first
        assert check.get_project_python(str(wt)) == first
