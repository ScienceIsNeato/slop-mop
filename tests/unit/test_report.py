"""Tests for RunReport and the output adapters.

RunReport is the single canonical enriched view of a run.  These tests
verify that:
  * categorisation happens once and matches what adapters need
  * log file writing is deterministic and reference-able
  * JsonAdapter produces the same enrichment the old inline code did
  * ConsoleAdapter renders failures with role badges + rerun hints
  * SarifAdapter delegates to SarifReporter without data loss
"""

import json

import pytest

from slopmop.core.result import (
    CheckResult,
    CheckStatus,
    ExecutionSummary,
    Finding,
)
from slopmop.reporting.report import (
    JSON_SCHEMA,
    ConsoleAdapter,
    JsonAdapter,
    RunReport,
    SarifAdapter,
)


# ─── Fixtures ────────────────────────────────────────────────────────────


def _mk_result(name: str, status: CheckStatus, **kw) -> CheckResult:
    return CheckResult(name=name, status=status, duration=0.1, **kw)


def _mk_summary(results: list[CheckResult]) -> ExecutionSummary:
    return ExecutionSummary.from_results(results, duration=1.5)


@pytest.fixture
def mixed_summary() -> ExecutionSummary:
    """One of each status, with roles set on the foundation/diagnostic pair."""
    return _mk_summary(
        [
            _mk_result("lint", CheckStatus.PASSED, role="foundation"),
            _mk_result("types", CheckStatus.FAILED, role="foundation", error="bad"),
            _mk_result(
                "sprawl", CheckStatus.FAILED, role="diagnostic", output="too big"
            ),
            _mk_result("tests", CheckStatus.WARNED, role="foundation"),
            _mk_result("dead", CheckStatus.SKIPPED, role="diagnostic"),
            _mk_result("dup", CheckStatus.ERROR, role="diagnostic", error="boom"),
        ]
    )


# ─── RunReport.from_summary ──────────────────────────────────────────────


class TestRunReportCategorisation:
    def test_buckets_by_status(self, mixed_summary):
        report = RunReport.from_summary(mixed_summary, "", write_logs=False)

        assert [r.name for r in report.passed] == ["lint"]
        assert [r.name for r in report.failed] == ["types", "sprawl"]
        assert [r.name for r in report.warned] == ["tests"]
        assert [r.name for r in report.skipped] == ["dead"]
        assert [r.name for r in report.errors] == ["dup"]

    def test_empty_summary_produces_empty_buckets(self):
        report = RunReport.from_summary(_mk_summary([]), "", write_logs=False)
        assert report.passed == []
        assert report.failed == []
        assert report.all_passed  # 0 failures, 0 errors

    def test_first_actionable_prefers_failed_over_error(self, mixed_summary):
        report = RunReport.from_summary(mixed_summary, "", write_logs=False)
        # FAILED wins over ERROR — fix the slop before fixing the tool.
        assert report.first_actionable is not None
        assert report.first_actionable.name == "types"

    def test_first_actionable_falls_back_to_error(self):
        summary = _mk_summary([_mk_result("x", CheckStatus.ERROR, error="boom")])
        report = RunReport.from_summary(summary, "", write_logs=False)
        assert report.first_actionable is not None
        assert report.first_actionable.name == "x"

    def test_first_actionable_none_when_clean(self):
        summary = _mk_summary([_mk_result("x", CheckStatus.PASSED)])
        report = RunReport.from_summary(summary, "", write_logs=False)
        assert report.first_actionable is None
        assert report.next_steps == []


