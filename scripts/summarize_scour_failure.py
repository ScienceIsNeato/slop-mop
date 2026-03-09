#!/usr/bin/env python3
"""Summarize slopmop CI failures in a reviewer-friendly way.

Reads SARIF + JSON output from the same scour run and prints:
- top SARIF rule IDs
- swab-overlap failed gates
- scour-only failed gates
- detailed actionable gate lines
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from slopmop.reporting.rail import (
    filter_actionable_rows,
    format_actionable_line,
    normalize_actionable_row,
)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _swab_gate_names() -> set[str]:
    try:
        from slopmop.checks import ensure_checks_registered
        from slopmop.checks.base import GateLevel
        from slopmop.core.registry import get_registry

        ensure_checks_registered()
        return set(get_registry().get_gate_names_for_level(GateLevel.SWAB))
    except Exception as exc:
        print(
            "::warning::Could not compute swab gate set for classification: "
            f"{exc}"
        )
        return set()


def _write_step_summary(
    path: str | None,
    classification_line: str,
    swab_failed: list[str],
    scour_only_failed: list[str],
    top_rules_line: str,
    actionable_lines: list[str],
) -> None:
    if not path:
        return

    summary_lines = [
        "## slopmop scour failure summary",
        "",
    ]
    if classification_line:
        summary_lines.append(f"- Classification: {classification_line}")
    if swab_failed:
        summary_lines.append(f"- SWAB-overlap failed gates: {', '.join(swab_failed)}")
    if scour_only_failed:
        summary_lines.append(
            f"- SCOUR-only failed gates: {', '.join(scour_only_failed)}"
        )
    if top_rules_line:
        summary_lines.append("")
        summary_lines.append("### Top SARIF rules")
        summary_lines.append(top_rules_line)
    if actionable_lines:
        summary_lines.append("")
        summary_lines.append("### Actionable gate details")
        summary_lines.extend(actionable_lines)
    summary_lines.append("")
    summary_lines.append(
        "See Security > Code scanning (category `slopmop`) and artifact `slopmop-results` for full payloads."
    )

    Path(path).write_text("\n".join(summary_lines) + "\n", encoding="utf-8")


def _read_sarif(sarif_path: str) -> tuple[list[dict[str, Any]], str]:
    sarif_doc = _load_json(Path(sarif_path))
    if sarif_doc is None:
        print("::error::slopmop scour failed - SARIF missing or unreadable")
        return [], "SARIF missing or unreadable"

    runs = sarif_doc.get("runs") or []
    sarif_results = (runs[0].get("results") or []) if runs else []
    if not sarif_results:
        print("::error::slopmop scour failed, but SARIF has zero results")
        return [], "SARIF had zero results"

    counts = Counter(r.get("ruleId", "unknown") for r in sarif_results)
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
    top_rules_line = ", ".join(f"{rule} ({n})" for rule, n in top)
    print(f"::error::Top SARIF rules: {top_rules_line}")
    return sarif_results, top_rules_line


def _read_actionable_results(json_path: str) -> list[dict[str, Any]]:
    json_doc = _load_json(Path(json_path))
    if json_doc is None:
        print(
            "::warning::JSON report missing/unreadable; cannot classify "
            "scour-only vs swab-overlap failures"
        )
        print("::notice::See Code scanning results / slopmop for detailed findings.")
        return []

    raw_results = json_doc.get("results") or []
    actionable = [
        r for r in filter_actionable_rows(raw_results) if isinstance(r, dict)
    ]
    if not actionable:
        print("::warning::No actionable results found in JSON report")
        return []

    status_order = {"error": 0, "failed": 1, "warned": 2}
    actionable.sort(
        key=lambda r: (status_order.get(str(r.get("status")), 9), str(r.get("name", "")))
    )
    return actionable


def _classify_failed_gates(
    actionable: list[dict[str, Any]],
) -> tuple[str, list[str], list[str]]:
    failed_names = {
        str(r.get("name", ""))
        for r in actionable
        if r.get("status") in {"failed", "error"}
    }

    classification_line = ""
    swab_failed: list[str] = []
    scour_only_failed: list[str] = []
    swab_names = _swab_gate_names()
    if not swab_names:
        return classification_line, swab_failed, scour_only_failed

    swab_failed = sorted(n for n in failed_names if n in swab_names)
    scour_only_failed = sorted(n for n in failed_names if n not in swab_names)

    if scour_only_failed and not swab_failed:
        classification_line = "SCOUR-only failures"
        print(
            "::notice::Classification: CI failed due to SCOUR-ONLY gates "
            "(would not fail a plain swab run)."
        )
    elif swab_failed and scour_only_failed:
        classification_line = "Mixed: SWAB-overlap + SCOUR-only failures"
        print(
            "::notice::Classification: CI failed due to both SWAB-overlap "
            "and SCOUR-only gates."
        )
    elif swab_failed:
        classification_line = "SWAB-overlap failures"
        print("::notice::Classification: CI failed on gates that are also in SWAB.")

    if swab_failed:
        print(f"::error::SWAB-overlap failed gates: {', '.join(swab_failed)}")
    if scour_only_failed:
        print(f"::error::SCOUR-only failed gates: {', '.join(scour_only_failed)}")

    return classification_line, swab_failed, scour_only_failed


def _print_actionable_details(actionable: list[dict[str, Any]]) -> list[str]:
    actionable_lines: list[str] = []
    print("::group::Detailed actionable gate results")
    for row in actionable:
        line = format_actionable_line(normalize_actionable_row(row))
        print(line)
        actionable_lines.append(line)
    print("::endgroup::")
    print("::notice::See Code scanning results / slopmop for full findings.")
    return actionable_lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sarif", default="slopmop.sarif")
    parser.add_argument("--json", default="slopmop-results.json")
    parser.add_argument("--step-summary-path", default=None)
    args = parser.parse_args()

    sarif_results, top_rules_line = _read_sarif(args.sarif)
    if not sarif_results and top_rules_line == "SARIF missing or unreadable":
        _write_step_summary(
            args.step_summary_path,
            "",
            [],
            [],
            top_rules_line,
            [],
        )
        return 0

    actionable = _read_actionable_results(args.json)
    if not actionable:
        _write_step_summary(
            args.step_summary_path,
            "",
            [],
            [],
            top_rules_line,
            [],
        )
        return 0
    classification_line, swab_failed, scour_only_failed = _classify_failed_gates(
        actionable
    )
    actionable_lines = _print_actionable_details(actionable)

    _write_step_summary(
        args.step_summary_path,
        classification_line,
        swab_failed,
        scour_only_failed,
        top_rules_line,
        actionable_lines,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
