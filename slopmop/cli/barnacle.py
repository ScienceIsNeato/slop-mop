"""Barnacle issue intake for slop-mop tool-friction reports.

A barnacle is a defect or friction point in slop-mop itself, discovered while
using the tool in a real repository. Barnacles are one-way upstream reports:
``sm barnacle file`` creates a structured GitHub issue in the slop-mop repo.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse, urlunparse

from slopmop.utils import git_current_branch, iso_now

SCHEMA_VERSION = "slopmop/barnacle-issue/v1"
DEFAULT_REPO = "ScienceIsNeato/slop-mop"
DEFAULT_LABELS = ("barnacle", "bug")
BLOCKER_BLOCKING = "blocking"
AUTO_FILE_DISABLED_ENVAR = "SLOPMOP_DISABLE_BARNACLE_AUTO_FILE"

HELP_AGENT = "Agent identifier (default: user@hostname)"
_BARNACLE_PREFIX_RE = re.compile(r"^\[barnacle\]\s*", re.IGNORECASE)
_REDACTED = "(redacted; pass --include-sensitive-metadata to include)"


@dataclass(frozen=True)
class BarnacleIssue:
    """Structured payload for a barnacle issue."""

    title: str
    command: str
    expected: str
    actual: str
    output_excerpt: str
    blocker_type: str
    workflow: str
    project_root: str
    gate: Optional[str]
    agent: str
    repo: str
    labels: Sequence[str]
    reproduction_steps: Sequence[str]
    things_tried: Sequence[str]
    metadata: Dict[str, Any]
    include_sensitive_metadata: bool = False


def _default_agent() -> str:
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
    host = socket.gethostname()
    return f"{user}@{host}"


def _installed_slopmop_version() -> str:
    try:
        from importlib.metadata import version  # noqa: PLC0415

        return version("slopmop")
    except Exception:
        return "unknown"


def _run_git(project_root: str, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _git_dirty(project_root: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return False
    return bool(result.stdout.strip())


def _redact_url(url: str) -> str:
    """Strip embedded credentials from a git remote URL.

    Only HTTPS/HTTP URLs can carry embedded credentials; SSH ``git@`` URLs
    do not contain real secrets and are returned unchanged.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme in ("http", "https") and (parsed.username or parsed.password):
            netloc = parsed.hostname or ""
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            return urlunparse(
                (
                    parsed.scheme,
                    netloc,
                    parsed.path,
                    parsed.params,
                    parsed.query,
                    parsed.fragment,
                )
            )
    except Exception:
        pass
    return url


def _repo_metadata(root: str, include_sensitive: bool) -> Dict[str, Any]:
    if not include_sensitive:
        return {
            "root": _REDACTED,
            "remote": _REDACTED,
            "branch": _REDACTED,
            "commit": _REDACTED,
            "dirty": _git_dirty(root),
        }
    return {
        "root": root,
        "remote": _redact_url(_run_git(root, "config", "--get", "remote.origin.url")),
        "branch": git_current_branch(root),
        "commit": _run_git(root, "rev-parse", "HEAD"),
        "dirty": _git_dirty(root),
    }


def _collect_metadata(
    project_root: str, agent: str, include_sensitive: bool = False
) -> Dict[str, Any]:
    """Collect environment metadata for a barnacle issue.

    By default only non-sensitive fields are included.  Pass
    ``include_sensitive=True`` (via ``--include-sensitive-metadata``) to also
    include the remote URL (with credentials redacted), the HEAD commit SHA,
    and the current working directory.
    """
    root = str(Path(project_root).resolve())
    metadata: Dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "filed_at": iso_now(),
        "slopmop_version": _installed_slopmop_version(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "cwd": os.getcwd() if include_sensitive else _REDACTED,
        "repo": _repo_metadata(root, include_sensitive),
        "agent": {
            "name": agent,
            "source": os.environ.get("SLOPMOP_AGENT_SOURCE", "unknown"),
        },
    }
    return metadata


def _fenced_block(language: str, content: str) -> str:
    body = content.strip() or "(none provided)"
    return f"```{language}\n{body}\n```"


