"""Tests for scripts/summarize_coverage_xml.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "summarize_coverage_xml.py"
_SPEC = importlib.util.spec_from_file_location("summarize_coverage_xml", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_load_coverage_pct_reads_line_rate(tmp_path: Path) -> None:
    coverage_xml = tmp_path / "coverage.xml"
    coverage_xml.write_text(
        '<coverage line-rate="0.873" branch-rate="0.5"></coverage>',
        encoding="utf-8",
    )

    assert _MODULE.load_coverage_pct(coverage_xml) == 87.3


def test_find_total_line_reads_coverage_report(tmp_path: Path) -> None:
    report = tmp_path / "coverage-report.txt"
    report.write_text(
        "Name    Stmts   Miss  Cover\n"
        "---------------------------\n"
        "TOTAL     200      8    96%\n",
        encoding="utf-8",
    )

    assert _MODULE.find_total_line(report) == "TOTAL     200      8    96%"


def test_build_summary_includes_total_line() -> None:
    summary = _MODULE.build_summary(96.0, "TOTAL     200      8    96%")

    assert "## Unit Test Coverage" in summary
    assert "- Total line coverage: 96.0%" in summary
    assert "`TOTAL     200      8    96%`" in summary


def test_main_writes_step_summary(tmp_path: Path) -> None:
    coverage_xml = tmp_path / "coverage.xml"
    coverage_xml.write_text('<coverage line-rate="0.91"></coverage>', encoding="utf-8")
    summary_path = tmp_path / "summary.md"

    result = _MODULE.main(
        [
            "--xml",
            str(coverage_xml),
            "--step-summary-path",
            str(summary_path),
        ]
    )

    assert result == 0
    assert "91.0%" in summary_path.read_text(encoding="utf-8")
