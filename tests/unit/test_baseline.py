"""Tests for baseline snapshot generation and filtering."""

import json

from slopmop.baseline import (
    filter_summary_against_baseline,
    generate_baseline_snapshot,
    load_baseline_snapshot,
)
from slopmop.core.result import (
    CheckResult,
    CheckStatus,
    ExecutionSummary,
    Finding,
    FindingLevel,
)


class TestGenerateBaselineSnapshot:
    """Tests for baseline snapshot generation."""

    def test_prefers_newest_artifact(self, tmp_path):
        sm_dir = tmp_path / ".slopmop"
        sm_dir.mkdir()
        swab = sm_dir / "last_swab.json"
        scour = sm_dir / "last_scour.json"
        swab.write_text(json.dumps({"level": "swab", "results": []}))
        scour.write_text(json.dumps({"level": "scour", "results": []}))
        scour.touch()

        snapshot_path, source_path = generate_baseline_snapshot(tmp_path)

        assert snapshot_path.exists()
        assert source_path.name == "last_scour.json"


class TestFilterSummaryAgainstBaseline:
    """Tests for post-run baseline filtering."""

    def test_fully_matched_failure_becomes_warning(self, tmp_path):
        sm_dir = tmp_path / ".slopmop"
        sm_dir.mkdir()
        artifact = sm_dir / "last_swab.json"
        artifact.write_text(
            json.dumps(
                {
                    "level": "swab",
                    "results": [
                        {
                            "name": "myopia:string-duplication.py",
                            "status": "failed",
                            "duration": 0.1,
                            "findings": [
                                {
                                    "message": "duplicate string",
                                    "level": "warning",
                                    "file": "app.py",
                                    "line": 10,
                                    "rule_id": "dup-str",
                                }
                            ],
                        }
                    ],
                }
            )
        )
        generate_baseline_snapshot(tmp_path)
        snapshot = load_baseline_snapshot(tmp_path)
        assert snapshot is not None

        summary = ExecutionSummary.from_results(
            [
                CheckResult(
                    name="myopia:string-duplication.py",
                    status=CheckStatus.FAILED,
                    duration=0.1,
                    findings=[
                        Finding(
                            message="duplicate string",
                            level=FindingLevel.WARNING,
                            file="app.py",
                            line=10,
                            rule_id="dup-str",
                        )
                    ],
                )
            ],
            duration=0.1,
        )

        filtered = filter_summary_against_baseline(summary, snapshot)

        assert filtered.filtered_summary.failed == 0
        assert filtered.filtered_summary.warned == 1
        assert filtered.filtered_summary.all_passed is True

    def test_partially_matched_failure_keeps_only_new_findings(self, tmp_path):
        sm_dir = tmp_path / ".slopmop"
        sm_dir.mkdir()
        artifact = sm_dir / "last_swab.json"
        artifact.write_text(
            json.dumps(
                {
                    "level": "swab",
                    "results": [
                        {
                            "name": "overconfidence:type-blindness.py",
                            "status": "failed",
                            "duration": 0.1,
                            "findings": [
                                {
                                    "message": "known issue",
                                    "level": "error",
                                    "file": "app.py",
                                    "line": 5,
                                    "rule_id": "known",
                                }
                            ],
                        }
                    ],
                }
            )
        )
        generate_baseline_snapshot(tmp_path)
        snapshot = load_baseline_snapshot(tmp_path)
        assert snapshot is not None

        summary = ExecutionSummary.from_results(
            [
                CheckResult(
                    name="overconfidence:type-blindness.py",
                    status=CheckStatus.FAILED,
                    duration=0.1,
                    findings=[
                        Finding(
                            message="known issue",
                            level=FindingLevel.ERROR,
                            file="app.py",
                            line=5,
                            rule_id="known",
                        ),
                        Finding(
                            message="new issue",
                            level=FindingLevel.ERROR,
                            file="app.py",
                            line=8,
                            rule_id="new",
                        ),
                    ],
                )
            ],
            duration=0.1,
        )

        filtered = filter_summary_against_baseline(summary, snapshot)
        result = filtered.filtered_summary.results[0]

        assert filtered.filtered_summary.failed == 1
        assert len(result.findings) == 1
        assert result.findings[0].message == "new issue"