class TestRunReportRoleCounts:
    def test_splits_by_role(self, mixed_summary):
        report = RunReport.from_summary(mixed_summary, "", write_logs=False)
        roles = report.role_counts()

        # foundation: lint passed, types failed, tests warned (warned isn't
        # pass OR fail so doesn't count in either column)
        assert roles["foundation"]["passed"] == 1
        assert roles["foundation"]["failed"] == 1

        # diagnostic: sprawl failed, dead skipped (neither), dup errored
        assert roles["diagnostic"]["passed"] == 0
        assert roles["diagnostic"]["failed"] == 2  # FAILED + ERROR both count

    def test_unknown_role_bucketed(self):
        summary = _mk_summary([_mk_result("legacy", CheckStatus.PASSED, role=None)])
        report = RunReport.from_summary(summary, "", write_logs=False)
        assert report.role_counts()["unknown"]["passed"] == 1

    def test_empty_when_no_results(self):
        report = RunReport.from_summary(_mk_summary([]), "", write_logs=False)
        assert report.role_counts() == {}


class TestVerifyCommand:
    def test_builds_rerun_command(self):
        result = _mk_result("laziness:dead-code.py", CheckStatus.FAILED)
        assert (
            RunReport.verify_command(result)
            == "sm swab -g laziness:dead-code.py --verbose"
        )

    def test_next_steps_uses_first_actionable(self, mixed_summary):
        report = RunReport.from_summary(mixed_summary, "", write_logs=False)
        assert report.next_steps == ["sm swab -g types --verbose"]


class TestLogWriting:
    def test_writes_logs_for_failed_and_error(self, tmp_path, mixed_summary):
        report = RunReport.from_summary(
            mixed_summary, str(tmp_path), write_logs=True
        )

        # types (FAILED), sprawl (FAILED), dup (ERROR) — three logs
        assert set(report.log_files) == {"types", "sprawl", "dup"}

        # Verify one log actually exists on disk with the expected content.
        log_path = tmp_path / ".slopmop" / "logs" / "types.log"
        assert log_path.exists()
        content = log_path.read_text()
        assert "Check: types" in content
        assert "Status: failed" in content

    def test_write_logs_false_skips_disk(self, tmp_path, mixed_summary):
        report = RunReport.from_summary(
            mixed_summary, str(tmp_path), write_logs=False
        )
        assert report.log_files == {}
        assert not (tmp_path / ".slopmop").exists()

    def test_no_project_root_no_logs(self, mixed_summary):
        report = RunReport.from_summary(mixed_summary, "", write_logs=True)
        assert report.log_files == {}


# ─── JsonAdapter ─────────────────────────────────────────────────────────


class TestJsonAdapter:
    def test_schema_version_is_v2(self, mixed_summary):
        """Schema bumped when role + fix_strategy were added."""
        report = RunReport.from_summary(mixed_summary, "", write_logs=False)
        payload = json.loads(JsonAdapter.render(report))
        assert payload["schema"] == JSON_SCHEMA
        assert JSON_SCHEMA == "slopmop/v2"

    def test_level_included_when_set(self):
        report = RunReport.from_summary(
            _mk_summary([]), "", level="swab", write_logs=False
        )
        payload = json.loads(JsonAdapter.render(report))
        assert payload["level"] == "swab"

    def test_level_omitted_when_none(self):
        report = RunReport.from_summary(_mk_summary([]), "", write_logs=False)
        payload = json.loads(JsonAdapter.render(report))
        assert "level" not in payload

    def test_next_steps_for_first_failure(self, mixed_summary):
        report = RunReport.from_summary(mixed_summary, "", write_logs=False)
        payload = json.loads(JsonAdapter.render(report))
        assert payload["next_steps"] == ["sm swab -g types --verbose"]

    def test_log_files_attached_to_results(self, tmp_path, mixed_summary):
        report = RunReport.from_summary(mixed_summary, str(tmp_path))
        payload = json.loads(JsonAdapter.render(report))

        by_name = {r["name"]: r for r in payload["results"]}
        # Failed results get log_file; warned results don't (no log written).
        assert "log_file" in by_name["types"]
        assert by_name["types"]["log_file"].endswith("types.log")
        assert "log_file" not in by_name["tests"]  # WARNED, no log

    def test_roles_included(self, mixed_summary):
        report = RunReport.from_summary(mixed_summary, "", write_logs=False)
        payload = json.loads(JsonAdapter.render(report))
        assert "roles" in payload
        assert payload["roles"]["foundation"]["passed"] == 1

    def test_role_on_individual_results(self):
        """CheckResult.to_dict() now carries role — verify it survives."""
        summary = _mk_summary(
            [_mk_result("x", CheckStatus.FAILED, role="diagnostic")]
        )
        report = RunReport.from_summary(summary, "", write_logs=False)
        payload = json.loads(JsonAdapter.render(report))
        assert payload["results"][0]["role"] == "diagnostic"


