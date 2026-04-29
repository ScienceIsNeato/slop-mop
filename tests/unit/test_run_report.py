"""Tests for RunReport and output adapters.

RunReport is the canonical enriched intermediate between ExecutionSummary
and output formats.  These tests verify (a) derivation correctness and
(b) that adapters are pure transforms of RunReport state — no recomputation,
no side effects beyond the contract.
"""

import json
from types import SimpleNamespace
from typing import Optional

import pytest

from slopmop.core.result import (
    CheckResult,
    CheckStatus,
    ExecutionSummary,
    Finding,
    SkipReason,
)
from slopmop.reporting.adapters import (
    ConsoleAdapter,
    JsonAdapter,
    PorcelainAdapter,
    SarifAdapter,
    _role_badge,
)
from slopmop.reporting.report import JSON_SCHEMA_VERSION, RunReport

# ─── fixtures ────────────────────────────────────────────────────────────


def _result(
    name: str,
    status: CheckStatus,
    *,
    role: str = "diagnostic",
    error: str = "",
    output: str = "",
    fix_suggestion: str = "",
    why_it_matters: str = "",
    skip_reason: Optional[SkipReason] = None,
    findings: Optional[list[Finding]] = None,
) -> CheckResult:
    return CheckResult(
        name=name,
        status=status,
        duration=0.1,
        error=error or None,
        output=output,
        fix_suggestion=fix_suggestion or None,
        role=role,
        why_it_matters=why_it_matters or None,
        skip_reason=skip_reason,
        findings=findings or [],
    )


def _summary(results: list[CheckResult]) -> ExecutionSummary:
    return ExecutionSummary.from_results(results, duration=1.5)


# ─── RunReport derivation ────────────────────────────────────────────────


class TestRunReportCategorisation:
    def test_buckets_by_status(self) -> None:
        summary = _summary(
            [
                _result("p1", CheckStatus.PASSED),
                _result("f1", CheckStatus.FAILED),
                _result("w1", CheckStatus.WARNED),
                _result("e1", CheckStatus.ERROR),
                _result("s1", CheckStatus.SKIPPED, skip_reason=SkipReason.FAIL_FAST),
                _result(
                    "na",
                    CheckStatus.NOT_APPLICABLE,
                    skip_reason=SkipReason.NOT_APPLICABLE,
                ),
            ]
        )
        report = RunReport.from_summary(summary)
        assert [r.name for r in report.passed] == ["p1"]
        assert [r.name for r in report.failed] == ["f1"]
        assert [r.name for r in report.warned] == ["w1"]
        assert [r.name for r in report.errored] == ["e1"]
        # Operational skips (fail-fast, missing deps) stay separate
        # from applicability filtering — the console summary shows
        # "skipped" counts for things that *should* have run.
        assert [r.name for r in report.skipped] == ["s1"]
        assert [r.name for r in report.not_applicable] == ["na"]

    def test_preserves_order(self) -> None:
        summary = _summary(
            [
                _result("f1", CheckStatus.FAILED),
                _result("p1", CheckStatus.PASSED),
                _result("f2", CheckStatus.FAILED),
                _result("f3", CheckStatus.FAILED),
            ]
        )
        report = RunReport.from_summary(summary)
        assert [r.name for r in report.failed] == ["f1", "f2", "f3"]

    def test_can_sort_failures_by_remediation_order_for_display(self) -> None:
        registry = SimpleNamespace(
            remediation_sort_key_for_name=lambda name: {
                "overconfidence:high": (0, 10, name),
                "overconfidence:low": (0, 20, name),
            }.get(name)
        )

        summary = _summary(
            [
                _result("overconfidence:low", CheckStatus.FAILED),
                _result("overconfidence:high", CheckStatus.FAILED),
            ]
        )
        report = RunReport.from_summary(
            summary,
            level="swab",
            registry=registry,
            sort_actionable_by_remediation_order=True,
        )

        assert [r.name for r in report.failed] == [
            "overconfidence:high",
            "overconfidence:low",
        ]
        assert report.verify_command == "sm swab -g overconfidence:high"

    def test_verify_command_targets_first_failure(self) -> None:
        summary = _summary(
            [
                _result("p1", CheckStatus.PASSED),
                _result("f1", CheckStatus.FAILED),
                _result("f2", CheckStatus.FAILED),
            ]
        )
        report = RunReport.from_summary(summary, level="swab")
        assert report.verify_command == "sm swab -g f1"

    def test_verify_command_falls_back_to_error(self) -> None:
        summary = _summary(
            [
                _result("p1", CheckStatus.PASSED),
                _result("e1", CheckStatus.ERROR),
            ]
        )
        report = RunReport.from_summary(summary, level="scour")
        assert report.verify_command == "sm scour -g e1"

    def test_verify_command_none_when_all_passed(self) -> None:
        summary = _summary([_result("p1", CheckStatus.PASSED)])
        report = RunReport.from_summary(summary)
        assert report.verify_command is None

    def test_actionable_is_failed_plus_warned_plus_errored(self) -> None:
        summary = _summary(
            [
                _result("p", CheckStatus.PASSED),
                _result("f", CheckStatus.FAILED),
                _result("w", CheckStatus.WARNED),
                _result("e", CheckStatus.ERROR),
                _result("s", CheckStatus.SKIPPED),
            ]
        )
        report = RunReport.from_summary(summary)
        assert [r.name for r in report.actionable] == ["f", "w", "e"]


