"""``sm doctor`` CLI driver — run checks, format output, apply fixes.

Output shape (human mode)::

    sm doctor — 2 FAIL, 1 WARN, 6 OK, 1 SKIP

      ✗ state.lock              stale lock held by dead PID 48213
      ✗ sm_env.tool_inventory   3 gate tool(s) missing
      ⚠ project.python_venv     no local venv — gates fall back to sys_executable
      ✓ runtime.platform        Python 3.12.2 (CPython) on Darwin …
      …

    ── state.lock ─────────────────────────────────────────────
    Lock file: /repo/.slopmop/sm.lock
    …

    Fix: sm doctor --fix state.lock

Header first, skimmable table, then detail blocks only for non-OK.
The whole thing pastes cleanly into a bug report.

``--json`` emits a single structured object; auto-detected (like
``sm status``) when stdout is not a tty.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from slopmop.doctor import (
    ALL_CHECKS,
    DoctorContext,
    DoctorResult,
    DoctorStatus,
    run_checks,
    run_fixes,
    select_checks,
)

_GLYPH = {
    DoctorStatus.OK: "✓",
    DoctorStatus.WARN: "⚠",
    DoctorStatus.FAIL: "✗",
    DoctorStatus.SKIP: "○",
}

_RULE_WIDTH = 60


def _counts_line(results: Sequence[DoctorResult]) -> str:
    c: Dict[DoctorStatus, int] = {s: 0 for s in DoctorStatus}
    for r in results:
        c[r.status] += 1
    return (
        f"{c[DoctorStatus.FAIL]} FAIL, {c[DoctorStatus.WARN]} WARN, "
        f"{c[DoctorStatus.OK]} OK, {c[DoctorStatus.SKIP]} SKIP"
    )


def _table_row(r: DoctorResult, name_width: int) -> str:
    glyph = _GLYPH[r.status]
    name = r.name.ljust(name_width)
    return f"  {glyph} {name}  {r.summary}"


def _rule(title: str) -> str:
    prefix = f"── {title} "
    pad = max(0, _RULE_WIDTH - len(prefix))
    return prefix + ("─" * pad)


def _format_human(
    results: List[DoctorResult],
    fixed: Dict[str, DoctorResult] | None = None,
) -> str:
    out: List[str] = []
    sorted_results = sorted(results, key=lambda r: r.sort_key())
    name_width = max((len(r.name) for r in results), default=0)

    out.append(f"sm doctor — {_counts_line(results)}")
    out.append("")
    for r in sorted_results:
        out.append(_table_row(r, name_width))
    out.append("")

    # Detail blocks for non-OK only.  runtime.platform gets a compact
    # one-liner instead of the full detail block when everything is green.
    for r in sorted_results:
        if r.status not in (DoctorStatus.FAIL, DoctorStatus.WARN):
            continue
        if not r.detail:
            continue
        out.append(_rule(r.name))
        out.append(r.detail.rstrip())
        if r.fix_hint:
            out.append("")
            out.append("Fix:")
            for line in r.fix_hint.splitlines():
                out.append(f"  {line}")
        out.append("")

    if fixed:
        out.append(_rule("--fix"))
        for name, post in fixed.items():
            glyph = _GLYPH[post.status]
            out.append(f"  {glyph} {name:<{name_width}}  {post.summary}")
            if post.detail and post.status != DoctorStatus.OK:
                for line in post.detail.splitlines():
                    out.append(f"      {line}")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def _result_to_jsonable(r: DoctorResult) -> Dict[str, object]:
    d = asdict(r)
    d["status"] = r.status.value
    return d


def _format_json(
    results: List[DoctorResult],
    fixed: Dict[str, DoctorResult] | None = None,
) -> str:
    payload: Dict[str, object] = {
        "summary": _counts_line(results),
        "exit_code": _exit_code(results, fixed),
        "checks": [_result_to_jsonable(r) for r in results],
    }
    if fixed:
        payload["fixes"] = {k: _result_to_jsonable(v) for k, v in fixed.items()}
    return json.dumps(payload, indent=2)


def _exit_code(
    results: Sequence[DoctorResult],
    fixed: Dict[str, DoctorResult] | None = None,
) -> int:
    """Exit 1 only when there are FAILs that ``--fix`` did not resolve."""
    fixed = fixed or {}
    for r in results:
        if r.status != DoctorStatus.FAIL:
            continue
        post = fixed.get(r.name)
        if post is not None and post.status == DoctorStatus.OK:
            continue
        return 1
    return 0


def _validate_patterns(patterns: Sequence[str]) -> List[str]:
    """Reject obvious typos so ``sm doctor stat.lock`` doesn't silently run nothing."""
    if not patterns:
        return []
    unknown = [p for p in patterns if not select_checks([p])]
    if unknown:
        names = "\n  ".join(c.name for c in ALL_CHECKS)
        raise SystemExit(
            f"sm doctor: no checks match pattern(s): {', '.join(unknown)}\n"
            f"Available checks:\n  {names}"
        )
    return list(patterns)