# ─── ConsoleAdapter ──────────────────────────────────────────────────────


class TestConsoleAdapter:
    def test_success_banner(self, capsys):
        summary = _mk_summary([_mk_result("x", CheckStatus.PASSED, role="foundation")])
        report = RunReport.from_summary(summary, "", write_logs=False)
        ConsoleAdapter().render(report)

        out = capsys.readouterr().out
        assert "NO SLOP DETECTED" in out
        assert "1 checks passed" in out

    def test_failure_banner_with_role_badge(self, capsys, mixed_summary):
        report = RunReport.from_summary(mixed_summary, "", write_logs=False)
        ConsoleAdapter().render(report)

        out = capsys.readouterr().out
        assert "SLOP DETECTED" in out
        # Role badges appear on failure lines.
        assert "[foundation]" in out
        assert "[diagnostic]" in out

    def test_rerun_hint_per_failure(self, capsys, mixed_summary):
        report = RunReport.from_summary(mixed_summary, "", write_logs=False)
        ConsoleAdapter().render(report)

        out = capsys.readouterr().out
        assert "sm swab -g types --verbose" in out
        assert "sm swab -g sprawl --verbose" in out

    def test_fix_suggestion_rendered(self, capsys):
        summary = _mk_summary(
            [
                _mk_result(
                    "x",
                    CheckStatus.FAILED,
                    role="diagnostic",
                    fix_suggestion="Move Foo (200 lines) to its own file",
                )
            ]
        )
        report = RunReport.from_summary(summary, "", write_logs=False)
        ConsoleAdapter().render(report)

        out = capsys.readouterr().out
        assert "💡 Move Foo (200 lines) to its own file" in out

    def test_role_line_on_success(self, capsys):
        summary = _mk_summary(
            [
                _mk_result("a", CheckStatus.PASSED, role="foundation"),
                _mk_result("b", CheckStatus.PASSED, role="foundation"),
                _mk_result("c", CheckStatus.PASSED, role="diagnostic"),
            ]
        )
        report = RunReport.from_summary(summary, "", write_logs=False)
        ConsoleAdapter().render(report)

        out = capsys.readouterr().out
        assert "foundation: 2/2" in out
        assert "diagnostic: 1/1" in out

    def test_role_line_suppressed_when_all_unknown(self, capsys):
        """Legacy results without role don't print a useless 'unknown: n/n'."""
        summary = _mk_summary([_mk_result("x", CheckStatus.PASSED, role=None)])
        report = RunReport.from_summary(summary, "", write_logs=False)
        ConsoleAdapter().render(report)

        out = capsys.readouterr().out
        assert "unknown" not in out
        assert "foundation" not in out


# ─── SarifAdapter ────────────────────────────────────────────────────────