class TestRunReportRoleCounts:
    def test_counts_passed_by_role(self) -> None:
        summary = _summary(
            [
                _result("a", CheckStatus.PASSED, role="foundation"),
                _result("b", CheckStatus.PASSED, role="foundation"),
                _result("c", CheckStatus.PASSED, role="diagnostic"),
                _result("d", CheckStatus.FAILED, role="foundation"),
            ]
        )
        report = RunReport.from_summary(summary)
        counts = report.role_counts()
        assert counts["foundation"] == 2
        assert counts["diagnostic"] == 1

    def test_unknown_role_buckets_as_diagnostic(self) -> None:
        # Matches BaseCheck default — unknown is treated as diagnostic.
        r = CheckResult(name="x", status=CheckStatus.PASSED, duration=0.1, role=None)
        summary = _summary([r])
        report = RunReport.from_summary(summary)
        assert report.role_counts()["diagnostic"] == 1


class TestRunReportLogs:
    def test_write_logs_creates_files_for_failures(self, tmp_path) -> None:
        summary = _summary(
            [
                _result(
                    "myopia:code-sprawl",
                    CheckStatus.FAILED,
                    output="too big",
                    error="1 file over limit",
                ),
                _result("p", CheckStatus.PASSED),
            ]
        )
        report = RunReport.from_summary(summary, project_root=str(tmp_path))
        logs = report.write_logs()
        assert "myopia:code-sprawl" in logs
        log_file = tmp_path / ".slopmop" / "logs" / "myopia_code-sprawl.log"
        assert log_file.exists()
        content = log_file.read_text()
        assert "Check: myopia:code-sprawl" in content
        assert "too big" in content

    def test_write_logs_creates_files_for_warnings(self, tmp_path) -> None:
        summary = _summary(
            [
                _result(
                    "python:missing-venv",
                    CheckStatus.WARNED,
                    output="warn details",
                    error="warning",
                )
            ]
        )
        report = RunReport.from_summary(summary, project_root=str(tmp_path))
        logs = report.write_logs()
        assert "python:missing-venv" in logs
        log_file = tmp_path / ".slopmop" / "logs" / "python_missing-venv.log"
        assert log_file.exists()
        assert "warn details" in log_file.read_text()

    def test_write_logs_no_op_without_project_root(self) -> None:
        summary = _summary([_result("f", CheckStatus.FAILED)])
        report = RunReport.from_summary(summary, project_root=None)
        assert report.write_logs() == {}

    def test_write_logs_idempotent(self, tmp_path) -> None:
        summary = _summary([_result("f", CheckStatus.FAILED, output="x")])
        report = RunReport.from_summary(summary, project_root=str(tmp_path))
        first = dict(report.write_logs())
        second = dict(report.write_logs())
        assert first == second


# ─── JsonAdapter ─────────────────────────────────────────────────────────