def _bullets(values: Sequence[str]) -> str:
    cleaned = [value.strip() for value in values if value and value.strip()]
    if not cleaned:
        return "- (none provided)"
    return "\n".join(f"- {value}" for value in cleaned)


def _numbered(values: Sequence[str]) -> str:
    cleaned = [value.strip() for value in values if value and value.strip()]
    if not cleaned:
        return "1. (none provided)"
    return "\n".join(f"{idx}. {value}" for idx, value in enumerate(cleaned, 1))


def _issue_title(raw_title: str, command: str) -> str:
    title = raw_title.strip() or f"slop-mop friction while running {command}"
    if _BARNACLE_PREFIX_RE.match(title):
        return title
    return f"[barnacle] {title}"


def _issue_summary(title: str) -> str:
    return _BARNACLE_PREFIX_RE.sub("", title).strip() or title


def build_barnacle_issue(args: argparse.Namespace) -> BarnacleIssue:
    """Build a normalized barnacle issue from parsed CLI arguments."""
    project_root = str(Path(getattr(args, "project_root", ".")).resolve())
    agent = getattr(args, "agent", None) or _default_agent()
    command = getattr(args, "command", "") or ""
    labels = tuple(getattr(args, "labels", None) or DEFAULT_LABELS)
    include_sensitive = bool(getattr(args, "include_sensitive_metadata", False))
    return BarnacleIssue(
        title=_issue_title(getattr(args, "title", "") or "", command),
        command=command,
        expected=getattr(args, "expected", "") or "",
        actual=getattr(args, "actual", "") or "",
        output_excerpt=getattr(args, "output_excerpt", "") or "",
        blocker_type=getattr(args, "blocker_type", BLOCKER_BLOCKING),
        workflow=getattr(args, "workflow", "unknown") or "unknown",
        project_root=project_root,
        gate=getattr(args, "gate", None),
        agent=agent,
        repo=getattr(args, "repo", DEFAULT_REPO) or DEFAULT_REPO,
        labels=labels,
        reproduction_steps=getattr(args, "reproduction_steps", None) or [command],
        things_tried=getattr(args, "things_tried", None) or [],
        metadata=_collect_metadata(project_root, agent, include_sensitive),
        include_sensitive_metadata=include_sensitive,
    )


def render_issue_body(issue: BarnacleIssue) -> str:
    """Render the barnacle issue body as structured Markdown."""
    gate_line = f"\n- Gate: {issue.gate}" if issue.gate else ""
    source_repo = issue.project_root if issue.include_sensitive_metadata else _REDACTED
    return "\n".join(
        [
            "### Barnacle Summary",
            _issue_summary(issue.title),
            "",
            "### Current Behavior",
            issue.actual or "(none provided)",
            "",
            "### Expected Behavior",
            issue.expected or "(none provided)",
            "",
            "### Command",
            _fenced_block("bash", issue.command),
            "",
            "### Reproduction Steps",
            _numbered(issue.reproduction_steps),
            "",
            "### Things Tried",
            _bullets(issue.things_tried),
            "",
            "### Output Excerpt",
            _fenced_block("text", issue.output_excerpt),
            "",
            "### Impact",
            "- Barnacle: true",
            f"- Blocker Type: {issue.blocker_type}",
            f"- Affected Workflow: {issue.workflow}",
            f"- Source Repository: {source_repo}{gate_line}",
            "",
            "### Environment Metadata",
            _fenced_block("json", json.dumps(issue.metadata, indent=2, sort_keys=True)),
            "",
        ]
    )


def _default_body_file(issue: BarnacleIssue) -> Path:
    return Path(issue.project_root) / ".slopmop" / "last_barnacle_issue.md"


def write_issue_body_file(
    issue: BarnacleIssue, body_file: Optional[str] = None, body: Optional[str] = None
) -> Path:
    """Write the rendered issue body to a retryable Markdown artifact."""
    path = Path(body_file) if body_file else _default_body_file(issue)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        body if body is not None else render_issue_body(issue), encoding="utf-8"
    )
    return path


def _issue_create_command(
    issue: BarnacleIssue, labels: Sequence[str], body_file: Path
) -> List[str]:
    command = [
        "gh",
        "issue",
        "create",
        "--repo",
        issue.repo,
        "--title",
        issue.title,
        "--body-file",
        str(body_file),
    ]
    for label in labels:
        command.extend(["--label", label])
    return command


