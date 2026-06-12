"""Tests for the hull grade — the deterministic rating for full runs.

Covers:
  - compute_hull_grade() boundaries (A+ through F)
  - dry-dock for uninitialized repos
  - provisional marking on operational skips
  - RunReport wiring: full runs grade, partial (-g) runs don't
  - adapter surfacing: JSON payload, porcelain line, console banner
"""

from pathlib import Path

from slopmop.core.result import CheckResult, CheckStatus, ExecutionSummary
from slopmop.reporting.adapters import ConsoleAdapter, JsonAdapter, PorcelainAdapter
from slopmop.reporting.grading import (
    HullGrade,
    compute_hull_grade,
    dry_dock_grade,
    is_repo_initialized,
)
from slopmop.reporting.report import RunReport

# ---------------------------------------------------------------------------
# Pure grading function
# ---------------------------------------------------------------------------


class TestComputeHullGrade:
    def test_all_green_is_a_plus_shipshape(self):
        grade = compute_hull_grade(failing=0, warned=0)
        assert (grade.grade, grade.level) == ("A+", "shipshape")

    def test_warnings_only_is_a_seaworthy(self):
        grade = compute_hull_grade(failing=0, warned=2)
        assert (grade.grade, grade.level) == ("A", "seaworthy")

    def test_one_failing_is_b_serviceable(self):
        grade = compute_hull_grade(failing=1, warned=0)
        assert (grade.grade, grade.level) == ("B", "serviceable")

    def test_two_failing_is_c_weathered(self):
        grade = compute_hull_grade(failing=2, warned=0)
        assert (grade.grade, grade.level) == ("C", "weathered")

    def test_three_failing_is_d_fouled(self):
        grade = compute_hull_grade(failing=3, warned=0)
        assert (grade.grade, grade.level) == ("D", "fouled")

    def test_four_failing_is_f_scuttled(self):
        grade = compute_hull_grade(failing=4, warned=0)
        assert (grade.grade, grade.level) == ("F", "scuttled")

    def test_many_failing_still_f_scuttled(self):
        grade = compute_hull_grade(failing=20, warned=5)
        assert (grade.grade, grade.level) == ("F", "scuttled")

    def test_warnings_do_not_soften_a_failing_grade(self):
        # Warnings only matter at the A+/A boundary.
        grade = compute_hull_grade(failing=1, warned=3)
        assert grade.grade == "B"
        assert grade.warned == 3

    def test_provisional_flag_carried(self):
        grade = compute_hull_grade(failing=0, warned=0, provisional=True)
        assert grade.provisional is True
        assert "provisional" in grade.label

    def test_label_format(self):
        assert compute_hull_grade(2, 0).label == "C — weathered"

    def test_to_dict_round_trip(self):
        d = compute_hull_grade(failing=1, warned=2, provisional=True).to_dict()
        assert d == {
            "grade": "B",
            "level": "serviceable",
            "failing": 1,
            "warned": 2,
            "provisional": True,
        }

    def test_dry_dock_grade(self):
        grade = dry_dock_grade()
        assert (grade.grade, grade.level) == ("N/A", "dry-dock")


class TestIsRepoInitialized:
    def test_fresh_repo_not_initialized(self, tmp_path):
        assert is_repo_initialized(str(tmp_path)) is False

    def test_sb_config_counts(self, tmp_path):
        (tmp_path / ".sb_config.json").write_text("{}")
        assert is_repo_initialized(str(tmp_path)) is True

    def test_pyproject_tool_slopmop_counts(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.slopmop]\n")
        assert is_repo_initialized(str(tmp_path)) is True

    def test_pyproject_gate_section_counts(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.slopmop.myopia.gates."dependency-risk.py"]\nfoo = 1\n'
        )
        assert is_repo_initialized(str(tmp_path)) is True

    def test_pyproject_without_slopmop_does_not_count(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.black]\n")
        assert is_repo_initialized(str(tmp_path)) is False


# ---------------------------------------------------------------------------
# RunReport wiring
# ---------------------------------------------------------------------------


def _gate_result(name: str, status: CheckStatus) -> CheckResult:
    return CheckResult(name=name, status=status, duration=0.1)


def _statuses_summary(*statuses: CheckStatus) -> ExecutionSummary:
    results = [_gate_result(f"gate-{i}", s) for i, s in enumerate(statuses)]
    return ExecutionSummary.from_results(results, duration=1.0)


def _initialized(tmp_path: Path) -> str:
    (tmp_path / ".sb_config.json").write_text("{}")
    return str(tmp_path)