class TestJsonAdapter:
    def test_schema_version_present(self) -> None:
        summary = _summary([_result("p", CheckStatus.PASSED)])
        report = RunReport.from_summary(summary)
        out = JsonAdapter.render(report)
        assert out["schema"] == JSON_SCHEMA_VERSION

    def test_level_present_when_set(self) -> None:
        summary = _summary([_result("p", CheckStatus.PASSED)])
        report = RunReport.from_summary(summary, level="swab")
        out = JsonAdapter.render(report)
        assert out["level"] == "swab"

    def test_level_absent_when_unset(self) -> None:
        summary = _summary([_result("p", CheckStatus.PASSED)])
        report = RunReport.from_summary(summary)
        out = JsonAdapter.render(report)
        assert "level" not in out

    def test_next_steps_point_to_log_then_verify(self, tmp_path) -> None:
        summary = _summary([_result("f", CheckStatus.FAILED, output="boom")])
        report = RunReport.from_summary(
            summary, level="swab", project_root=str(tmp_path)
        )
        report.write_logs()
        out = JsonAdapter.render(report)
        assert out["next_steps"] == [
            "Inspect failure details in .slopmop/logs/f.log",
            "After fixing, rerun sm swab -g f",
        ]

    def test_first_to_fix_includes_log_file_and_verify_command(self, tmp_path) -> None:
        summary = _summary([_result("f", CheckStatus.FAILED, output="boom")])
        report = RunReport.from_summary(
            summary, level="swab", project_root=str(tmp_path)
        )
        report.write_logs()
        out = JsonAdapter.render(report)
        assert out["first_to_fix"] == {
            "gate": "f",
            "log_file": ".slopmop/logs/f.log",
            "verify_command": "sm swab -g f",
        }

    def test_results_follow_report_actionable_order(self) -> None:
        summary = _summary(
            [
                _result("f2", CheckStatus.FAILED),
                _result("w1", CheckStatus.WARNED),
                _result("f1", CheckStatus.FAILED),
            ]
        )
        report = RunReport.from_summary(summary)
        report.failed = [report.failed[1], report.failed[0]]
        out = JsonAdapter.render(report)
        results = out["results"]
        assert isinstance(results, list)
        assert [row["name"] for row in results] == ["f1", "f2", "w1"]

    def test_next_steps_absent_when_all_passed(self) -> None:
        summary = _summary([_result("p", CheckStatus.PASSED)])
        report = RunReport.from_summary(summary)
        out = JsonAdapter.render(report)
        assert "next_steps" not in out

    def test_log_files_attached_to_results(self, tmp_path) -> None:
        summary = _summary([_result("f", CheckStatus.FAILED, output="x")])
        report = RunReport.from_summary(summary, project_root=str(tmp_path))
        report.write_logs()
        out = JsonAdapter.render(report)
        results = out["results"]
        assert isinstance(results, list)
        assert results[0]["log_file"].startswith(".slopmop/logs/")

    def test_json_serialisable(self) -> None:
        summary = _summary(
            [
                _result(
                    "f",
                    CheckStatus.FAILED,
                    findings=[
                        Finding(
                            message="bad",
                            file="src/x.py",
                            line=10,
                            fix_strategy="Replace foo() with bar()",
                        )
                    ],
                )
            ]
        )
        report = RunReport.from_summary(summary)
        out = JsonAdapter.render(report)
        # Must survive round-trip through json.dumps
        payload = json.dumps(out)
        parsed = json.loads(payload)
        assert parsed["schema"] == JSON_SCHEMA_VERSION

    def test_role_appears_in_results(self) -> None:
        summary = _summary([_result("f", CheckStatus.FAILED, role="foundation")])
        report = RunReport.from_summary(summary)
        out = JsonAdapter.render(report)
        assert out["results"][0]["role"] == "foundation"

    def test_why_it_matters_appears_in_results(self) -> None:
        summary = _summary(
            [
                _result(
                    "f",
                    CheckStatus.FAILED,
                    why_it_matters="Static typing catches interface bugs early.",
                )
            ]
        )
        report = RunReport.from_summary(summary)
        out = JsonAdapter.render(report)
        assert out["results"][0]["why_it_matters"] == (
            "Static typing catches interface bugs early."
        )

    def test_runtime_warning_present_for_time_budget_skips(self) -> None:
        summary = _summary(
            [
                _result("p", CheckStatus.PASSED),
                _result("s", CheckStatus.SKIPPED, skip_reason=SkipReason.TIME_BUDGET),
            ]
        )
        report = RunReport.from_summary(summary, level="swab")
        out = JsonAdapter.render(report)
        warnings = out.get("runtime_warnings")
        assert isinstance(warnings, list)
        assert warnings[0]["code"] == "swabbing_timeout_budget_skipped"
        assert warnings[0]["skipped_timed_checks"] == 1
        assert warnings[0]["suggested_command"] == "sm swab --swabbing-timeout 0"

    def test_runtime_warning_absent_without_time_budget_skips(self) -> None:
        summary = _summary([_result("p", CheckStatus.PASSED)])
        report = RunReport.from_summary(summary, level="swab")
        out = JsonAdapter.render(report)
        assert "runtime_warnings" not in out

    def test_cache_block_and_warning_present_for_cached_results(self) -> None:
        summary = _summary(
            [
                CheckResult(
                    name="p",
                    status=CheckStatus.PASSED,
                    duration=0.1,
                    cached=True,
                    cache_commit="abc1234",
                    cache_timestamp="2026-03-09T12:00:00+00:00",
                )
            ]
        )
        report = RunReport.from_summary(summary, level="swab")
        out = JsonAdapter.render(report)
        assert out["cache"]["cached_results"] == 1
        assert out["cache"]["refresh_command"] == "sm swab --no-cache"
        warnings = out.get("runtime_warnings")
        assert isinstance(warnings, list)
        assert any(w["code"] == "cached_results_present" for w in warnings)

    def test_cache_block_counts_skipped_results_in_denominator(self) -> None:
        summary = _summary(
            [
                CheckResult(
                    name="s",
                    status=CheckStatus.SKIPPED,
                    duration=0.1,
                    cached=True,
                )
            ]
        )
        report = RunReport.from_summary(summary, level="swab")
        out = JsonAdapter.render(report)
        assert out["cache"]["cached_results"] == 1
        assert out["cache"]["total_ran"] == 1

    def test_cache_block_preserves_mixed_provenance(self) -> None:
        summary = _summary(
            [
                CheckResult(
                    name="a",
                    status=CheckStatus.PASSED,
                    duration=0.1,
                    cached=True,
                    cache_commit="abc1234",
                    cache_timestamp="2026-03-09T12:00:00+00:00",
                ),
                CheckResult(
                    name="b",
                    status=CheckStatus.SKIPPED,
                    duration=0.1,
                    cached=True,
                    cache_commit="def5678",
                    cache_timestamp="2026-03-10T12:00:00+00:00",
                ),
            ]
        )
        report = RunReport.from_summary(summary, level="swab")
        out = JsonAdapter.render(report)
        assert out["cache"]["source_commits"] == ["abc1234", "def5678"]
        assert out["cache"]["oldest_source_timestamp"] == "2026-03-09T12:00:00+00:00"
        assert out["cache"]["newest_source_timestamp"] == "2026-03-10T12:00:00+00:00"
        assert "source_commit" not in out["cache"]
        assert "source_timestamp" not in out["cache"]


