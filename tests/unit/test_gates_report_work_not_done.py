"""A gate that did not do its work must not report success.

Three barnacles from one repo, all the same shape: slop-mop said a thing was
checked when nothing had been. That is worse than a gate being absent, because
a green board is believed.

- #366 semgrep exits 0 with findings; the gate read the exit status and
  returned "No issues found" without opening the report.
- #365 a semgrep killed by the timeout produced no JSON, which fell through to
  "Scan completed" — a scan that never completed.
- #367 a git worktree has no venv of its own, so the test gate warned and
  returned in a millisecond while scour reported everything passed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slopmop.checks.mixins import (
    _main_worktree_root,
    has_project_venv,
    resolve_project_python,
)
from slopmop.checks.security import SecurityLocalCheck


def _semgrep_result(**kwargs: object) -> MagicMock:
    result = MagicMock()
    result.success = kwargs.get("success", True)
    result.timed_out = kwargs.get("timed_out", False)
    result.stdout = kwargs.get("stdout", "")
    result.stderr = kwargs.get("stderr", "")
    result.output = kwargs.get("output", "")
    result.returncode = kwargs.get("returncode", 0)
    return result


class TestSemgrepFindingsAreRead:
    """#366 — the exit status says semgrep ran, nothing more."""

    @staticmethod
    def _report(count: int, severity: str = "ERROR") -> str:
        return json.dumps(
            {
                "results": [
                    {
                        "extra": {"severity": severity, "message": f"issue {i}"},
                        "path": f"mod{i}.py",
                        "start": {"line": i + 1},
                        "check_id": f"rule.{i}",
                    }
                    for i in range(count)
                ]
            }
        )

    def test_findings_on_a_zero_exit_are_reported(self, tmp_path: Path) -> None:
        """The reported case: 34 findings came back as "No issues found"."""
        check = SecurityLocalCheck({})
        result = _semgrep_result(success=True, stdout=self._report(34))

        with patch.object(check, "_run_command", return_value=result):
            sub = check._run_semgrep(str(tmp_path))

        assert sub.passed is False
        assert "No issues found" not in sub.findings
        assert len(sub.sarif_findings) == 34

    def test_long_finding_lists_are_summarised_not_truncated_silently(
        self, tmp_path: Path
    ) -> None:
        check = SecurityLocalCheck({})
        result = _semgrep_result(success=True, stdout=self._report(34))

        with patch.object(check, "_run_command", return_value=result):
            sub = check._run_semgrep(str(tmp_path))

        assert "and 24 more" in sub.findings

    def test_informational_only_still_passes(self, tmp_path: Path) -> None:
        """Turning findings on must not make INFO noise fail the build."""
        check = SecurityLocalCheck({})
        result = _semgrep_result(success=True, stdout=self._report(3, "INFO"))

        with patch.object(check, "_run_command", return_value=result):
            sub = check._run_semgrep(str(tmp_path))

        assert sub.passed is True

    def test_empty_report_passes(self, tmp_path: Path) -> None:
        check = SecurityLocalCheck({})
        result = _semgrep_result(success=True, stdout=json.dumps({"results": []}))

        with patch.object(check, "_run_command", return_value=result):
            sub = check._run_semgrep(str(tmp_path))

        assert sub.passed is True
        assert "No issues found" in sub.findings


class TestSemgrepTimeoutIsNotAPass:
    """#365 — "Scan completed" was reported for a scan that was killed."""

    def test_timeout_fails(self, tmp_path: Path) -> None:
        check = SecurityLocalCheck({})
        result = _semgrep_result(success=False, timed_out=True, stdout="")

        with patch.object(check, "_run_command", return_value=result):
            sub = check._run_semgrep(str(tmp_path))

        assert sub.passed is False
        assert "Scan completed" not in sub.findings

    def test_timeout_says_nothing_was_verified(self, tmp_path: Path) -> None:
        """The reader has to know the gap is coverage, not a found defect."""
        check = SecurityLocalCheck({})
        result = _semgrep_result(success=False, timed_out=True)

        with patch.object(check, "_run_command", return_value=result):
            sub = check._run_semgrep(str(tmp_path))

        assert "incomplete" in sub.findings
        assert "nothing here was verified" in sub.findings

    def test_unparseable_output_is_not_a_pass(self, tmp_path: Path) -> None:
        """No report means no verdict — the old code defaulted to pass."""
        check = SecurityLocalCheck({})
        result = _semgrep_result(
            success=False, stdout="not json", stderr="boom", returncode=2
        )

        with patch.object(check, "_run_command", return_value=result):
            sub = check._run_semgrep(str(tmp_path))

        assert sub.passed is False

    def test_scanner_that_never_started_is_still_a_did_not_run(
        self, tmp_path: Path
    ) -> None:
        """Not-installed keeps its own reporting; it is not a finding."""
        check = SecurityLocalCheck({})
        result = _semgrep_result(
            success=False,
            stdout="",
            output="semgrep: command not found",
            returncode=127,
        )

        with patch.object(check, "_run_command", return_value=result):
            sub = check._run_semgrep(str(tmp_path))

        assert "not found" in sub.findings.lower() or sub.passed is False


@pytest.fixture
def worktree(tmp_path: Path) -> tuple[Path, Path]:
    """A repo with a gitignored venv, plus a linked worktree without one."""
    main = tmp_path / "main"
    main.mkdir()

    def git(*args: str, cwd: Path = main) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

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