class TestRunReportGrading:
    def test_full_run_gets_grade(self, tmp_path):
        summary = _statuses_summary(CheckStatus.PASSED, CheckStatus.PASSED)
        report = RunReport.from_summary(
            summary, level="swab", project_root=_initialized(tmp_path)
        )
        assert report.hull_grade is not None
        assert report.hull_grade.grade == "A+"

    def test_partial_run_gets_no_grade(self, tmp_path):
        summary = _statuses_summary(CheckStatus.PASSED)
        # level=None is how -g partial runs flow through _run_validation
        report = RunReport.from_summary(
            summary, level=None, project_root=_initialized(tmp_path)
        )
        assert report.hull_grade is None

    def test_errors_count_as_failing(self, tmp_path):
        summary = _statuses_summary(
            CheckStatus.FAILED, CheckStatus.ERROR, CheckStatus.PASSED
        )
        report = RunReport.from_summary(
            summary, level="scour", project_root=_initialized(tmp_path)
        )
        assert report.hull_grade is not None
        assert report.hull_grade.failing == 2
        assert report.hull_grade.grade == "C"

    def test_skips_make_grade_provisional(self, tmp_path):
        summary = _statuses_summary(CheckStatus.PASSED, CheckStatus.SKIPPED)
        report = RunReport.from_summary(
            summary, level="swab", project_root=_initialized(tmp_path)
        )
        assert report.hull_grade is not None
        assert report.hull_grade.provisional is True

    def test_not_applicable_does_not_mark_provisional(self, tmp_path):
        summary = _statuses_summary(CheckStatus.PASSED, CheckStatus.NOT_APPLICABLE)
        report = RunReport.from_summary(
            summary, level="swab", project_root=_initialized(tmp_path)
        )
        assert report.hull_grade is not None
        assert report.hull_grade.provisional is False
        assert report.hull_grade.grade == "A+"

    def test_uninitialized_repo_is_dry_dock(self, tmp_path):
        summary = _statuses_summary(CheckStatus.FAILED, CheckStatus.FAILED)
        report = RunReport.from_summary(
            summary, level="swab", project_root=str(tmp_path)
        )
        assert report.hull_grade is not None
        assert report.hull_grade.grade == "N/A"
        assert report.hull_grade.level == "dry-dock"

    def test_no_project_root_still_grades(self):
        summary = _statuses_summary(CheckStatus.PASSED)
        report = RunReport.from_summary(summary, level="swab", project_root=None)
        assert report.hull_grade is not None
        assert report.hull_grade.grade == "A+"


# ---------------------------------------------------------------------------
# Adapter surfacing
# ---------------------------------------------------------------------------


class TestAdapterSurfacing:
    def _graded_report(self, tmp_path: Path, *statuses: CheckStatus) -> RunReport:
        return RunReport.from_summary(
            _statuses_summary(*statuses),
            level="swab",
            project_root=_initialized(tmp_path),
        )

    def test_json_payload_includes_hull_grade(self, tmp_path):
        report = self._graded_report(tmp_path, CheckStatus.FAILED, CheckStatus.PASSED)
        envelope = JsonAdapter.render(report)
        data = envelope["data"]
        assert isinstance(data, dict)
        assert data["hull_grade"] == {
            "grade": "B",
            "level": "serviceable",
            "failing": 1,
            "warned": 0,
            "provisional": False,
        }

    def test_json_payload_omits_grade_on_partial_run(self, tmp_path):
        report = RunReport.from_summary(
            _statuses_summary(CheckStatus.PASSED),
            level=None,
            project_root=_initialized(tmp_path),
        )
        envelope = JsonAdapter.render(report)
        data = envelope["data"]
        assert isinstance(data, dict)
        assert "hull_grade" not in data

    def test_porcelain_includes_grade_line(self, tmp_path):
        report = self._graded_report(tmp_path, CheckStatus.PASSED)
        output = PorcelainAdapter.render(report)
        assert "grade: A+ — shipshape" in output

    def test_console_success_includes_hull_rating(self, tmp_path, capsys):
        report = self._graded_report(tmp_path, CheckStatus.PASSED)
        ConsoleAdapter(report).render()
        assert "⚓ hull rating: A+ — shipshape" in capsys.readouterr().out

    def test_console_failure_includes_hull_rating(self, tmp_path, capsys):
        report = self._graded_report(
            tmp_path,
            CheckStatus.FAILED,
            CheckStatus.FAILED,
            CheckStatus.FAILED,
            CheckStatus.FAILED,
        )
        ConsoleAdapter(report).render()
        assert "⚓ hull rating: F — scuttled" in capsys.readouterr().out


class TestHullGradeDeterminism:
    def test_same_counts_same_grade(self):
        a = compute_hull_grade(failing=2, warned=1)
        b = compute_hull_grade(failing=2, warned=1)
        assert a == b

    def test_frozen(self):
        import dataclasses

        import pytest

        grade = compute_hull_grade(0, 0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            grade.grade = "F"  # type: ignore[misc]

    def test_grade_is_hashable_value_object(self):
        assert isinstance(compute_hull_grade(1, 0), HullGrade)
        assert len({compute_hull_grade(1, 0), compute_hull_grade(1, 0)}) == 1
