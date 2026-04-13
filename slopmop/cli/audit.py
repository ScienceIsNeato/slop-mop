"""``sm audit`` — read-only codebase health snapshot.

Produces a structured report covering two lenses:

1. **Git analytics** — who built this, what changes most, where bugs cluster,
   how fast the project is moving, and how often the team firefights.
2. **Gate violations** — run every scour gate in reporting-only mode (no
   auto-fix, no pass/fail exit code) and expose what slop currently exists.

This report is **informational only**.  Nothing here is enforced and nothing
is auto-fixed.  Use it to orient yourself before a refit, to track progress
during one, or to get a snapshot of a repo already in maintenance mode.
The violations section will shrink as remediation proceeds; the git section
reflects history and does not change based on workflow phase.

Requires ``sm init`` to have been run at least once (so ``.slopmop/`` exists).
Otherwise, ``sm audit`` is idempotent and safe to run at any lifecycle stage.

``sm audit`` does not modify tracked project files, never runs auto-fix, and
always exits 0.  Generated artifacts (``.slopmop/audit-report.md``,
``.slopmop/audit-gate-inventory.json``) are written to the gitignored
``.slopmop/`` directory.  The report is also printed to stdout unless
``--quiet`` or ``--json`` is active.

Usage::

    sm audit [--project-root PATH] [--output PATH] [--no-git] [--no-gates]
             [--since DURATION] [--top N] [--json] [-q]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_DEFAULT_OUTPUT = ".slopmop/audit-report.md"
_SCHEMA = "slopmop/audit/v1"
_SECTION_WIDTH = 72
_HLINE = "─" * _SECTION_WIDTH


# ── Git helpers ──────────────────────────────────────────────────────────────


def _run_git_cmd(args: List[str], cwd: str) -> Tuple[int, str]:
    """Run a git command and return (returncode, stdout).

    Returns ``(1, "")`` when ``git`` is not installed so callers can treat
    a missing git binary the same as a failed command without crashing.
    """
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode, result.stdout
    except OSError:
        return 1, ""


def _is_git_repo(project_root: str) -> bool:
    rc, _ = _run_git_cmd(["rev-parse", "--is-inside-work-tree"], project_root)
    return rc == 0


def _churn_hotspots(project_root: str, since: str, top_n: int) -> List[Tuple[int, str]]:
    """Return [(count, path), …] sorted descending by change count."""
    _, output = _run_git_cmd(
        [
            "log",
            "--format=format:",
            "--name-only",
            f"--since={since}",
        ],
        project_root,
    )
    counts: Dict[str, int] = {}
    for line in output.splitlines():
        line = line.strip()
        if line:
            counts[line] = counts.get(line, 0) + 1
    pairs = [(count, path) for path, count in counts.items()]
    return sorted(pairs, key=lambda kv: kv[0], reverse=True)[:top_n]


def _bug_commits(project_root: str, top_n: int) -> List[Tuple[int, str]]:
    """Return [(count, path), …] from commits matching fix/bug/broken."""
    _, output = _run_git_cmd(
        [
            "log",
            "-i",
            "-E",
            "--grep=fix|bug|broken",
            "--name-only",
            "--format=",
        ],
        project_root,
    )
    counts: Dict[str, int] = {}
    for line in output.splitlines():
        line = line.strip()
        if line:
            counts[line] = counts.get(line, 0) + 1
    pairs = [(count, path) for path, count in counts.items()]
    return sorted(pairs, key=lambda kv: kv[0], reverse=True)[:top_n]


def _cross_reference(
    churn: List[Tuple[int, str]],
    bugs: List[Tuple[int, str]],
) -> List[Tuple[str, int, int]]:
    """Return [(path, churn_count, bug_count), …] for files in both lists."""
    bug_map = {path: count for count, path in bugs}
    result: List[Tuple[str, int, int]] = []
    for count, path in churn:
        if path in bug_map:
            result.append((path, count, bug_map[path]))
    result.sort(key=lambda t: t[1] + t[2], reverse=True)
    return result


def _contributors(project_root: str) -> List[Tuple[int, str]]:
    _, output = _run_git_cmd(["shortlog", "-sn", "--no-merges", "HEAD"], project_root)
    result: List[Tuple[int, str]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t", 1)
        if len(parts) == 2:
            try:
                result.append((int(parts[0].strip()), parts[1].strip()))
            except ValueError:
                pass
    return result


def _contributors_recent(project_root: str, since: str) -> List[Tuple[int, str]]:
    _, output = _run_git_cmd(
        ["shortlog", "-sn", "--no-merges", f"--since={since}", "HEAD"],
        project_root,
    )
    result: List[Tuple[int, str]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t", 1)
        if len(parts) == 2:
            try:
                result.append((int(parts[0].strip()), parts[1].strip()))
            except ValueError:
                pass
    return result


def _velocity_by_month(project_root: str) -> List[Tuple[int, str]]:
    """Return [(count, 'YYYY-MM'), …] oldest first."""
    _, output = _run_git_cmd(
        ["log", "--format=%ad", "--date=format:%Y-%m"],
        project_root,
    )
    counts: Dict[str, int] = {}
    for line in output.splitlines():
        line = line.strip()
        if line:
            counts[line] = counts.get(line, 0) + 1
    pairs = [(count, month) for month, count in counts.items()]
    return sorted(pairs, key=lambda t: t[1])  # sort by month string, not count


def _firefighting(project_root: str, since: str) -> List[str]:
    _, output = _run_git_cmd(
        [
            "log",
            "--oneline",
            f"--since={since}",
        ],
        project_root,
    )
    hits: List[str] = []
    import re

    pattern = re.compile(r"revert|hotfix|emergency|rollback", re.IGNORECASE)
    for line in output.splitlines():
        if pattern.search(line):
            hits.append(line.strip())
    return hits


# ── Gate inventory (no-fix scour) ────────────────────────────────────────────


def _run_gate_inventory(
    project_root: Path,
    quiet: bool = False,
) -> Optional[Dict[str, Any]]:
    """Run scour with --no-auto-fix and return the JSON summary, or None.

    When *quiet* is False (default) the scour progress display is left
    connected to the terminal so the user sees the beautiful gate-by-gate
    output rather than silence.  Pass ``quiet=True`` only in tests or
    non-interactive contexts (e.g. JSON mode).
    """
    artifact_path = project_root / ".slopmop" / "audit-gate-inventory.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "slopmop.sm",
        "scour",
        "--no-auto-fix",
        "--no-cache",
        "--json-file",
        str(artifact_path),
        "--project-root",
        str(project_root),
    ]
    if quiet:
        command.append("--quiet")

    # audit does not hold a repo lock itself, so let scour acquire its
    # own lock normally.  Do NOT set SLOPMOP_SKIP_REPO_LOCK — that env
    # var is restricted to the refit pipeline and is rejected by any
    # other caller.
    #
    # When not in quiet mode, leave stdout/stderr connected to the
    # terminal so the progress display renders live.  capture_output
    # would silence it completely.
    subprocess.run(
        command,
        cwd=str(project_root),
        capture_output=quiet,
        text=True,
        check=False,
    )

    if artifact_path.exists():
        try:
            return json.loads(artifact_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


# ── Report formatting ────────────────────────────────────────────────────────


def _separator_line(char: str = "─") -> str:
    return char * _SECTION_WIDTH


def _section(title: str) -> str:
    return f"\n{'═' * _SECTION_WIDTH}\n{title}\n{'═' * _SECTION_WIDTH}\n"


def _collect_git_data(
    project_root: str,
    since: str,
    top_n: int,
) -> Optional[Dict[str, Any]]:
    """Run all git queries once and return a single dict.

    Returns ``None`` when ``project_root`` is not a git repository so callers
    can skip git sections without running a separate ``_is_git_repo`` check.
    """
    if not _is_git_repo(project_root):
        return None
    churn = _churn_hotspots(project_root, since, top_n)
    bugs = _bug_commits(project_root, top_n)
    hotspots = _cross_reference(churn, bugs)
    all_contributors = _contributors(project_root)
    recent_contributors = _contributors_recent(project_root, "6 months ago")
    velocity = _velocity_by_month(project_root)
    fires = _firefighting(project_root, since)
    return {
        "churn": churn,
        "bugs": bugs,
        "hotspots": hotspots,
        "all_contributors": all_contributors,
        "recent_contributors": recent_contributors,
        "velocity": velocity,
        "firefighting": fires,
    }


def _format_git_section(
    project_root: str,
    since: str,
    top_n: int,
    git_data: Optional[Dict[str, Any]] = None,
) -> List[str]:
    lines: List[str] = []
    lines.append(_section("📊 GIT ANALYTICS"))

    if git_data is None:
        git_data = _collect_git_data(project_root, since, top_n)
    if git_data is None:
        lines.append("  (not a git repository — skipping git analysis)\n")
        return lines

    # 1. Contributors
    lines.append(_HLINE)
    lines.append("WHO BUILT THIS")
    lines.append(_HLINE)
    all_contributors = git_data["all_contributors"]
    recent_contributors = git_data["recent_contributors"]
    recent_names = {name for _, name in recent_contributors}
    if all_contributors:
        total_commits = sum(c for c, _ in all_contributors)
        for count, name in all_contributors[:15]:
            pct = count / total_commits * 100 if total_commits else 0
            active = "" if name in recent_names else "  (inactive >6mo)"
            lines.append(f"  {count:>5}  {pct:5.1f}%  {name}{active}")
        bus_factor = len([n for _, n in recent_contributors])
        lines.append(f"\n  Bus factor (active contributors, last 6mo): {bus_factor}")
        if bus_factor == 1:
            lines.append("  ⚠  Single active contributor — bus factor risk.")
    else:
        lines.append("  (no commit history)")
    lines.append("")

    # 2. Churn hotspots
    lines.append(_HLINE)
    lines.append(f"MOST CHANGED (last {since})")
    lines.append(_HLINE)
    churn = git_data["churn"]
    if churn:
        for count, path in churn:
            lines.append(f"  {count:>5}  {path}")
    else:
        lines.append("  (no data)")
    lines.append("")

    # 3. Bug clusters
    lines.append(_HLINE)
    lines.append("BUG-KEYWORD COMMITS (all time)")
    lines.append(_HLINE)
    bugs = git_data["bugs"]
    if bugs:
        for count, path in bugs:
            lines.append(f"  {count:>5}  {path}")
    else:
        lines.append("  (no fix/bug/broken commits found — check commit discipline)")
    lines.append("")

    # 4. Cross-reference
    hotspots = git_data["hotspots"]
    if hotspots:
        lines.append(_HLINE)
        lines.append(f"HIGH-RISK FILES (high churn AND high bug-commit count)")
        lines.append(_HLINE)
        for path, churn_count, bug_count in hotspots[:10]:
            lines.append(f"  churn={churn_count:>4}  bugs={bug_count:>4}  {path}")
        lines.append("")

    # 5. Velocity
    lines.append(_HLINE)
    lines.append("COMMIT VELOCITY (by month)")
    lines.append(_HLINE)
    velocity = git_data["velocity"]
    if velocity:
        max_count = max(c for c, _ in velocity) if velocity else 1
        bar_scale = min(1.0, 40 / max_count)
        for count, month in velocity[-18:]:
            bar = "█" * int(count * bar_scale)
            lines.append(f"  {month}  {count:>4}  {bar}")
    else:
        lines.append("  (no data)")
    lines.append("")

    # 6. Firefighting
    lines.append(_HLINE)
    lines.append(f"FIREFIGHTING (reverts/hotfixes, last {since})")
    lines.append(_HLINE)
    fires = git_data["firefighting"]
    if fires:
        for hit in fires:
            lines.append(f"  {hit}")
        lines.append(f"\n  Total: {len(fires)} revert/hotfix/rollback commits")
    else:
        lines.append("  (none found)")
    lines.append("")

    return lines


def _format_gate_section(gate_data: Optional[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    lines.append(_section("🔍 GATE VIOLATION INVENTORY"))
    lines.append(
        "  This section is informational. Nothing is enforced or auto-fixed here."
    )
    lines.append(
        "  Use it to understand current slop before, during, or after a refit."
    )
    lines.append("")

    if gate_data is None:
        lines.append("  (gate scan failed — check `sm doctor`)\n")
        return lines

    summary = gate_data.get("summary", {})
    total = summary.get("total_checks", 0)
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    skipped = summary.get("skipped", 0)
    na = summary.get("not_applicable", 0)
    duration = summary.get("total_duration", 0)

    lines.append(
        f"  Gates: {total} total  |  {passed} passed  |  {failed} failing"
        f"  |  {skipped} skipped  |  {na} N/A  |  {duration:.1f}s"
    )
    lines.append("")

    results: List[Dict[str, Any]] = gate_data.get("results", [])
    failing = [r for r in results if r.get("status") == "failed"]
    warned_list = [r for r in results if r.get("status") == "warned"]
    # Passing gate names live in the top-level ``passed_gates`` list —
    # they are NOT included in ``results`` (which only contains non-passing
    # entries).  Reading ``results`` for passed status always yields 0.
    passing_names: List[str] = gate_data.get("passed_gates", [])

    if failing:
        lines.append(_HLINE)
        lines.append(f"FAILING GATES ({len(failing)})")
        lines.append(_HLINE)
        for r in failing:
            name = r.get("name", "?")
            error = r.get("error", "")
            lines.append(f"  ❌  {name}")
            if error:
                for eline in str(error).splitlines()[:3]:
                    lines.append(f"       {eline}")
        lines.append("")

    if warned_list:
        lines.append(_HLINE)
        lines.append(f"WARNED GATES ({len(warned_list)})")
        lines.append(_HLINE)
        for r in warned_list:
            lines.append(f"  ⚠️   {r.get('name', '?')}")
        lines.append("")

    if passing_names:
        lines.append(_HLINE)
        lines.append(f"PASSING GATES ({len(passing_names)})")
        lines.append(_HLINE)
        for name in sorted(passing_names):
            lines.append(f"  ✅  {name}")
        lines.append("")

    return lines


def _build_report(
    project_root: str,
    since: str,
    top_n: int,
    include_git: bool,
    include_gates: bool,
    gate_data: Optional[Dict[str, Any]],
    timestamp: str,
    git_data: Optional[Dict[str, Any]] = None,
) -> str:
    parts: List[str] = []
    parts.append(f"# slop-mop audit report")
    parts.append(f"Generated: {timestamp}")
    parts.append(f"Project:   {Path(project_root).resolve()}")
    parts.append(f"Schema:    {_SCHEMA}")
    parts.append("")

    if include_git:
        parts.extend(_format_git_section(project_root, since, top_n, git_data))

    if include_gates:
        parts.extend(_format_gate_section(gate_data))

    parts.append(_separator_line("═"))
    parts.append(
        "This report is informational. Nothing here is enforced or auto-fixed."
    )
    parts.append(
        "Run `sm audit` again at any stage — violations shrink as you remediate."
    )
    parts.append(_separator_line("═"))
    parts.append("")
    return "\n".join(parts)


# ── JSON output ───────────────────────────────────────────────────────────────


def _build_json_payload(
    project_root: str,
    since: str,
    top_n: int,
    include_git: bool,
    include_gates: bool,
    gate_data: Optional[Dict[str, Any]],
    timestamp: str,
    git_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schema": _SCHEMA,
        "generated_at": timestamp,
        "project_root": str(Path(project_root).resolve()),
    }

    if include_git:
        if git_data is None:
            git_data = _collect_git_data(project_root, since, top_n)
        if git_data is not None:
            churn = git_data["churn"]
            bugs = git_data["bugs"]
            hotspots = git_data["hotspots"]
            payload["git"] = {
                "contributors_all_time": [
                    {"commits": c, "author": n} for c, n in git_data["all_contributors"]
                ],
                "contributors_recent_6mo": [
                    {"commits": c, "author": n}
                    for c, n in git_data["recent_contributors"]
                ],
                "churn_hotspots": [{"changes": c, "path": p} for c, p in churn],
                "bug_clusters": [{"bug_commits": c, "path": p} for c, p in bugs],
                "high_risk_files": [
                    {"path": p, "churn": ch, "bug_commits": bc}
                    for p, ch, bc in hotspots[:10]
                ],
                "velocity_by_month": [
                    {"month": m, "commits": c} for c, m in git_data["velocity"]
                ],
                "firefighting": git_data["firefighting"],
            }

    if include_gates:
        payload["gates"] = gate_data or {}

    return payload


# ── Entry point ───────────────────────────────────────────────────────────────


def cmd_audit(args: argparse.Namespace) -> int:
    """Entry point for ``sm audit``."""
    project_root = Path(getattr(args, "project_root", ".")).resolve()
    since = getattr(args, "since", "1 year ago")
    top_n = getattr(args, "top", 20)
    include_git = not getattr(args, "no_git", False)
    include_gates = not getattr(args, "no_gates", False)
    output_path_str: Optional[str] = getattr(args, "output", None)
    json_flag = getattr(args, "json_output", None)
    json_mode = json_flag is True or (json_flag is None and not sys.stdout.isatty())
    quiet = getattr(args, "quiet", False)

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not quiet and not json_mode:
        print(f"🔍  sm audit — {project_root}")
        if include_git:
            print("    Collecting git analytics …")

    # Collect git data once — reused by both the text report and the JSON payload
    # to avoid redundant git subprocess calls in json_mode.
    git_data: Optional[Dict[str, Any]] = None
    if include_git:
        git_data = _collect_git_data(str(project_root), since, top_n)

    gate_data: Optional[Dict[str, Any]] = None
    if include_gates:
        # In interactive mode let the scour progress display render live.
        # In quiet/json mode suppress it to keep stdout clean.
        suppress_scour_output = quiet or json_mode
        if not suppress_scour_output:
            print("\n── Gate inventory (sm scour --no-auto-fix) ──────────────\n")
        gate_data = _run_gate_inventory(project_root, quiet=suppress_scour_output)

    # Always build and write the report file regardless of output mode.
    report = _build_report(
        str(project_root),
        since,
        top_n,
        include_git,
        include_gates,
        gate_data,
        timestamp,
        git_data,
    )
    output_path = Path(
        output_path_str if output_path_str else project_root / _DEFAULT_OUTPUT
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    if json_mode:
        payload = _build_json_payload(
            str(project_root),
            since,
            top_n,
            include_git,
            include_gates,
            gate_data,
            timestamp,
            git_data,
        )
        print(json.dumps(payload, indent=2))
        return 0

    # Print to stdout
    if not quiet:
        print(report)
        try:
            rel: Path = output_path.relative_to(project_root)
        except ValueError:
            rel = output_path
        print(f"📄  Report saved to {rel}")

    return 0
