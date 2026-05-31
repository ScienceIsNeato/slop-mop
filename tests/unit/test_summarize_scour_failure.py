"""Tests for CI scour failure summary formatting."""

from __future__ import annotations

import json

from scripts.summarize_scour_failure import (
    _classify_failed_gates,
    _read_actionable_results,
)


def test_scour_only_gate_summary_includes_error_detail(capsys):
    classification, swab_failed, scour_only_failed = _classify_failed_gates(
        [
            {
                "name": "myopia:just-this-once.py",
                "status": "failed",
                "error": "Changed files have <80% coverage",
            }
        ]
    )

    out = capsys.readouterr().out

    assert classification == "SCOUR-only failures"
    assert swab_failed == []
    assert scour_only_failed == [
        "myopia:just-this-once.py — Changed files have <80% coverage"
    ]
    assert (
        "::error::SCOUR-only failed gates: "
        "myopia:just-this-once.py — Changed files have <80% coverage"
    ) in out


def test_failure_summary_falls_back_to_status_detail(capsys):
    _classification, _swab_failed, scour_only_failed = _classify_failed_gates(
        [
            {
                "name": "myopia:just-this-once.py",
                "status": "failed",
                "status_detail": "Diff coverage below threshold",
            }
        ]
    )

    assert scour_only_failed == [
        "myopia:just-this-once.py — Diff coverage below threshold"
    ]


def test_read_actionable_results_unwraps_v3_envelope(tmp_path):
    report = tmp_path / "slopmop-results.json"
    report.write_text(
        json.dumps(
            {
                "schema": "slopmop/v3",
                "command": "scour",
                "status": "fail",
                "exit_code": 1,
                "data": {
                    "results": [
                        {
                            "name": "myopia:just-this-once.py",
                            "status": "failed",
                            "error": "Changed files have <80% coverage",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    actionable = _read_actionable_results(str(report))

    assert actionable == [
        {
            "name": "myopia:just-this-once.py",
            "status": "failed",
            "error": "Changed files have <80% coverage",
        }
    ]
