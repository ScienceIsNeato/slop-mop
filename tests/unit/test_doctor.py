"""Tests for ``sm doctor`` — framework, registry, output, and CLI driver.

Per-check behaviour (runtime.*, sm_env.*, project.*, state.*) and the
``--fix`` flows live in ``test_doctor_checks.py``.  This file covers the
scaffolding around them: the ``DoctorCheck`` contract, the explicit
registry, pattern selection, crash containment in ``run_checks`` /
``run_fixes``, human/JSON formatters, exit-code rules, and the
``cmd_doctor`` entry point end-to-end.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slopmop.cli.doctor import (
    _exit_code,
    _format_human,
    _format_json,
    _validate_patterns,
    cmd_doctor,
)
from slopmop.core.lock import LOCK_DIR, LOCK_FILE
from slopmop.doctor import (
    ALL_CHECKS,
    CHECKS_BY_NAME,
    DoctorContext,
    DoctorResult,
    DoctorStatus,
    run_checks,
    run_fixes,
    select_checks,
)
from slopmop.doctor.base import DoctorCheck

# ── fixtures / helpers ───────────────────────────────────────────────────


@pytest.fixture()
def ctx(tmp_path: Path) -> DoctorContext:  # noqa: ambiguity-mine
    return DoctorContext(project_root=tmp_path)


def _mk_lock(root: Path, meta: dict) -> Path:  # noqa: ambiguity-mine
    lock_dir = root / LOCK_DIR
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / LOCK_FILE
    lock_file.write_text(json.dumps(meta))
    return lock_file


def _doctor_args(**kw) -> argparse.Namespace:
    """Build a Namespace matching what argparse would produce."""
    defaults = dict(
        checks=[],
        list_checks=False,
        fix=False,
        yes=False,
        json_output=None,
        project_root=".",
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _sample_results() -> list[DoctorResult]:
    return [
        DoctorResult("runtime.platform", DoctorStatus.OK, "Python 3.x", detail="dump"),
        DoctorResult(
            "state.lock",
            DoctorStatus.FAIL,
            "stale lock",
            detail="Lock file: /x\nPID: 9",
            fix_hint="sm doctor --fix state.lock",
            can_fix=True,
        ),
        DoctorResult(
            "project.js_deps",
            DoctorStatus.WARN,
            "no node_modules",
            detail="Detail",
        ),
        DoctorResult("project.pip_check", DoctorStatus.SKIP, "no venv"),
    ]


# ── registry contract ────────────────────────────────────────────────────


class TestRegistry:
    """Sanity on the explicit registry — stable names, no dupes, all wired."""

    def test_all_checks_populated(self):
        assert len(ALL_CHECKS) >= 11

    def test_names_unique(self):
        names = [c.name for c in ALL_CHECKS]
        assert len(names) == len(set(names))

    def test_checks_by_name_roundtrip(self):
        for cls in ALL_CHECKS:
            assert CHECKS_BY_NAME[cls.name] is cls

    def test_names_are_dotted(self):
        """group.specific — so glob selection works and --list-checks aligns."""
        for cls in ALL_CHECKS:
            assert "." in cls.name, f"{cls.name} should be namespaced"

    def test_descriptions_nonempty(self):
        for cls in ALL_CHECKS:
            assert cls.description.strip()

    def test_only_state_checks_can_fix(self):
        """--fix is scoped to .slopmop/ turf — nothing else should claim it."""
        fixable = {c.name for c in ALL_CHECKS if c.can_fix}
        assert fixable == {
            "state.lock",
            "state.dir_permissions",
            "state.config_readable",
        }


class TestSelectChecks:
    def test_empty_returns_all(self):
        assert select_checks([]) == ALL_CHECKS
        assert select_checks(None) == ALL_CHECKS

    def test_exact_name(self):
        result = select_checks(["state.lock"])
        assert len(result) == 1
        assert result[0].name == "state.lock"

    def test_glob_pattern(self):
        result = select_checks(["state.*"])
        names = {c.name for c in result}
        assert names == {
            "state.lock",
            "state.dir_permissions",
            "state.config_readable",
        }

    def test_multiple_patterns(self):
        result = select_checks(["runtime.platform", "state.lock"])
        assert {c.name for c in result} == {"runtime.platform", "state.lock"}

    def test_nonmatching_pattern_returns_empty(self):
        assert select_checks(["no.such.check"]) == []

    def test_preserves_registry_order(self):
        """Selection keeps registry ordering so table is stable."""
        all_names = [c.name for c in ALL_CHECKS]
        selected = select_checks(["*"])
        assert [c.name for c in selected] == all_names


# ── crash containment ────────────────────────────────────────────────────


class TestRunChecks:
    def test_crashing_check_becomes_fail_result(self, ctx):
        """doctor must survive a check that raises — report it, don't die."""

        class Exploding(DoctorCheck):
            name = "test.explode"
            description = "raises"

            def run(self, ctx):
                raise RuntimeError("kaboom")

        with patch("slopmop.doctor.select_checks", return_value=[Exploding]):
            results = run_checks(ctx)
        assert len(results) == 1
        assert results[0].status is DoctorStatus.FAIL
        assert results[0].summary == "check crashed"
        assert "kaboom" in results[0].detail

    def test_passes_ctx_through(self, tmp_path):
        ctx = DoctorContext(project_root=tmp_path)
        results = run_checks(ctx, patterns=["runtime.platform"])
        assert len(results) == 1
        assert str(tmp_path) in results[0].detail


