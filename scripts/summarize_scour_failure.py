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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sarif", default="slopmop.sarif")
    parser.add_argument("--json", default="slopmop-results.json")
    args = parser.parse_args()

    sarif_doc = _load_json(Path(args.sarif))
    if sarif_doc is None:
        print("::error::slopmop scour failed - SARIF missing or unreadable")
        return 0

    runs = sarif_doc.get("runs") or []
    sarif_results = (runs[0].get("results") or []) if runs else []
    if not sarif_results:
        print("::error::slopmop scour failed, but SARIF has zero results")
    else:
        counts = Counter(r.get("ruleId", "unknown") for r in sarif_results)
        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
        summary = ", ".join(f"{rule} ({n})" for rule, n in top)
        print(f"::error::Top SARIF rules: {summary}")

    json_doc = _load_json(Path(args.json))
    if json_doc is None:
        print(
            "::warning::JSON report missing/unreadable; cannot classify "
            "scour-only vs swab-overlap failures"
        )
        print("::notice::See Code scanning results / slopmop for detailed findings.")
        return 0

    actionable = [
        r
        for r in (json_doc.get("results") or [])
        if r.get("status") in {"failed", "error", "warned"}
    ]
    if not actionable:
        print("::warning::No actionable results found in JSON report")
        return 0

    status_order = {"error": 0, "failed": 1, "warned": 2}
    actionable.sort(
        key=lambda r: (status_order.get(str(r.get("status")), 9), str(r.get("name", "")))
    )

    failed_names = {
        str(r.get("name", ""))
        for r in actionable
        if r.get("status") in {"failed", "error"}
    }

    swab_names = _swab_gate_names()
    if swab_names:
        swab_failed = sorted(n for n in failed_names if n in swab_names)
        scour_only_failed = sorted(n for n in failed_names if n not in swab_names)

        if scour_only_failed and not swab_failed:
            print(
                "::notice::Classification: CI failed due to SCOUR-ONLY gates "
                "(would not fail a plain swab run)."
            )
        elif swab_failed and scour_only_failed:
            print(
                "::notice::Classification: CI failed due to both SWAB-overlap "
                "and SCOUR-only gates."
            )
        elif swab_failed:
            print("::notice::Classification: CI failed on gates that are also in SWAB.")

        if swab_failed:
            print(f"::error::SWAB-overlap failed gates: {', '.join(swab_failed)}")
        if scour_only_failed:
            print(f"::error::SCOUR-only failed gates: {', '.join(scour_only_failed)}")

    print("::group::Detailed actionable gate results")
    for row in actionable:
        name = str(row.get("name", "unknown"))
        status = str(row.get("status", "unknown")).upper()
        detail = (
            row.get("error")
            or row.get("fix_suggestion")
            or row.get("status_detail")
            or "(no detail)"
        )
        print(f"- {status}: {name} :: {detail}")
    print("::endgroup::")

    print("::notice::See Code scanning results / slopmop for full findings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
