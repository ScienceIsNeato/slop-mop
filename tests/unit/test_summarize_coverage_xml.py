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


def test_find_total_line_returns_none_for_missing_report(tmp_path: Path) -> None:
    assert _MODULE.find_total_line(tmp_path / "missing.txt") is None


def test_load_coverage_pct_rejects_missing_line_rate(tmp_path: Path) -> None:
    coverage_xml = tmp_path / "coverage.xml"
    coverage_xml.write_text("<coverage></coverage>", encoding="utf-8")

    try:
        _MODULE.load_coverage_pct(coverage_xml)
    except ValueError as exc:
        assert "missing line-rate" in str(exc)
    else:  # pragma: no cover - failure path for assertion clarity
        raise AssertionError("expected ValueError")


def test_load_coverage_pct_rejects_invalid_line_rate(tmp_path: Path) -> None:
    coverage_xml = tmp_path / "coverage.xml"
    coverage_xml.write_text('<coverage line-rate="0.9.9" />', encoding="utf-8")

    try:
        _MODULE.load_coverage_pct(coverage_xml)
    except ValueError as exc:
        assert "Invalid coverage line-rate" in str(exc)
    else:  # pragma: no cover - failure path for assertion clarity
        raise AssertionError("expected ValueError")


def test_build_summary_includes_total_line() -> None:
    summary = _MODULE.build_summary(96.0, "TOTAL     200      8    96%")

    assert "## Unit Test Coverage" in summary
    assert "- Total line coverage: 96.0%" in summary
    assert "`TOTAL     200      8    96%`" in summary


def test_build_summary_without_total_line() -> None:
    summary = _MODULE.build_summary(88.25, None)

    assert "88.2%" in summary
    assert "coverage.py summary" not in summary


def test_write_step_summary_noops_without_path() -> None:
    assert _MODULE.write_step_summary(None, "ignored") is None


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


def test_main_returns_error_for_bad_coverage_xml(tmp_path: Path, capsys) -> None:
    coverage_xml = tmp_path / "coverage.xml"
    coverage_xml.write_text("<coverage></coverage>", encoding="utf-8")

    result = _MODULE.main(["--xml", str(coverage_xml)])

    assert result == 1
    assert "missing line-rate" in capsys.readouterr().err