class TestRunFixes:
    def test_skips_ok_results(self, ctx):
        ok = DoctorResult("state.lock", DoctorStatus.OK, "fine", can_fix=True)
        assert run_fixes(ctx, [ok]) == {}

    def test_skips_non_fixable(self, ctx):
        fail = DoctorResult(
            "runtime.platform", DoctorStatus.FAIL, "broken", can_fix=False
        )
        assert run_fixes(ctx, [fail]) == {}

    def test_crashing_fix_becomes_fail_result(self, ctx):
        class BadFix(DoctorCheck):
            name = "test.badfix"
            description = "fix raises"
            can_fix = True

            def run(self, ctx):
                return self._fail("broken")

            def fix(self, ctx):
                raise IOError("disk full")

        result = BadFix().run(ctx)
        with patch.dict(CHECKS_BY_NAME, {"test.badfix": BadFix}):
            fixed = run_fixes(ctx, [result])
        assert fixed["test.badfix"].status is DoctorStatus.FAIL
        assert fixed["test.badfix"].summary == "fix crashed"
        assert "disk full" in fixed["test.badfix"].detail


class TestDoctorCheckABC:
    def test_default_fix_raises(self, ctx):
        """Checks that don't set can_fix shouldn't silently no-op on fix()."""

        class NoFix(DoctorCheck):
            name = "test.nofix"
            description = "x"

            def run(self, ctx):
                return self._ok("fine")

        with pytest.raises(NotImplementedError, match="does not support --fix"):
            NoFix().fix(ctx)

    def test_warn_and_fail_carry_can_fix(self, ctx):
        """can_fix=True on the class propagates to WARN/FAIL results."""

        class Fixable(DoctorCheck):
            name = "test.fixable"
            description = "x"
            can_fix = True

            def run(self, ctx):
                return self._fail("broken")

        r = Fixable().run(ctx)
        assert r.can_fix is True

    def test_sort_key_orders_fail_first(self):
        results = [
            DoctorResult("a", DoctorStatus.OK, ""),
            DoctorResult("b", DoctorStatus.SKIP, ""),
            DoctorResult("c", DoctorStatus.FAIL, ""),
            DoctorResult("d", DoctorStatus.WARN, ""),
        ]
        ordered = sorted(results, key=lambda r: r.sort_key())
        assert [r.status for r in ordered] == [
            DoctorStatus.FAIL,
            DoctorStatus.WARN,
            DoctorStatus.OK,
            DoctorStatus.SKIP,
        ]


# ── output formatting ────────────────────────────────────────────────────


class TestFormatHuman:
    def test_header_has_counts(self):
        out = _format_human(_sample_results())
        assert out.startswith("sm doctor — 1 FAIL, 1 WARN, 1 OK, 1 SKIP")

    def test_fail_sorts_first_in_table(self):
        out = _format_human(_sample_results())
        body = out.split("\n\n")[1]
        lines = [l for l in body.splitlines() if l.strip()]
        assert "✗" in lines[0]
        assert "○" in lines[-1]

    def test_detail_block_only_for_non_ok_and_platform(self):
        out = _format_human(_sample_results())
        # Platform detail always shown (bug-report header).
        assert "── runtime.platform " in out
        assert "── state.lock " in out
        # SKIP has no detail content set, so no block.
        assert "── project.pip_check " not in out

    def test_fix_hint_rendered(self):
        out = _format_human(_sample_results())
        assert "Fix:\n  sm doctor --fix state.lock" in out

    def test_fix_block_appended(self):
        post = {"state.lock": DoctorResult("state.lock", DoctorStatus.OK, "removed")}
        out = _format_human(_sample_results(), post)
        assert "── --fix " in out
        assert "✓ state.lock" in out


