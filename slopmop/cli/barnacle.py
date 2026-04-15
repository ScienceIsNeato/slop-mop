"""Barnacle queue — file, claim, and resolve tool-friction reports.

A barnacle is a defect or friction point in slop-mop itself, discovered
by an agent while using the tool in a real repository.  The queue lives
at ``~/.slopmop/barnacles/`` (overridable via ``SLOPMOP_BARNACLE_DIR``)
so every agent on the same machine can see and act on the same pool.

Lifecycle
---------
open  →  claimed  →  resolved
      →  wont-fix

Filing agents discover barnacles and run ``sm barnacle file``.
Cleaning agents (typically the slop-mop maintainer) run
``sm barnacle watch``, ``sm barnacle claim``, fix the issue, then
``sm barnacle resolve``.

The barnacle verb mirrors the swab/scour/buff nautical theme: every
agent is both a detector and a potential cleaner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "slopmop/barnacle/v1"

# Status constants
STATUS_OPEN = "open"
STATUS_CLAIMED = "claimed"
STATUS_RESOLVED = "resolved"
STATUS_WONT_FIX = "wont-fix"
VALID_STATUSES = (STATUS_OPEN, STATUS_CLAIMED, STATUS_RESOLVED, STATUS_WONT_FIX)

BLOCKER_BLOCKING = "blocking"
BLOCKER_NON_BLOCKING = "non-blocking"
VALID_BLOCKER_TYPES = (BLOCKER_BLOCKING, BLOCKER_NON_BLOCKING)

# Environment variable to override queue location (primarily for tests)
QUEUE_DIR_ENVAR = "SLOPMOP_BARNACLE_DIR"

# Shared error/help strings (re-used across handlers and the argparse spec)
ERR_MISSING_ID = "❌ barnacle_id required"
ERR_NOT_FOUND_FMT = "❌ Barnacle not found: {}"
HELP_AGENT = "Agent identifier (default: user@hostname)"
HELP_BARNACLE_ID = "Full or prefix barnacle ID"

_STATUS_ICONS = {
    STATUS_OPEN: "🔴",
    STATUS_CLAIMED: "🟡",
    STATUS_RESOLVED: "✅",
    STATUS_WONT_FIX: "⬜",
}


# ---------------------------------------------------------------------------
# Queue directory helpers
# ---------------------------------------------------------------------------


def _queue_dir() -> Path:
    override = os.environ.get(QUEUE_DIR_ENVAR)
    if override:
        return Path(override)
    return Path.home() / ".slopmop" / "barnacles"


def _iso_now() -> str:  # noqa: ambiguity-mine
    return datetime.now(timezone.utc).isoformat()


def _short_id() -> str:
    raw = f"{time.time_ns()}{os.getpid()}".encode()
    return hashlib.sha256(raw).hexdigest()[:8]


def _barnacle_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"barnacle-{ts}-{_short_id()}"


def _default_agent() -> str:
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
    host = socket.gethostname()
    return f"{user}@{host}"


def _barnacle_path(bid: str) -> Path:
    return _queue_dir() / f"{bid}.json"


def _read_barnacle(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())  # type: ignore[no-any-return]


def _write_barnacle(data: Dict[str, Any]) -> Path:
    qdir = _queue_dir()
    qdir.mkdir(parents=True, exist_ok=True)
    path = _barnacle_path(data["id"])
    path.write_text(json.dumps(data, indent=2))
    return path


def _list_barnacles(status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    qdir = _queue_dir()
    if not qdir.exists():
        return []
    results: List[Dict[str, Any]] = []
    for p in sorted(qdir.glob("barnacle-*.json")):
        try:
            b = _read_barnacle(p)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(b, dict) or "id" not in b or "status" not in b:
            continue  # skip corrupted entries
        if status_filter and status_filter != "all":
            if b.get("status") != status_filter:
                continue
        results.append(b)
    return results


_SAFE_PREFIX_RE = re.compile(r"^[a-zA-Z0-9\-_]+$")


def _find_barnacle(bid_prefix: str) -> Optional[Dict[str, Any]]:
    """Find a barnacle by full or prefix ID.

    Iterates only ``barnacle-*.json`` within the queue dir and matches on
    ``Path.stem.startswith(bid_prefix)`` after validating the prefix contains
    only safe characters.  Returns ``None`` if 0 or >1 matches are found.
    """
    if not _SAFE_PREFIX_RE.match(bid_prefix):
        print(
            f"❌ Invalid barnacle ID prefix (unsafe characters): {bid_prefix!r}",
            file=sys.stderr,
        )
        return None
    qdir = _queue_dir()
    if not qdir.exists():
        print(ERR_NOT_FOUND_FMT.format(bid_prefix), file=sys.stderr)
        return None
    matches: List[Dict[str, Any]] = []
    for p in sorted(qdir.glob("barnacle-*.json")):
        if not p.stem.startswith(bid_prefix):
            continue
        try:
            matches.append(_read_barnacle(p))
        except (json.JSONDecodeError, OSError):
            continue
    if len(matches) == 0:
        print(ERR_NOT_FOUND_FMT.format(bid_prefix), file=sys.stderr)
        return None
    if len(matches) > 1:
        print(
            f"❌ Ambiguous prefix '{bid_prefix}' matches {len(matches)} barnacles;"
            " use a longer prefix.",
            file=sys.stderr,
        )
        return None
    return matches[0]


def _installed_slopmop_version() -> str:
    try:
        from importlib.metadata import version  # noqa: PLC0415

        return version("slopmop")
    except Exception:
        return "unknown"


def _git_branch(path: str) -> str:
    try:
        import subprocess  # noqa: PLC0415

        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            cwd=path,
        )
        if result.returncode == 0:
            return result.stdout.strip() or "unknown"
    except Exception:
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# Public auto-file helper (called by other sm commands)
# ---------------------------------------------------------------------------


def auto_file_barnacle(
    *,
    command: str,
    gate: Optional[str] = None,
    expected: str,
    actual: str,
    output_excerpt: str,
    blocker_type: str = BLOCKER_BLOCKING,
    project_root: Optional[str] = None,
    reproduction_steps: Optional[List[str]] = None,
) -> Optional[str]:
    """Auto-file a barnacle from within a slop-mop command.

    Called by commands that can self-detect tool defects (e.g. ``sm upgrade``
    when post-install validation fails unexpectedly).

    Returns the barnacle ID on success, None if filing fails (never raises).
    """
    try:
        _queue_dir().mkdir(parents=True, exist_ok=True)
        branch = _git_branch(project_root) if project_root else "unknown"
        bid = _barnacle_id()
        data: Dict[str, Any] = {
            "schema": SCHEMA_VERSION,
            "id": bid,
            "filed_at": _iso_now(),
            "status": STATUS_OPEN,
            "filed_by": {
                "agent": _default_agent(),
                "repo": project_root or "unknown",
                "branch": branch,
                "slopmop_version": _installed_slopmop_version(),
            },
            "command": command,
            "gate": gate,
            "blocker_type": blocker_type,
            "expected": expected,
            "actual": actual,
            "output_excerpt": output_excerpt,
            "reproduction_steps": reproduction_steps or [command],
            "auto_filed": True,
            "claim": None,
            "resolution": None,
        }
        _write_barnacle(data)
        return bid
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_barnacle_file(args: argparse.Namespace) -> int:
    """File a new barnacle."""
    project_root = str(Path(getattr(args, "project_root", ".")).resolve())
    bid = _barnacle_id()
    data: Dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "id": bid,
        "filed_at": _iso_now(),
        "status": STATUS_OPEN,
        "filed_by": {
            "agent": getattr(args, "agent", None) or _default_agent(),
            "repo": project_root,
            "branch": _git_branch(project_root),
            "slopmop_version": _installed_slopmop_version(),
        },
        "command": getattr(args, "command", "") or "",
        "gate": getattr(args, "gate", None),
        "blocker_type": getattr(args, "blocker_type", BLOCKER_BLOCKING),
        "expected": getattr(args, "expected", "") or "",
        "actual": getattr(args, "actual", "") or "",
        "output_excerpt": getattr(args, "output_excerpt", "") or "",
        "reproduction_steps": getattr(args, "reproduction_steps", None)
        or [getattr(args, "command", "") or ""],
        "auto_filed": False,
        "claim": None,
        "resolution": None,
    }
    path = _write_barnacle(data)
    print(f"🐚 Barnacle filed: {bid}")
    print(f"   {path}")
    print(f"   Blocker: {data['blocker_type']}")
    print()
    print(f"Cleaning agents can claim it with:")
    print(f"  sm barnacle claim {bid}")
    return 0


def cmd_barnacle_list(args: argparse.Namespace) -> int:
    """List barnacles in the queue."""
    status_filter = getattr(args, "status", STATUS_OPEN)
    barnacles = _list_barnacles(status_filter)
    if not barnacles:
        label = "no" if status_filter == "all" else f"no {status_filter}"
        print(f"🐚 {label.capitalize()} barnacles  ({_queue_dir()})")
        return 0

    print(f"🐚 Barnacles  ({_queue_dir()})")
    for b in barnacles:
        status = b.get("status", "?")
        icon = _STATUS_ICONS.get(status, "❓")
        blocker = "  [BLOCKING]" if b.get("blocker_type") == BLOCKER_BLOCKING else ""
        filed_by = b.get("filed_by", {})
        repo = Path(filed_by.get("repo", "?")).name
        date = b.get("filed_at", "?")[:10]
        print(f"  {icon} {b['id']}{blocker}")
        print(f"     {b.get('command', '?')} · {repo} · {date}")
    return 0


def _print_barnacle(b: Dict[str, Any]) -> None:
    status = b.get("status", "?")
    icon = _STATUS_ICONS.get(status, "❓")
    filed_by = b.get("filed_by", {})
    print(f"🐚 {b['id']}")
    print(f"   Status:  {icon} {status}")
    print(f"   Filed:   {b.get('filed_at', '?')}")
    print(f"   By:      {filed_by.get('agent', '?')}")
    print(f"   Repo:    {filed_by.get('repo', '?')}  ({filed_by.get('branch', '?')})")
    print(f"   Version: {filed_by.get('slopmop_version', '?')}")
    print(f"   Blocker: {b.get('blocker_type', '?')}")
    print(f"   Command: {b.get('command', '?')}")
    if b.get("gate"):
        print(f"   Gate:    {b['gate']}")
    print()
    print(f"Expected:")
    print(f"  {b.get('expected', '(none)')}")
    print()
    print(f"Actual:")
    print(f"  {b.get('actual', '(none)')}")
    if b.get("output_excerpt"):
        print()
        print("Output excerpt:")
        for line in b["output_excerpt"].strip().splitlines()[:20]:
            print(f"  {line}")
    if b.get("reproduction_steps"):
        print()
        print("Reproduction steps:")
        for i, step in enumerate(b["reproduction_steps"], 1):
            print(f"  {i}. {step}")
    if b.get("claim"):
        claim = b["claim"]
        print()
        print(
            f"Claimed by: {claim.get('agent', '?')}  at {claim.get('claimed_at', '?')}"
        )
    if b.get("resolution"):
        res = b["resolution"]
        print()
        print(f"Resolved by: {res.get('agent', '?')}  at {res.get('resolved_at', '?')}")
        if res.get("fix_commit"):
            print(f"  Commit: {res['fix_commit']}")
        if res.get("fix_branch"):
            print(f"  Branch: {res['fix_branch']}")
        if res.get("notes"):
            print(f"  Notes:  {res['notes']}")


def cmd_barnacle_show(args: argparse.Namespace) -> int:
    """Show full details for one barnacle."""
    bid = getattr(args, "barnacle_id", None)
    if not bid:
        print(ERR_MISSING_ID, file=sys.stderr)
        return 1
    b = _find_barnacle(bid)
    if not b:
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(b, indent=2))
        return 0
    _print_barnacle(b)
    return 0


def cmd_barnacle_claim(args: argparse.Namespace) -> int:
    """Claim a barnacle to address it."""
    bid = getattr(args, "barnacle_id", None)
    if not bid:
        print(ERR_MISSING_ID, file=sys.stderr)
        return 1
    b = _find_barnacle(bid)
    if not b:
        return 1
    if b.get("status") == STATUS_CLAIMED:
        claim_data: Dict[str, Any] = b.get("claim") or {}
        existing: str = claim_data.get("agent", "?")
        print(f"⚠️  Already claimed by {existing}", file=sys.stderr)
        return 1
    if b.get("status") != STATUS_OPEN:
        print(
            f"❌ Cannot claim a barnacle with status: {b.get('status')}",
            file=sys.stderr,
        )
        return 1

    agent = getattr(args, "agent", None) or _default_agent()
    b["status"] = STATUS_CLAIMED
    b["claim"] = {"agent": agent, "claimed_at": _iso_now()}
    _write_barnacle(b)

    print(f"🟡 Claimed {b['id']}")
    print(f"   Repo:      {b.get('filed_by', {}).get('repo', '?')}")
    print(f"   Command:   {b.get('command', '?')}")
    print(f"   Expected:  {b.get('expected', '?')}")
    print(f"   Actual:    {b.get('actual', '?')}")
    print()
    print(f"When fixed, resolve with:")
    print(f"  sm barnacle resolve {b['id']} --commit <SHA> --branch <branch>")
    return 0


def cmd_barnacle_resolve(args: argparse.Namespace) -> int:
    """Resolve a barnacle with fix details."""
    bid = getattr(args, "barnacle_id", None)
    if not bid:
        print(ERR_MISSING_ID, file=sys.stderr)
        return 1
    b = _find_barnacle(bid)
    if not b:
        return 1
    if b.get("status") == STATUS_RESOLVED:
        print("⚠️  Already resolved")
        return 0
    if b.get("status") != STATUS_CLAIMED:
        print(
            f"❌ Cannot resolve a barnacle with status '{b.get('status')}'; "
            "run 'sm barnacle claim' first.",
            file=sys.stderr,
        )
        return 1

    agent = getattr(args, "agent", None) or _default_agent()
    resolution: Dict[str, Any] = {
        "agent": agent,
        "resolved_at": _iso_now(),
        "fix_commit": getattr(args, "commit", None),
        "fix_branch": getattr(args, "branch", None),
        "notes": getattr(args, "notes", None),
    }
    b["status"] = STATUS_RESOLVED
    b["resolution"] = resolution
    _write_barnacle(b)

    print(f"✅ Resolved {b['id']}")
    if resolution.get("fix_commit"):
        print(f"   Commit: {resolution['fix_commit']}")
    if resolution.get("fix_branch"):
        print(f"   Branch: {resolution['fix_branch']}")
    if resolution.get("notes"):
        print(f"   Notes:  {resolution['notes']}")
    print()
    repo = b.get("filed_by", {}).get("repo", "?")
    print(f"Original reporter can verify in:")
    print(f"  {repo}")
    return 0


def cmd_barnacle_watch(args: argparse.Namespace) -> int:
    """Poll the queue for new open barnacles."""
    interval = getattr(args, "interval", 15)
    status_filter = getattr(args, "status", STATUS_OPEN)

    if interval < 1:
        print("❌ --interval must be at least 1 second.", file=sys.stderr)
        return 1

    print(f"🐚 Watching barnacle queue  ({_queue_dir()})")
    print(f"   Filter: {status_filter} · interval: {interval}s · Ctrl+C to stop")
    print()

    seen: set[str] = set()
    try:
        while True:
            barnacles = _list_barnacles(status_filter)
            new = [b for b in barnacles if b["id"] not in seen]
            for b in new:
                seen.add(b["id"])
                icon = _STATUS_ICONS.get(b.get("status", ""), "❓")
                blocker = (
                    "  [BLOCKING]" if b.get("blocker_type") == BLOCKER_BLOCKING else ""
                )
                filed_by = b.get("filed_by", {})
                print(f"  {icon} {b['id']}{blocker}")
                print(f"     {b.get('command', '?')}  in  {filed_by.get('repo', '?')}")
                excerpt = b.get("actual", "")[:78]
                if excerpt:
                    print(f"     {excerpt}")
                print(f"     → sm barnacle claim {b['id']}")
                print()
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n🐚 Watch stopped.")
    return 0


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------


def cmd_barnacle(args: argparse.Namespace) -> int:
    """Dispatch barnacle subcommands."""
    action = getattr(args, "barnacle_action", None)
    dispatch = {
        "file": cmd_barnacle_file,
        "list": cmd_barnacle_list,
        "show": cmd_barnacle_show,
        "claim": cmd_barnacle_claim,
        "resolve": cmd_barnacle_resolve,
        "watch": cmd_barnacle_watch,
    }
    handler = dispatch.get(action or "")
    if not handler:
        print("Usage: sm barnacle <file|list|show|claim|resolve|watch>")
        return 2
    return handler(args)
