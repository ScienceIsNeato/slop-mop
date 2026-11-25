"""A tool slop-mop execs must not be one of its library dependencies.

semgrep was declared in the ``[security]`` extra, so installing slop-mop
installed semgrep's entire transitive tree beside it. slop-mop never imports
semgrep — it runs the binary — but pip-audit correctly reported those
transitive packages as slop-mop's supply chain.

Three of them (mcp, opentelemetry-api, wcmatch) were pinned by semgrep tightly
enough that no floor-pin could reach a patched version, so the only lever left
was an ignore list that had to be re-earned every time one got a new advisory.
It was, three times, and the scanning gate sat red for six weeks.

These tests pin the rule that prevents it recurring.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Dict, List

import pytest

from slopmop.checks.base import Requirement
from slopmop.checks.security import SecurityLocalCheck

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Packages slop-mop runs as subprocesses and never imports. Verified by the
# import test below rather than asserted here.
EXEC_ONLY = ("semgrep", "bandit", "detect-secrets", "pip-audit")


def _pyproject() -> Dict[str, Any]:
    return tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _extra(name: str) -> List[str]:
    return _pyproject()["project"]["optional-dependencies"].get(name, [])


class TestSemgrepIsNotALibraryDependency:
    def test_semgrep_is_absent_from_every_extra(self) -> None:
        """The actual regression guard: it must not come back as a pip dep."""
        extras = _pyproject()["project"]["optional-dependencies"]
        offenders = {
            name: [d for d in deps if d.lower().startswith("semgrep")]
            for name, deps in extras.items()
        }
        offenders = {k: v for k, v in offenders.items() if v}
        assert not offenders, f"semgrep is a library dependency again: {offenders}"

    def test_semgrep_is_absent_from_core_dependencies(self) -> None:
        deps = _pyproject()["project"].get("dependencies", [])
        assert not [d for d in deps if d.lower().startswith("semgrep")]

    def test_semgrep_is_still_a_declared_requirement(self) -> None:
        """Unbundling must not quietly stop requiring it — that is a silent skip."""
        reqs = SecurityLocalCheck({})._SCANNER_REQUIREMENTS
        assert "semgrep" in reqs

    def test_semgrep_is_marked_isolated(self) -> None:
        req = SecurityLocalCheck({})._SCANNER_REQUIREMENTS["semgrep"]
        assert req.isolated is True

    def test_its_install_hint_can_actually_install_it(self) -> None:
        """The old hint pointed at an extra that no longer contains semgrep."""
        req = SecurityLocalCheck({})._SCANNER_REQUIREMENTS["semgrep"]
        assert "slopmop[" not in req.install_hint, req.install_hint
        assert "semgrep" in req.install_hint


class TestExecOnlyToolsAreNeverImported:
    """The premise behind unbundling, asserted rather than assumed."""

    @pytest.mark.parametrize("tool", EXEC_ONLY)
    def test_no_module_imports_the_tool(self, tool: str) -> None:
        module = tool.replace("-", "_")
        hits: List[str] = []
        for path in (PROJECT_ROOT / "slopmop").rglob("*.py"):
            for num, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                stripped = line.strip()
                if stripped.startswith(f"import {module}") or stripped.startswith(
                    f"from {module}"
                ):
                    hits.append(f"{path.relative_to(PROJECT_ROOT)}:{num}")
        assert not hits, f"{tool} is imported, so it IS a library dependency: {hits}"


class TestManifestStaysBackwardCompatible:
    """An older Action must keep working, not skip the tool in silence."""

    def test_schema_version_is_unchanged(self) -> None:
        """Bumping it would hard-fail every consumer still on an older Action."""
        from slopmop.checks.base import REQUIREMENTS_MANIFEST_SCHEMA_VERSION

        assert REQUIREMENTS_MANIFEST_SCHEMA_VERSION == 1

    def test_isolated_tools_keep_a_kind_old_installers_understand(self) -> None:
        """The installer selects on `kind`; an unknown one is silently skipped.

        Keeping kind="python" means an Action that ignores `isolated` installs
        semgrep the way it always did — today's behaviour, not a new failure.
        """
        req = SecurityLocalCheck({})._SCANNER_REQUIREMENTS["semgrep"]
        assert req.kind == "python"

    def test_isolated_is_omitted_when_false(self) -> None:
        """Keeps the manifest byte-stable for every unaffected entry."""
        plain = Requirement(kind="python", name="bandit")
        assert "isolated" not in plain.to_manifest()

    def test_isolated_is_emitted_when_true(self) -> None:
        marked = Requirement(kind="python", name="semgrep", isolated=True)
        assert marked.to_manifest()["isolated"] is True

    def test_the_committed_manifest_marks_semgrep_isolated(self) -> None:
        """The Action installs from this file, so it has to carry the flag."""
        import json

        manifest = json.loads(
            (PROJECT_ROOT / ".slopmop" / "required-deps.json").read_text(
                encoding="utf-8"
            )
        )
        entry = next(r for r in manifest["requirements"] if r["name"] == "semgrep")
        assert entry.get("isolated") is True
        assert entry["kind"] == "python"


class TestTheIgnoreListShrank:
    """The mcp entries existed only because semgrep brought mcp along."""

    def test_mcp_advisories_are_no_longer_excused(self) -> None:
        gates = _pyproject()["tool"]["slopmop"]["myopia"]["gates"]
        ignored = gates["dependency-risk.py"].get("pip_audit_ignore_vulns", [])
        assert not [
            v for v in ignored if v.startswith("PYSEC-2026-348")
        ], "mcp ignores should be gone with the dependency that needed them"

    def test_black_is_pinned_to_a_patched_release(self) -> None:
        """26.5.1 carried CVE-2026-114134; this one is a real fix, not scoping."""
        black = [d for d in _extra("lint") if d.startswith("black")]
        assert black == ["black==26.10.1"], black


class TestGitIsRunWithoutInheritedRepositoryContext:
    """Git hooks export GIT_DIR; slop-mop's pre-commit hook runs this suite.

    A test that builds its own repository in a tmp directory then had its git
    commands redirected at slop-mop's own checkout. Eight worktree tests
    passed under `pytest` and errored under `git commit` with exit 128, and
    the gate reported "0 test(s) failed" because pytest errored in setup
    rather than failing an assertion.

    Same shape as the run-level marker that used to live in an environment
    variable: anything inherited by a spawned test suite becomes part of its
    behaviour.
    """

    def test_every_git_pointer_is_stripped(self) -> None:
        import os
        from unittest.mock import patch

        from tests.git_helpers import clean_git_env

        leaked = {
            "GIT_DIR": "/elsewhere/.git",
            "GIT_WORK_TREE": "/elsewhere",
            "GIT_INDEX_FILE": "/elsewhere/.git/index",
            "GIT_OBJECT_DIRECTORY": "/elsewhere/.git/objects",
            "PATH": os.environ.get("PATH", ""),
        }
        with patch.dict(os.environ, leaked, clear=True):
            env = clean_git_env()

        assert not [k for k in env if k.startswith("GIT_")], sorted(env)
        assert "PATH" in env, "scrubbing must not strip the rest of the environment"

    def test_a_repo_built_under_a_leaked_git_dir_is_its_own(
        self, tmp_path: Path
    ) -> None:
        """The end-to-end property: the test's repo answers, not the caller's."""
        import os
        from unittest.mock import patch

        from tests.git_helpers import init_repo, run_git

        with patch.dict(os.environ, {"GIT_DIR": str(PROJECT_ROOT / ".git")}):
            init_repo(tmp_path)
            out = run_git("rev-parse", "--show-toplevel", cwd=tmp_path)

        resolved = Path(out.stdout.decode().strip()).resolve()
        assert resolved == tmp_path.resolve(), (
            f"git answered for {resolved}, not the test's own repo"
        )

    def test_worktrees_can_be_created_under_a_leaked_git_dir(
        self, tmp_path: Path
    ) -> None:
        """The exact failure: `git worktree add -b` exited 128."""
        import os
        from unittest.mock import patch

        from tests.git_helpers import add_worktree, commit_all, init_repo

        main = tmp_path / "main"
        main.mkdir()
        with patch.dict(os.environ, {"GIT_DIR": str(PROJECT_ROOT / ".git")}):
            init_repo(main)
            (main / "f.txt").write_text("x\n")
            commit_all(main)
            add_worktree(main, tmp_path / "wt", "feat/x")

        assert (tmp_path / "wt").is_dir()