class TestFormatJson:
    def test_roundtrips(self):
        payload = json.loads(_format_json(_sample_results()))
        assert payload["summary"].startswith("1 FAIL")
        assert payload["exit_code"] == 1
        assert len(payload["checks"]) == 4
        assert all(
            c["status"] in ("ok", "warn", "fail", "skip") for c in payload["checks"]
        )

    def test_includes_fixes_when_present(self):
        post = {"state.lock": DoctorResult("state.lock", DoctorStatus.OK, "removed")}
        payload = json.loads(_format_json(_sample_results(), post))
        assert payload["fixes"]["state.lock"]["status"] == "ok"
        # Exit code drops to 0 because the only FAIL was fixed.
        assert payload["exit_code"] == 0


class TestExitCode:
    def test_zero_when_no_fail(self):
        results = [
            DoctorResult("a", DoctorStatus.OK, ""),
            DoctorResult("b", DoctorStatus.WARN, ""),
        ]
        assert _exit_code(results) == 0

    def test_one_on_unresolved_fail(self):
        results = [DoctorResult("a", DoctorStatus.FAIL, "")]
        assert _exit_code(results) == 1

    def test_zero_when_fix_resolved_the_fail(self):
        results = [DoctorResult("a", DoctorStatus.FAIL, "", can_fix=True)]
        fixed = {"a": DoctorResult("a", DoctorStatus.OK, "fixed")}
        assert _exit_code(results, fixed) == 0

    def test_one_when_fix_did_not_resolve(self):
        results = [DoctorResult("a", DoctorStatus.FAIL, "", can_fix=True)]
        fixed = {"a": DoctorResult("a", DoctorStatus.FAIL, "still broken")}
        assert _exit_code(results, fixed) == 1

    def test_skip_does_not_affect_exit(self):
        results = [DoctorResult("a", DoctorStatus.SKIP, "")]
        assert _exit_code(results) == 0


class TestValidatePatterns:
    def test_empty_passes(self):
        assert _validate_patterns([]) == []

    def test_known_name_passes(self):
        assert _validate_patterns(["state.lock"]) == ["state.lock"]

    def test_glob_passes(self):
        assert _validate_patterns(["state.*"]) == ["state.*"]

    def test_typo_raises_with_available_list(self):
        with pytest.raises(SystemExit) as exc_info:
            _validate_patterns(["stat.lock"])
        msg = str(exc_info.value)
        assert "stat.lock" in msg
        assert "state.lock" in msg  # available names listed


# ── cmd_doctor integration ───────────────────────────────────────────────