# ─── SarifAdapter ────────────────────────────────────────────────────────


class TestSarifAdapter:
    def test_produces_valid_envelope(self) -> None:
        summary = _summary([_result("p", CheckStatus.PASSED)])
        report = RunReport.from_summary(summary)
        doc = SarifAdapter.render(report)
        assert doc["version"] == "2.1.0"
        assert "runs" in doc
        assert len(doc["runs"]) == 1

    def test_fix_strategy_in_result_properties(self) -> None:
        summary = _summary(
            [
                _result(
                    "f",
                    CheckStatus.FAILED,
                    findings=[
                        Finding(
                            message="yaml.load without Loader",
                            file="src/x.py",
                            line=5,
                            rule_id="B506",
                            fix_strategy="Replace yaml.load(data) with yaml.safe_load(data)",
                        )
                    ],
                )
            ]
        )
        report = RunReport.from_summary(summary)
        doc = SarifAdapter.render(report)
        results = doc["runs"][0]["results"]
        assert len(results) == 1
        assert results[0]["properties"]["fix_strategy"] == (
            "Replace yaml.load(data) with yaml.safe_load(data)"
        )

    def test_role_in_rule_properties(self) -> None:
        summary = _summary(
            [
                _result(
                    "f",
                    CheckStatus.FAILED,
                    role="foundation",
                    findings=[Finding(message="x", file="a.py", line=1)],
                )
            ]
        )
        report = RunReport.from_summary(summary)
        doc = SarifAdapter.render(report)
        rules = doc["runs"][0]["tool"]["driver"]["rules"]
        assert len(rules) == 1
        assert rules[0]["properties"]["role"] == "foundation"

    def test_no_properties_bag_when_empty(self) -> None:
        # Finding with no fix_strategy → result has no properties key.
        r = CheckResult(
            name="f",
            status=CheckStatus.FAILED,
            duration=0.1,
            role=None,
            findings=[Finding(message="x", file="a.py", line=1)],
        )
        summary = _summary([r])
        report = RunReport.from_summary(summary)
        doc = SarifAdapter.render(report)
        assert "properties" not in doc["runs"][0]["results"][0]
        assert "properties" not in doc["runs"][0]["tool"]["driver"]["rules"][0]