def _print_list_checks() -> None:
    name_width = max(len(c.name) for c in ALL_CHECKS)
    for cls in ALL_CHECKS:
        fix = "  [--fix]" if cls.can_fix else ""
        print(f"  {cls.name.ljust(name_width)}  {cls.description}{fix}")


def _print_gates_tree(project_root: Path, json_mode: bool = False) -> int:
    """Show quality gates grouped by level with required tools and status."""
    from slopmop.checks import ensure_checks_registered
    from slopmop.checks.base import GateLevel, find_tool
    from slopmop.core.registry import get_registry

    ensure_checks_registered()
    registry = get_registry()
    root = str(project_root)

    swab_gates: List[Tuple[str, str, List[Tuple[str, bool]]]] = []
    scour_gates: List[Tuple[str, str, List[Tuple[str, bool]]]] = []

    for name, cls in registry._check_classes.items():
        tools_status: List[Tuple[str, bool]] = []
        for tool in cls.required_tools:
            path = find_tool(tool, root)
            tools_status.append((tool, path is not None))

        role_tag = cls.role.value if hasattr(cls, "role") else ""
        entry = (name, role_tag, tools_status)

        if cls.level == GateLevel.SCOUR:
            scour_gates.append(entry)
        else:
            swab_gates.append(entry)

    if json_mode:
        payload: dict[str, list[dict[str, object]]] = {
            "swab": [
                {"gate": g, "role": r, "tools": [{"name": t, "ok": ok} for t, ok in ts]}
                for g, r, ts in swab_gates
            ],
            "scour": [
                {"gate": g, "role": r, "tools": [{"name": t, "ok": ok} for t, ok in ts]}
                for g, r, ts in scour_gates
            ],
        }
        print(json.dumps(payload, indent=2))
        return 0

    def _format_group(
        label: str, gates: List[Tuple[str, str, List[Tuple[str, bool]]]]
    ) -> List[str]:
        lines: List[str] = []
        lines.append(f"{label} ({len(gates)} gates)")
        name_width = max((len(g) for g, _, _ in gates), default=0)
        for gate_name, _role, tools in sorted(gates):
            if tools:
                tool_parts: list[str] = []
                for t, ok in tools:
                    tool_parts.append(f"{'✓' if ok else '✗'} {t}")
                tool_str = ", ".join(tool_parts)
            else:
                tool_str = "(pure — no external tools)"
            lines.append(f"  {gate_name.ljust(name_width)}  {tool_str}")
        lines.append("")
        return lines

    out: List[str] = []
    out.extend(_format_group("swab", swab_gates))
    if scour_gates:
        out.extend(_format_group("scour-only", scour_gates))
    print("\n".join(out).rstrip())
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Entry point for ``sm doctor``."""
    if args.list_checks:
        _print_list_checks()
        return 0

    if args.gates:
        project_root = Path(getattr(args, "project_root", ".") or ".").resolve()
        json_mode = args.json_output
        if json_mode is None:
            json_mode = not sys.stdout.isatty()
        return _print_gates_tree(project_root, json_mode=json_mode)

    patterns = _validate_patterns(args.checks or [])
    project_root = Path(getattr(args, "project_root", ".") or ".").resolve()
    ctx = DoctorContext(project_root=project_root, apply_fix=bool(args.fix))

    # JSON mode mirrors sm status: auto when not a tty, explicit --json
    # forces on, explicit --no-json forces off.
    json_mode = args.json_output
    if json_mode is None:
        json_mode = not sys.stdout.isatty()

    results = run_checks(ctx, patterns)

    fixed: Dict[str, DoctorResult] | None = None
    if args.fix:
        fix_candidates = [
            r for r in results if r.can_fix and r.status != DoctorStatus.OK
        ]
        if fix_candidates:
            proceed = True
            # Prompt goes to stderr so stdout stays clean for --json
            # consumers.  Still gate on stdin tty — piped input means
            # no human to answer.
            if not args.yes and sys.stdin.isatty():
                names = ", ".join(r.name for r in fix_candidates)
                sys.stderr.write(f"Will attempt to fix: {names}\nProceed? [y/N] ")
                sys.stderr.flush()
                ans = sys.stdin.readline().strip().lower()
                if ans not in ("y", "yes"):
                    sys.stderr.write("Aborted — nothing changed.\n")
                    proceed = False
            if proceed:
                fixed = run_fixes(ctx, results)

    if json_mode:
        print(_format_json(results, fixed))
    else:
        print(_format_human(results, fixed), end="")

    return _exit_code(results, fixed)


def run_doctor(args: argparse.Namespace) -> int:  # pragma: no cover — alias
    return cmd_doctor(args)
