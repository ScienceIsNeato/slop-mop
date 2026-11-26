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

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

# tomllib is stdlib from 3.11; this project supports 3.10, where an
# unconditional import stops pytest collecting this file entirely. Same
# shim the CLI uses.
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]

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
        assert (
            resolved == tmp_path.resolve()
        ), f"git answered for {resolved}, not the test's own repo"

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


class TestManifestPinsAgreeWithPyproject:
    """Two copies of a version is two chances to ship the wrong one.

    A gate's ``requirements()`` carries the version the Action installs, and
    ``pyproject.toml`` carries the version a pip install resolves. They are
    separate strings describing the same decision. Bumping black for
    CVE-2026-114134 in pyproject alone left the manifest — and therefore every
    CI run — still installing 26.5.1.

    Only exact pins are compared. pyproject deliberately uses floors for tools
    where any recent version will do; this is about the ones that claim to be
    one specific release.
    """

    @staticmethod
    def _exact_pyproject_pins() -> Dict[str, str]:
        pins: Dict[str, str] = {}
        extras = _pyproject()["project"]["optional-dependencies"]
        for deps in extras.values():
            for dep in deps:
                if "==" not in dep or dep.startswith("slopmop["):
                    continue
                name, _, version = dep.partition("==")
                pins[name.strip().lower()] = version.strip()
        return pins

    @staticmethod
    def _exact_manifest_pins() -> Dict[str, str]:
        import json

        manifest = json.loads(
            (PROJECT_ROOT / ".slopmop" / "required-deps.json").read_text(
                encoding="utf-8"
            )
        )
        return {
            r["name"].lower(): r["version"]
            for r in manifest["requirements"]
            if r.get("version")
        }

    def test_no_tool_is_pinned_to_two_different_versions(self) -> None:
        pyproject = self._exact_pyproject_pins()
        manifest = self._exact_manifest_pins()
        shared = set(pyproject) & set(manifest)
        assert shared, "expected at least one tool pinned exactly in both places"

        drift = {
            name: {"pyproject": pyproject[name], "manifest": manifest[name]}
            for name in sorted(shared)
            if pyproject[name] != manifest[name]
        }
        assert not drift, f"a pin was bumped in one place only: {drift}"

    def test_black_is_patched_in_both(self) -> None:
        """The specific instance that would have shipped the CVE to CI."""
        assert self._exact_pyproject_pins()["black"] == "26.10.1"
        assert self._exact_manifest_pins()["black"] == "26.10.1"


class TestAMissingScannerIsNotAFinding:
    """A scanner that never ran has found nothing, by definition.

    The dispatch folded every exception into a failed sub-result, so a
    semgrep that was not installed came back as "semgrep found issues" — the
    gate reporting a security finding from a scanner that had not executed.

    Latent until now: semgrep was always present because it was a library
    dependency. Unbundling makes it reachable, since a machine can satisfy
    the availability probe and still fail the exec.
    """

    def test_a_missing_binary_degrades_instead_of_failing(self) -> None:
        from slopmop.checks.security import _subresult_for_scanner_exception

        sub = _subresult_for_scanner_exception(
            "semgrep", FileNotFoundError(2, "No such file or directory: 'semgrep'")
        )
        assert sub.passed is True, "a scanner that did not run must not fail the gate"
        assert sub.warned is True
        assert sub.did_not_run is True
        assert "found issues" not in sub.findings

    def test_a_real_error_still_fails(self) -> None:
        """Degrading must not swallow genuine scanner breakage."""
        from slopmop.checks.security import _subresult_for_scanner_exception

        sub = _subresult_for_scanner_exception("semgrep", ValueError("bad rule pack"))
        assert sub.passed is False
        assert "bad rule pack" in sub.findings

    def test_the_remediation_can_install_the_missing_tool(self) -> None:
        """The shared hint would send a semgrep user to an extra without it."""
        from slopmop.checks.security import _subresult_for_scanner_exception

        sub = _subresult_for_scanner_exception("semgrep", FileNotFoundError("nope"))
        assert "pipx install semgrep" in sub.findings
        assert "slopmop[security]" not in sub.findings

    def test_bundled_scanners_keep_the_extras_hint(self) -> None:
        from slopmop.checks.security import _subresult_for_scanner_exception

        sub = _subresult_for_scanner_exception("bandit", FileNotFoundError("nope"))
        assert "slopmop[security]" in sub.findings