class TestWorktreeFindsTheProjectVenv:
    """#367 — the whole suite was skipped, and the run reported all_passed."""

    def test_worktree_has_no_venv_of_its_own(self, worktree: tuple[Path, Path]) -> None:
        """The precondition: venvs are gitignored, so a worktree never gets one."""
        _, wt = worktree
        assert not (wt / "venv").exists()
        assert not (wt / ".venv").exists()

    def test_worktree_venv_is_found(self, worktree: tuple[Path, Path]) -> None:
        _, wt = worktree
        assert has_project_venv(wt) is True

    def test_worktree_resolves_the_main_checkout_interpreter(
        self, worktree: tuple[Path, Path]
    ) -> None:
        main, wt = worktree
        python, source = resolve_project_python(str(wt))
        assert python == str(main / "venv" / "bin" / "python")
        assert source == "project_venv"

    def test_main_checkout_does_not_resolve_to_itself(
        self, worktree: tuple[Path, Path]
    ) -> None:
        """Guards against a fallback that always fires and hides a real absence."""
        main, _ = worktree
        assert _main_worktree_root(main) is None

    def test_a_venvless_project_still_reports_no_venv(self, tmp_path: Path) -> None:
        """The fallback must not invent a venv where the project has none."""
        subprocess.run(
            ["git", "init", "-q", "."], cwd=tmp_path, check=True, capture_output=True
        )
        assert has_project_venv(tmp_path) is False

    def test_non_repo_directory_is_handled(self, tmp_path: Path) -> None:
        """Not every project is a git repo; the probe must not raise."""
        assert has_project_venv(tmp_path) is False
        assert _main_worktree_root(tmp_path) is None


class TestSkippedWorkSaysSoPlainly:
    def test_warning_names_the_consequence_not_just_the_cause(
        self, tmp_path: Path
    ) -> None:
        """ "No venv found" read as an environment note among 26 passes."""
        import time

        from slopmop.checks.python.tests import PythonTestsCheck

        check = PythonTestsCheck({})
        subprocess.run(
            ["git", "init", "-q", "."], cwd=tmp_path, check=True, capture_output=True
        )
        result = check.check_project_venv_or_warn(str(tmp_path), time.time())

        assert result is not None
        assert "did not run" in (result.error or "")
        assert "nothing it covers was verified" in (result.error or "")


class TestSemgrepRuleExclusion:
    """Excluding an inapplicable rule is not the same as accepting findings.

    Reading findings at all (#366) surfaced seven on slop-mop itself, none of
    them real: four from a Python-3.7 compatibility ruleset on a repo that
    requires 3.10, and three rules that are sound in general but wrong at
    those lines. A rule that cannot be true here is excluded by id; a finding
    that is simply judged wrong is suppressed at the line it is about.
    """

    @staticmethod
    def _report(*check_ids: str) -> dict:
        return {
            "results": [
                {
                    "check_id": cid,
                    "extra": {"severity": "ERROR", "message": f"from {cid}"},
                    "path": "mod.py",
                    "start": {"line": 1},
                }
                for cid in check_ids
            ]
        }

    def test_excluded_ruleset_prefix_drops_its_rules(self) -> None:
        result = SecurityLocalCheck._semgrep_report_result(
            self._report("python.lang.compatibility.python37.importlib2"),
            ["python.lang.compatibility.python37"],
        )
        assert result.passed is True

    def test_other_rules_still_fail(self) -> None:
        """The exclusion must be narrow, or the gate goes back to meaning nothing."""
        result = SecurityLocalCheck._semgrep_report_result(
            self._report(
                "python.lang.compatibility.python37.importlib2",
                "python.lang.security.audit.dangerous-exec.dangerous-exec",
            ),
            ["python.lang.compatibility.python37"],
        )
        assert result.passed is False
        assert len(result.sarif_findings) == 1

    def test_no_exclusions_by_default(self) -> None:
        """A repo starts by seeing everything; nothing is waved through for it."""
        assert SecurityLocalCheck({})._semgrep_excluded_rules() == []

    def test_exclusions_are_read_from_config(self) -> None:
        check = SecurityLocalCheck({"semgrep_exclude_rules": ["a.b", "c.d"]})
        assert check._semgrep_excluded_rules() == ["a.b", "c.d"]

    def test_a_single_string_is_accepted(self) -> None:
        check = SecurityLocalCheck({"semgrep_exclude_rules": "a.b"})
        assert check._semgrep_excluded_rules() == ["a.b"]

    def test_exclusion_is_applied_to_the_report_not_the_cli(self, tmp_path) -> None:
        """--exclude-rule is not in every semgrep; a flag it ignores would
        silently reinstate the rules the project ruled out."""
        check = SecurityLocalCheck(
            {"semgrep_exclude_rules": ["python.lang.compatibility.python37"]}
        )
        captured: dict = {}

        def _fake_run(cmd, **_kwargs):
            captured["cmd"] = cmd
            return _semgrep_result(
                success=True,
                stdout=json.dumps(
                    self._report("python.lang.compatibility.python37.importlib2")
                ),
            )

        with patch.object(check, "_run_command", side_effect=_fake_run):
            sub = check._run_semgrep(str(tmp_path))

        assert "--exclude-rule" not in captured["cmd"]
        assert sub.passed is True