class TestSarifAdapter:
    def test_delegates_to_sarif_reporter(self, tmp_path):
        """SarifAdapter is a thin wrapper — verify the handoff."""
        summary = _mk_summary(
            [
                _mk_result(
                    "myopia:code-sprawl",
                    CheckStatus.FAILED,
                    role="diagnostic",
                    findings=[
                        Finding(
                            message="too big",
                            file="src/big.py",
                            line=1,
                        )
                    ],
                )
            ]
        )
        report = RunReport.from_summary(summary, str(tmp_path), write_logs=False)
        payload = json.loads(SarifAdapter.render(report))

        assert payload["version"] == "2.1.0"
        assert len(payload["runs"]) == 1
        results = payload["runs"][0]["results"]
        assert len(results) == 1
        assert results[0]["ruleId"] == "myopia:code-sprawl"

    def test_role_tagged_on_rule(self, tmp_path):
        """CheckRole flows through to SARIF rule properties."""
        summary = _mk_summary(
            [
                _mk_result(
                    "x",
                    CheckStatus.FAILED,
                    role="diagnostic",
                    findings=[Finding(message="m")],
                )
            ]
        )
        report = RunReport.from_summary(summary, str(tmp_path), write_logs=False)
        payload = json.loads(SarifAdapter.render(report))

        rules = payload["runs"][0]["tool"]["driver"]["rules"]
        assert rules[0]["properties"]["role"] == "diagnostic"

    def test_fix_strategy_tagged_on_result(self, tmp_path):
        """Finding.fix_strategy flows through to SARIF result properties."""
        summary = _mk_summary(
            [
                _mk_result(
                    "x",
                    CheckStatus.FAILED,
                    role="diagnostic",
                    findings=[
                        Finding(
                            message="bad yaml",
                            fix_strategy="Replace yaml.load() with yaml.safe_load()",
                        )
                    ],
                )
            ]
        )
        report = RunReport.from_summary(summary, str(tmp_path), write_logs=False)
        payload = json.loads(SarifAdapter.render(report))

        results = payload["runs"][0]["results"]
        assert (
            results[0]["properties"]["fix_strategy"]
            == "Replace yaml.load() with yaml.safe_load()"
        )


# ─── Finding.fix_strategy ────────────────────────────────────────────────


class TestFindingFixStrategy:
    def test_str_without_fix_strategy_unchanged(self):
        """Backward compat — existing gates see no console output change."""
        f = Finding(message="bad", file="src/x.py", line=42)
        assert str(f) == "src/x.py:42: bad"

    def test_str_with_fix_strategy_adds_second_line(self):
        f = Finding(
            message="12 uncovered lines: 42-53",
            file="src/handler.py",
            line=42,
            fix_strategy="Lines 42-53 are an except block — test with invalid input",
        )
        rendered = str(f)
        lines = rendered.split("\n")
        assert len(lines) == 2
        assert lines[0] == "src/handler.py:42: 12 uncovered lines: 42-53"
        assert lines[1] == "  → fix: Lines 42-53 are an except block — test with invalid input"

    def test_to_dict_omits_none_fix_strategy(self):
        f = Finding(message="x")
        assert "fix_strategy" not in f.to_dict()

    def test_to_dict_includes_fix_strategy_when_set(self):
        f = Finding(message="x", fix_strategy="do the thing")
        assert f.to_dict()["fix_strategy"] == "do the thing"

    def test_finding_is_still_frozen(self):
        f = Finding(message="x", fix_strategy="y")
        with pytest.raises(Exception):  # noqa: B017 — FrozenInstanceError or AttributeError
            f.fix_strategy = "z"  # type: ignore[misc]


# ─── CheckRole integration ───────────────────────────────────────────────


class TestCheckRoleIntegration:
    def test_check_result_to_dict_includes_role(self):
        r = _mk_result("x", CheckStatus.FAILED, role="foundation")
        d = r.to_dict()
        assert d["role"] == "foundation"

    def test_check_result_to_dict_omits_none_role(self):
        r = _mk_result("x", CheckStatus.FAILED, role=None)
        assert "role" not in r.to_dict()

    def test_base_check_default_is_diagnostic(self):
        """Checks prove themselves FOUNDATION; DIAGNOSTIC is the default."""
        from slopmop.checks.base import BaseCheck, CheckRole

        assert BaseCheck.role is CheckRole.DIAGNOSTIC

    def test_foundation_checks_have_correct_role(self):
        """Spot-check the classification landed correctly."""
        from slopmop.checks.base import CheckRole
        from slopmop.checks.python.lint_format import PythonLintFormatCheck
        from slopmop.checks.quality.loc_lock import LocLockCheck

        assert PythonLintFormatCheck.role is CheckRole.FOUNDATION
        assert LocLockCheck.role is CheckRole.DIAGNOSTIC  # novel, not wrapping a tool