# ─── ConsoleAdapter ──────────────────────────────────────────────────────


class TestConsoleAdapter:
    def test_success_path_prints_no_slop_banner(self, capsys) -> None:
        summary = _summary(
            [
                _result("a", CheckStatus.PASSED, role="foundation"),
                _result("b", CheckStatus.PASSED, role="diagnostic"),
            ]
        )
        report = RunReport.from_summary(summary)
        ConsoleAdapter(report).render()
        out = capsys.readouterr().out
        assert "NO SLOP DETECTED" in out
        assert "2 checks passed" in out
        # role breakdown shown when both tiers present
        assert "foundation" in out
        assert "diagnostic" in out

    def test_failure_path_shows_gate_detail(self, capsys, tmp_path) -> None:
        summary = _summary(
            [
                _result(
                    "myopia:code-sprawl",
                    CheckStatus.FAILED,
                    role="diagnostic",
                    error="1 file over limit",
                    output="src/big.py: 1200 lines",
                    fix_suggestion="Move BigClass to its own file",
                ),
            ]
        )
        report = RunReport.from_summary(
            summary, level="swab", project_root=str(tmp_path)
        )
        report.write_logs()
        ConsoleAdapter(report).render()
        out = capsys.readouterr().out
        assert "SLOP DETECTED" in out
        assert "Fix First: myopia:code-sprawl" not in out
        assert "after fixing: sm swab -g myopia:code-sprawl" in out
        assert "myopia:code-sprawl" in out
        assert "Move BigClass" in out
        assert "📄 full details: .slopmop/logs/myopia_code-sprawl.log" in out

    def test_role_badge_in_failure_header(self, capsys) -> None:
        summary = _summary([_result("f", CheckStatus.FAILED, role="foundation")])
        report = RunReport.from_summary(summary)
        ConsoleAdapter(report).render()
        out = capsys.readouterr().out
        # foundation badge is wrench emoji
        assert "🔧" in out

    def test_fix_strategy_renders_in_finding_output(self, capsys) -> None:
        # When findings carry fix_strategy, Finding.__str__ includes it
        # as a "→ fix:" line.  The auto-output rail in _create_result
        # joins findings; this test simulates a gate that returned
        # findings-only (no free-form output).
        f = Finding(
            message="bad thing",
            file="src/x.py",
            line=5,
            fix_strategy="Do the thing",
        )
        summary = _summary([_result("g", CheckStatus.FAILED, output=str(f))])
        report = RunReport.from_summary(summary)
        ConsoleAdapter(report).render()
        out = capsys.readouterr().out
        assert "→ fix: Do the thing" in out

    def test_structured_guidance_renders_when_present(self, capsys, tmp_path) -> None:
        summary = _summary(
            [
                _result(
                    "overconfidence:type-blindness.py",
                    CheckStatus.FAILED,
                    why_it_matters="Unknown types force readers to guess about data shape.",
                    fix_suggestion="Fallback gate-level guidance",
                    findings=[
                        Finding(
                            message='Type of "x" is "Unknown"',
                            file="src/app.py",
                            line=11,
                            fix_strategy="Annotate x with its concrete type.",
                        )
                    ],
                )
            ]
        )
        report = RunReport.from_summary(
            summary, level="swab", project_root=str(tmp_path)
        )
        report.write_logs()
        ConsoleAdapter(report).render()
        out = capsys.readouterr().out
        assert "WHAT'S BROKEN:" in out
        assert "WHY IT MATTERS:" not in out
        assert "EXACTLY WHAT TO DO:" not in out
        assert "FULL DETAILS:" not in out
        assert "AFTER FIXING: sm swab -g overconfidence:type-blindness.py" in out

    def test_success_path_warns_on_time_budget_skips(self, capsys) -> None:
        summary = _summary(
            [
                _result("a", CheckStatus.PASSED, role="foundation"),
                _result("b", CheckStatus.SKIPPED, skip_reason=SkipReason.TIME_BUDGET),
            ]
        )
        report = RunReport.from_summary(summary)
        ConsoleAdapter(report).render()
        out = capsys.readouterr().out
        assert "Swabbing-timeout budget skipped 1 timed check(s)" in out
        assert "sm swab --swabbing-timeout 0" in out

    def test_failure_path_warns_on_time_budget_skips(self, capsys) -> None:
        summary = _summary(
            [
                _result("f", CheckStatus.FAILED),
                _result("s", CheckStatus.SKIPPED, skip_reason=SkipReason.TIME_BUDGET),
            ]
        )
        report = RunReport.from_summary(summary)
        ConsoleAdapter(report).render()
        out = capsys.readouterr().out
        assert "Swabbing-timeout budget skipped 1 timed check(s)" in out

    def test_cache_hint_renders_when_cached_results_present(self, capsys) -> None:
        summary = _summary(
            [
                CheckResult(
                    name="a",
                    status=CheckStatus.PASSED,
                    duration=0.1,
                    cached=True,
                    cache_commit="abc1234",
                    cache_timestamp="2026-03-09T12:00:00+00:00",
                )
            ]
        )
        report = RunReport.from_summary(summary, level="swab")
        ConsoleAdapter(report).render()
        out = capsys.readouterr().out
        assert "from cache" in out
        assert "sm swab --no-cache" in out