def create_barnacle_issue(
    issue: BarnacleIssue, body_file: Optional[str] = None, body: Optional[str] = None
) -> Tuple[subprocess.CompletedProcess[str], Path]:
    """Create the GitHub issue, retrying without the barnacle label if needed."""
    issue_body_path = write_issue_body_file(issue, body_file, body)
    try:
        result = subprocess.run(
            _issue_create_command(issue, issue.labels, issue_body_path),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("GitHub CLI `gh` is required to file barnacles") from exc

    missing_label = result.returncode != 0 and "barnacle" in result.stderr.lower()
    if not missing_label or "barnacle" not in issue.labels:
        return result, issue_body_path

    fallback_labels = tuple(label for label in issue.labels if label != "barnacle")
    return (
        subprocess.run(
            _issue_create_command(issue, fallback_labels, issue_body_path),
            capture_output=True,
            text=True,
            check=False,
        ),
        issue_body_path,
    )


def _print_json(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def cmd_barnacle_file(args: argparse.Namespace) -> int:
    """File a structured barnacle issue upstream."""
    issue = build_barnacle_issue(args)
    body = render_issue_body(issue)
    body_file = getattr(args, "body_file", None)
    if getattr(args, "dry_run", False):
        body_path = write_issue_body_file(issue, body_file, body)
        if getattr(args, "json_output", False):
            _print_json(
                {
                    "title": issue.title,
                    "repo": issue.repo,
                    "labels": list(issue.labels),
                    "body_file": str(body_path),
                    "body": body,
                }
            )
            return 0
        print(f"Title: {issue.title}")
        print(f"Repo: {issue.repo}")
        print(f"Labels: {', '.join(issue.labels)}")
        print(f"Body file: {body_path}")
        print()
        print(body)
        return 0

    try:
        result, body_path = create_barnacle_issue(issue, body_file, body)
    except RuntimeError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        print("Re-run with --dry-run to capture the issue body.", file=sys.stderr)
        return 1

    if result.returncode != 0:
        print("❌ Failed to file barnacle issue", file=sys.stderr)
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        print(f"Issue body preserved at: {body_path}", file=sys.stderr)
        return result.returncode

    url = result.stdout.strip()
    if getattr(args, "json_output", False):
        _print_json(
            {
                "title": issue.title,
                "repo": issue.repo,
                "labels": list(issue.labels),
                "body_file": str(body_path),
                "url": url,
            }
        )
        return 0

    print("🐚 Barnacle issue filed")
    if url:
        print(url)
    print(f"Body file: {body_path}")
    return 0


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
    workflow: str = "unknown",
) -> Optional[str]:
    """Best-effort compatibility wrapper that files a barnacle issue."""
    if os.environ.get(AUTO_FILE_DISABLED_ENVAR):
        return None
    args = argparse.Namespace(
        title="automated slop-mop friction report",
        command=command,
        gate=gate,
        expected=expected,
        actual=actual,
        output_excerpt=output_excerpt,
        blocker_type=blocker_type,
        project_root=project_root or ".",
        reproduction_steps=reproduction_steps or [command],
        things_tried=[],
        workflow=workflow,
        agent=None,
        repo=DEFAULT_REPO,
        labels=list(DEFAULT_LABELS),
        dry_run=False,
        body_file=None,
        json_output=False,
        include_sensitive_metadata=False,
    )
    try:
        issue = build_barnacle_issue(args)
        result, _body_path = create_barnacle_issue(issue)
    except Exception:
        return None
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    if url.startswith(("http://", "https://")):
        return url
    return None


def cmd_barnacle(args: argparse.Namespace) -> int:
    """Dispatch barnacle subcommands."""
    action = getattr(args, "barnacle_action", None)
    if action in {"file", "describe"}:
        if action == "describe":
            print(
                "sm barnacle describe is deprecated; use sm barnacle file.",
                file=sys.stderr,
            )
        return cmd_barnacle_file(args)
    print("Usage: sm barnacle file --command <cmd> --expected <text> --actual <text>")
    return 2