class TestCiInstallsSemgrepInIsolation:
    """Unbundling is only real if nobody puts it back in the same venv."""

    @staticmethod
    def _workflow() -> str:
        return (PROJECT_ROOT / ".github" / "workflows" / "slopmop-sarif.yml").read_text(
            encoding="utf-8"
        )

    def test_ci_installs_semgrep_somewhere(self) -> None:
        """It left [all], so CI has to ask for it explicitly or lose the gate."""
        assert "install semgrep" in self._workflow()

    def test_ci_never_pip_installs_it_into_the_audited_venv(self) -> None:
        """`pip install semgrep` there would restore the tree pip-audit reads."""
        offenders = [
            line.strip()
            for line in self._workflow().splitlines()
            if "semgrep" in line
            and "pip install" in line
            and "pipx" not in line
            and not line.strip().startswith("#")
        ]
        assert not offenders, offenders

    def test_every_install_site_gets_it(self) -> None:
        """Three jobs build a venv; a gate that silently skips in one is worse
        than one that fails in all three."""
        text = self._workflow()
        assert text.count('pip install -e ".[all]"') == text.count(
            "pipx install semgrep"
        )


class TestGitProbesIgnoreInheritedPointers:
    """slop-mop runs from a hook, then runs git against another project.

    `git -C <root>` is not enough on its own: a leaked GIT_DIR wins over it.
    `_main_worktree_root` asked an unrelated repository for its common dir and
    got slop-mop's own checkout back, which would let worktree detection
    borrow a different project's virtualenv and report success.

    One scrubber, in production, shared with the test helpers — a second copy
    of this rule is how several of this week's bugs happened.
    """

    def test_the_probe_is_not_fooled_by_a_leaked_git_dir(self, tmp_path: Path) -> None:
        import os
        from unittest.mock import patch

        from slopmop.checks.mixins import _main_worktree_root
        from tests.git_helpers import commit_all, init_repo

        init_repo(tmp_path)
        (tmp_path / "f.txt").write_text("x\n")
        commit_all(tmp_path)

        with patch.dict(os.environ, {"GIT_DIR": str(PROJECT_ROOT / ".git")}):
            answer = _main_worktree_root(tmp_path)

        assert (
            answer is None
        ), f"probe answered for {answer} instead of the repo it was asked about"

    def test_a_real_worktree_still_resolves_under_a_leak(self, tmp_path: Path) -> None:
        """Scrubbing must not break the detection it protects."""
        import os
        from unittest.mock import patch

        from slopmop.checks.mixins import _main_worktree_root
        from tests.git_helpers import add_worktree, commit_all, init_repo

        main = tmp_path / "main"
        main.mkdir()
        init_repo(main)
        (main / "f.txt").write_text("x\n")
        commit_all(main)
        wt = tmp_path / "wt"
        add_worktree(main, wt, "feat/x")

        with patch.dict(os.environ, {"GIT_DIR": str(PROJECT_ROOT / ".git")}):
            answer = _main_worktree_root(wt)

        assert answer is not None
        assert answer.resolve() == main.resolve()

    def test_there_is_one_scrubber(self) -> None:
        """The test helper re-exports production, it does not reimplement it."""
        from slopmop.utils.proc import git_env
        from tests.git_helpers import clean_git_env

        assert not [k for k in git_env() if k.startswith("GIT_")]
        assert not [k for k in clean_git_env() if k.startswith("GIT_")]

    def test_scrubbing_keeps_the_rest_of_the_environment(self) -> None:
        import os

        from slopmop.utils.proc import git_env

        env = git_env()
        assert "PATH" in env and env["PATH"] == os.environ.get("PATH")