class TestPorcelainAdapter:
    def test_success_is_single_summary_line(self) -> None:
        summary = _summary(
            [
                _result("a", CheckStatus.PASSED),
                _result(
                    "n",
                    CheckStatus.NOT_APPLICABLE,
                    skip_reason=SkipReason.NOT_APPLICABLE,
                ),
            ]
        )
        report = RunReport.from_summary(summary, level="swab")

        assert PorcelainAdapter.render(report) == "sm swab: 0 fail · 1 pass · 1 n/a"

    def test_failure_lists_actionable_detail_and_next_command(self) -> None:
        summary = _summary(
            [
                _result("p", CheckStatus.PASSED),
                _result(
                    "laziness:code-sprawl",
                    CheckStatus.FAILED,
                    output="tests/big.py - too large",
                    fix_suggestion="Split the file by concept",
                ),
            ]
        )
        report = RunReport.from_summary(summary, level="swab")

        out = PorcelainAdapter.render(report)

        assert "sm swab: 1 fail · 1 pass" in out
        assert "laziness:code-sprawl" in out
        assert "tests/big.py - too large" in out
        assert "fix: Split the file by concept" in out
        assert "next: sm swab -g laziness:code-sprawl" in out


# ─── role badge helper ───────────────────────────────────────────────────


class TestRoleBadge:
    def test_known_roles_have_distinct_badges(self) -> None:
        found = _role_badge(_result("x", CheckStatus.FAILED, role="foundation"))
        diag = _role_badge(_result("x", CheckStatus.FAILED, role="diagnostic"))
        assert found
        assert diag
        assert found != diag

    def test_unknown_role_empty_badge(self) -> None:
        r = CheckResult(name="x", status=CheckStatus.FAILED, duration=0.1, role=None)
        assert _role_badge(r) == ""


# ─── Finding fix_strategy ────────────────────────────────────────────────


class TestFindingFixStrategy:
    def test_fix_strategy_in_to_dict_when_set(self) -> None:
        f = Finding(message="x", fix_strategy="do y")
        d = f.to_dict()
        assert d["fix_strategy"] == "do y"

    def test_fix_strategy_absent_when_none(self) -> None:
        f = Finding(message="x")
        assert "fix_strategy" not in f.to_dict()

    def test_fix_strategy_in_str_as_second_line(self) -> None:
        f = Finding(message="problem", file="a.py", line=1, fix_strategy="solve it")
        s = str(f)
        lines = s.split("\n")
        assert len(lines) == 2
        assert lines[0] == "a.py:1: problem"
        assert "→ fix: solve it" in lines[1]

    def test_str_unchanged_when_fix_strategy_none(self) -> None:
        f = Finding(message="problem", file="a.py", line=1)
        assert str(f) == "a.py:1: problem"

    def test_frozen(self) -> None:
        f = Finding(message="x", fix_strategy="y")
        with pytest.raises(AttributeError):
            f.fix_strategy = "z"  # type: ignore[misc]


# ─── ConsoleAdapter additional coverage ──────────────────────────────────


