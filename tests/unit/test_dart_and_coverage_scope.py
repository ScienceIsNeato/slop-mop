"""Cache fingerprinting, Dart suite reuse, and coverage scoping.

Three barnacles from a Flutter repo (#362, #363, #364). Two are about work
being repeated; one is about work being skipped while a pass is reported.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from slopmop.checks.base import SOURCE_EXTENSIONS
from slopmop.checks.dart.common import DART_CACHE_EXTENSIONS
from slopmop.checks.python.tests import (
    PythonTestsCheck,
    _project_declares_coverage_source,
)
from slopmop.core.cache import _SOURCE_EXTENSIONS, compute_fingerprint


def _init_repo(root: Path) -> None:
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
    _init_repo(tmp_path)
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