class TestCmdDoctor:
    def test_list_checks_exits_zero(self, capsys):
        rc = cmd_doctor(_doctor_args(list_checks=True))
        out = capsys.readouterr().out
        assert rc == 0
        assert "state.lock" in out
        assert "[--fix]" in out

    def test_json_output_parses(self, capsys, tmp_path):
        rc = cmd_doctor(_doctor_args(json_output=True, project_root=str(tmp_path)))
        payload = json.loads(capsys.readouterr().out)
        assert "summary" in payload
        assert "checks" in payload
        assert isinstance(rc, int)

    def test_check_subset_runs_only_selected(self, capsys, tmp_path):
        rc = cmd_doctor(
            _doctor_args(
                checks=["runtime.platform"],
                json_output=True,
                project_root=str(tmp_path),
            )
        )
        payload = json.loads(capsys.readouterr().out)
        assert [c["name"] for c in payload["checks"]] == ["runtime.platform"]
        assert rc == 0

    def test_unknown_check_exits_nonzero(self, tmp_path):
        with pytest.raises(SystemExit):
            cmd_doctor(_doctor_args(checks=["typo.city"], project_root=str(tmp_path)))

    def test_fix_removes_stale_lock_end_to_end(self, capsys, tmp_path):
        """The headline --fix path: stale lock → doctor --fix → gone, exit 0."""
        lock_file = _mk_lock(
            tmp_path,
            {"pid": 99999999, "verb": "swab", "started_at": 0},
        )
        rc = cmd_doctor(
            _doctor_args(
                checks=["state.lock"],
                fix=True,
                yes=True,
                json_output=True,
                project_root=str(tmp_path),
            )
        )
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert not lock_file.exists()
        assert payload["fixes"]["state.lock"]["status"] == "ok"

    def test_fix_aborts_on_no(self, capsys, tmp_path, monkeypatch):
        """Interactive --fix prompt: 'n' → nothing touched, report still printed."""
        lock_file = _mk_lock(
            tmp_path,
            {"pid": 99999999, "verb": "swab", "started_at": 0},
        )
        monkeypatch.setattr("sys.stdin", MagicMock(isatty=lambda: True))
        monkeypatch.setattr("sys.stdin.readline", lambda: "n\n")
        rc = cmd_doctor(
            _doctor_args(
                checks=["state.lock"],
                fix=True,
                json_output=False,
                project_root=str(tmp_path),
            )
        )
        captured = capsys.readouterr()
        assert rc == 1  # still failing — fix aborted
        assert lock_file.exists()
        # Declining the prompt must still show the diagnostic report —
        # early-returning before output defeats the point of running
        # doctor at all.
        assert "sm doctor —" in captured.out
        assert "state.lock" in captured.out
        assert "Aborted" in captured.err

    def test_fix_json_mode_still_prompts(self, capsys, tmp_path, monkeypatch):
        """--fix --json must still confirm: no silent mutation without --yes."""
        lock_file = _mk_lock(
            tmp_path,
            {"pid": 99999999, "verb": "swab", "started_at": 0},
        )
        monkeypatch.setattr("sys.stdin", MagicMock(isatty=lambda: True))
        monkeypatch.setattr("sys.stdin.readline", lambda: "n\n")
        rc = cmd_doctor(
            _doctor_args(
                checks=["state.lock"],
                fix=True,
                json_output=True,  # JSON on, --yes NOT passed
                project_root=str(tmp_path),
            )
        )
        captured = capsys.readouterr()
        assert lock_file.exists()  # declined → not removed
        assert rc == 1
        # Prompt went to stderr, stdout stayed valid JSON.
        assert "Proceed?" in captured.err
        json.loads(captured.out)

    def test_fix_skipped_when_nothing_fixable(self, capsys, tmp_path):
        """--fix on an OK result is a no-op, not an error."""
        rc = cmd_doctor(
            _doctor_args(
                checks=["state.lock"],
                fix=True,
                yes=True,
                json_output=True,
                project_root=str(tmp_path),
            )
        )
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert "fixes" not in payload

    def test_non_tty_auto_enables_json(self, capsys, tmp_path, monkeypatch):
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        cmd_doctor(
            _doctor_args(checks=["runtime.platform"], project_root=str(tmp_path))
        )
        out = capsys.readouterr().out
        json.loads(out)  # parses → JSON mode was on

    def test_no_json_forces_human(self, capsys, tmp_path, monkeypatch):
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        cmd_doctor(
            _doctor_args(
                checks=["runtime.platform"],
                json_output=False,
                project_root=str(tmp_path),
            )
        )
        out = capsys.readouterr().out
        assert out.startswith("sm doctor —")


# ── classify_install (non-raising core) ──────────────────────────────────


class TestClassifyInstall:
    """Cover the non-raising wrapper added for doctor's benefit.

    ``_detect_install_type`` already has its own tests; these verify the
    non-raising paths that doctor depends on.
    """

    def test_editable_returned_not_raised(self):
        from slopmop.cli.upgrade import classify_install

        mode = classify_install(
            executable="/venv/bin/python",
            prefix="/venv",
            base_prefix="/usr",
            direct_url={"dir_info": {"editable": True}},
        )
        assert mode == "editable"

    def test_system_returned_not_raised(self):
        from slopmop.cli.upgrade import classify_install

        mode = classify_install(
            executable="/usr/bin/python3",
            prefix="/usr",
            base_prefix="/usr",
            virtual_env="",
        )
        assert mode == "system"

    def test_pipx_detection(self):
        from slopmop.cli.upgrade import classify_install

        mode = classify_install(
            executable="/home/user/.local/pipx/venvs/slopmop/bin/python",
            prefix="/home/user/.local/pipx/venvs/slopmop",
            base_prefix="/usr",
            virtual_env="",
        )
        assert mode == "pipx"