class TestConsoleAdapterSkippedLine:
    """Tests for ConsoleAdapter._skipped_line() — skip reason bucketing."""

    def test_single_reason(self, capsys) -> None:
        summary = _summary(
            [
                _result("f", CheckStatus.FAILED),
                _result(
                    "s1",
                    CheckStatus.SKIPPED,
                    skip_reason=SkipReason.FAIL_FAST,
                ),
            ]
        )
        report = RunReport.from_summary(summary)
        adapter = ConsoleAdapter(report)
        line = adapter._skipped_line()
        assert "1 skipped" in line
        assert "ff" in line

    def test_mixed_reasons(self, capsys) -> None:
        summary = _summary(
            [
                _result("f", CheckStatus.FAILED),
                _result("s1", CheckStatus.SKIPPED, skip_reason=SkipReason.FAIL_FAST),
                _result(
                    "s2",
                    CheckStatus.SKIPPED,
                    skip_reason=SkipReason.NOT_APPLICABLE,
                ),
            ]
        )
        report = RunReport.from_summary(summary)
        adapter = ConsoleAdapter(report)
        line = adapter._skipped_line()
        assert "2 skipped" in line
        assert "ff" in line
        assert "n/a" in line

    def test_no_skip_reason_buckets_as_skip(self) -> None:
        summary = _summary(
            [
                _result("f", CheckStatus.FAILED),
                _result("s1", CheckStatus.SKIPPED),
            ]
        )
        report = RunReport.from_summary(summary)
        adapter = ConsoleAdapter(report)
        line = adapter._skipped_line()
        assert "skip" in line


class TestConsoleAdapterSingleRole:
    """Test success path with only one role tier present."""

    def test_single_role_omits_breakdown(self, capsys) -> None:
        summary = _summary(
            [
                _result("a", CheckStatus.PASSED, role="foundation"),
                _result("b", CheckStatus.PASSED, role="foundation"),
            ]
        )
        report = RunReport.from_summary(summary)
        ConsoleAdapter(report).render()
        out = capsys.readouterr().out
        assert "NO SLOP DETECTED" in out
        # Should NOT show role breakdown when only one role
        assert "diagnostic" not in out


class TestConsoleAdapterWarnings:
    """Test warning rendering including fix_suggestion."""

    def test_warning_with_fix_suggestion(self, capsys) -> None:
        summary = _summary(
            [
                _result(
                    "w",
                    CheckStatus.WARNED,
                    error="something off",
                    fix_suggestion="try this fix",
                ),
                _result("f", CheckStatus.FAILED, error="broken"),
            ]
        )
        report = RunReport.from_summary(summary, level="swab")
        ConsoleAdapter(report).render()
        out = capsys.readouterr().out
        assert "something off" in out
        assert "try this fix" in out

    def test_warning_renders_log_path_when_available(self, capsys, tmp_path) -> None:
        summary = _summary(
            [
                _result(
                    "w",
                    CheckStatus.WARNED,
                    error="something off",
                    output="warn body",
                ),
                _result("f", CheckStatus.FAILED, error="broken"),
            ]
        )
        report = RunReport.from_summary(
            summary, level="swab", project_root=str(tmp_path)
        )
        report.write_logs()
        ConsoleAdapter(report).render()
        out = capsys.readouterr().out
        assert "📄 full details: .slopmop/logs/w.log" in out

    def test_output_truncation_with_log_file(self, capsys) -> None:
        long_output = "\n".join(f"line {i}" for i in range(20))
        summary = _summary(
            [
                _result("g", CheckStatus.FAILED, error="big", output=long_output),
            ]
        )
        report = RunReport.from_summary(summary, level="swab")
        # Simulate log files being available
        report.log_files = {"g": "logs/g.log"}
        ConsoleAdapter(report).render()
        out = capsys.readouterr().out
        assert "line 0" in out
        assert "line 2" in out
        assert "line 3" not in out
        assert "more lines in log" in out
        assert "logs/g.log" in out

    def test_verbose_output_preview_shows_more_lines(self, capsys) -> None:
        long_output = "\n".join(f"line {i}" for i in range(20))
        summary = _summary(
            [
                _result("g", CheckStatus.FAILED, error="big", output=long_output),
            ]
        )
        report = RunReport.from_summary(summary, level="swab", verbose=True)
        report.log_files = {"g": "logs/g.log"}
        ConsoleAdapter(report).render()
        out = capsys.readouterr().out
        assert "line 0" in out
        assert "line 9" in out
        assert "line 10" not in out
        assert "more lines in log" in out