class TestCommittedManifestIsCurrent:
    """The committed manifest must match what this repo's code generates.

    The Action's `verify-manifest` asks a different question — whether the
    committed manifest matches what the *released* slopmop generates — which
    no PR that changes `requirements()` can satisfy, because the manifest has
    to lead the release it describes. That check is right for a consumer and
    structurally unsatisfiable for this repo.

    This is the invariant that actually protects us: regenerate from the code
    in the tree and compare. It catches the real failure (someone edits
    requirements and forgets `sm doctor --required-deps`), which is what let
    a stale ruff pin sit in the manifest for weeks.
    """

    def test_regenerating_changes_nothing(self) -> None:
        import json

        from slopmop.checks.base import build_requirements_document
        from slopmop.checks.tool_inventory import aggregate_requirements
        from slopmop.doctor.sm_env import load_repo_config

        config = load_repo_config(str(PROJECT_ROOT))
        regenerated = build_requirements_document(
            aggregate_requirements(config, project_root=str(PROJECT_ROOT))
        )
        committed = json.loads(
            (PROJECT_ROOT / ".slopmop" / "required-deps.json").read_text(
                encoding="utf-8"
            )
        )
        assert committed == regenerated, (
            "committed manifest is stale — run: "
            "sm doctor --required-deps > .slopmop/required-deps.json"
        )


class TestEveryRemediationCanInstallWhatItNames:
    """A hint that cannot install the missing tool is worse than none.

    Review caught two survivors of the first pass. The human-readable string
    was switched to the per-scanner hint and the SARIF message immediately
    below it was not — so the GitHub Code Scanning alert, which is what most
    people actually read, still told semgrep users to run a command that
    installs everything except semgrep. The aggregate remediation had the same
    problem with no scanner named at all.
    """

    def test_text_and_sarif_agree_for_every_scanner(self) -> None:
        """They sit in the same function and drifted anyway."""
        from slopmop.checks.security import _scanner_did_not_run

        for name in ("semgrep", "bandit", "detect-secrets"):
            sub = _scanner_did_not_run(name, "boom")
            text_hint = sub.findings.split("install it with: ")[-1]
            sarif_hint = sub.sarif_findings[0].message.split("install it with: ")[-1]
            assert text_hint == sarif_hint, f"{name}: {text_hint!r} vs {sarif_hint!r}"

    def test_semgrep_is_never_pointed_at_the_extra_it_left(self) -> None:
        from slopmop.checks.security import _scanner_did_not_run

        sub = _scanner_did_not_run("semgrep", "boom")
        for message in (sub.findings, sub.sarif_findings[0].message):
            assert "slopmop[security]" not in message, message
            assert "pipx install semgrep" in message

    def test_the_aggregate_remediation_covers_every_route(self) -> None:
        """It names no scanner, so one shared command cannot be right."""
        from slopmop.checks.security import SecurityLocalCheck, _scanner_did_not_run

        warnings = [
            _scanner_did_not_run("semgrep", "x"),
            _scanner_did_not_run("bandit", "y"),
        ]
        result = SecurityLocalCheck({})._warnings_only_result(warnings, 0.0)
        suggestion = result.fix_suggestion or ""
        assert "pipx install semgrep" in suggestion
        assert "slopmop[security]" in suggestion

    def test_the_aggregate_does_not_repeat_a_shared_route(self) -> None:
        from slopmop.checks.security import SecurityLocalCheck, _scanner_did_not_run

        warnings = [
            _scanner_did_not_run("bandit", "x"),
            _scanner_did_not_run("detect-secrets", "y"),
        ]
        result = SecurityLocalCheck({})._warnings_only_result(warnings, 0.0)
        assert (result.fix_suggestion or "").count("slopmop[security]") == 1

    def test_no_scanner_message_hardcodes_the_shared_hint(self) -> None:
        """The guard: any message naming a scanner must resolve its own hint.

        Catches the next half-fix, where one of several strings in the same
        function keeps the old constant.
        """
        import inspect

        from slopmop.checks import security

        source = inspect.getsource(security._scanner_did_not_run)
        assert (
            "_SECURITY_INSTALL_HINT" not in source
        ), "a per-scanner message is using the shared constant again"


class TestMissingBinaryIsDetectedTheWayItActuallyFails:
    """The first attempt at this guarded an exception that never arrives.

    `SubprocessRunner` catches `FileNotFoundError` and returns
    `returncode=-1` with `Command not found: <name>` in stderr, so nothing
    propagates to the gate. The dispatch handler added for `FileNotFoundError`
    was dead code for this case, and the no-JSON path only matched import
    errors — so a missing binary still failed the gate.

    It looked fixed because the test mocked `side_effect=FileNotFoundError`:
    the mock encoded the model, and the model was wrong. These exercise the
    real runner instead.
    """

    def test_the_runner_returns_rather_than_raises(self) -> None:
        """The premise. If this ever changes, the marker below is redundant."""
        from slopmop.checks.security import SecurityLocalCheck

        check = SecurityLocalCheck({})
        result = check._run_command(
            ["semgrep", "--version"], cwd="/nonexistent-dir-xyz"
        )
        assert result.returncode != 0

    def test_command_not_found_counts_as_a_startup_failure(self) -> None:
        from slopmop.checks.security import _scanner_failed_to_start

        produced = (
            "Command not found: semgrep\n"
            "[Errno 2] No such file or directory: 'semgrep'"
        )
        assert _scanner_failed_to_start(produced) is True

    def test_a_real_scan_error_is_still_a_failure(self) -> None:
        """The marker must not swallow genuine scanner breakage."""
        from slopmop.checks.security import _scanner_failed_to_start

        assert _scanner_failed_to_start("semgrep: invalid rule pack") is False

    def test_an_absent_binary_degrades_through_the_real_path(self) -> None:
        """End to end, with no exception mocked anywhere."""
        from unittest.mock import patch

        import slopmop.checks.base as base
        from slopmop.checks.security import SecurityLocalCheck

        check = SecurityLocalCheck({})
        missing = "/nonexistent/bin/semgrep"
        with patch.object(base, "find_tool", return_value=missing):
            with patch.object(check, "resolve_requirement_path", return_value=missing):
                sub = check._run_semgrep(".")

        assert sub.passed is True, "a missing binary must not fail the gate"
        assert sub.did_not_run is True
        assert "pipx install semgrep" in sub.findings


class TestGitScrubbingKeepsRestrictions:
    """Dropping a pointer is safe; dropping a restriction is not.

    `git_env` removed every GIT_* variable, including
    `GIT_CEILING_DIRECTORIES`, which only limits how far up git may search.
    Without it the probe can walk into an ancestor checkout, so a project in
    no repository at all resolves to one and borrows its virtualenv — the
    opposite of what the scrubbing is for.
    """

    @staticmethod
    def _scrubbed(extra: Dict[str, str]) -> Dict[str, str]:
        import os
        from unittest.mock import patch

        from slopmop.utils.proc import git_env

        with patch.dict(os.environ, extra, clear=True):
            return git_env()

    def test_pointers_are_removed(self) -> None:
        env = self._scrubbed(
            {
                "GIT_DIR": "/elsewhere/.git",
                "GIT_WORK_TREE": "/elsewhere",
                "GIT_INDEX_FILE": "/elsewhere/.git/index",
                "GIT_COMMON_DIR": "/elsewhere/.git",
            }
        )
        assert not [k for k in env if k.startswith("GIT_")]

    def test_the_ceiling_survives(self) -> None:
        env = self._scrubbed(
            {"GIT_DIR": "/elsewhere/.git", "GIT_CEILING_DIRECTORIES": "/home/user"}
        )
        assert env.get("GIT_CEILING_DIRECTORIES") == "/home/user"
        assert "GIT_DIR" not in env

    def test_an_unknown_git_variable_is_still_dropped(self) -> None:
        """Default stays deny: only named restrictions are kept."""
        env = self._scrubbed({"GIT_SOMETHING_NEW": "x"})
        assert "GIT_SOMETHING_NEW" not in env
