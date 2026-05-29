"""Buff feedback-round tracking via the ``buff-rounds/N`` PR label.

A feedback "round" is one cycle of: the reviewer leaves comments, the agent
addresses them, and ``sm buff resolve`` clears the threads. The round is
"weathered" the moment a resolve closes the last open thread. Each weathered
round bumps a ``buff-rounds/N`` label on the PR so downstream consumers (e.g.
status dashboards) can read how many rounds a PR has survived straight from
GitHub — no shared state store required.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, cast

BUFF_ROUNDS_PREFIX = "buff-rounds/"


def count_unresolved_threads(
    project_root: str, owner: str, repo: str, pr_number: int
) -> int | None:
    """Count unresolved review threads on a PR.

    Returns ``None`` when the count cannot be determined (gh missing, API
    error, malformed payload) so callers can skip side effects on uncertainty
    rather than acting on a wrong count.
    """

    query = (
        "query($owner: String!, $name: String!, $number: Int!) { "
        "repository(owner: $owner, name: $name) { "
        "pullRequest(number: $number) { "
        "reviewThreads(first: 100) { nodes { isResolved } } } } }"
    )
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                "graphql",
                "-F",
                f"owner={owner}",
                "-F",
                f"name={repo}",
                "-F",
                f"number={pr_number}",
                "-f",
                f"query={query}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
            cwd=project_root,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None
    nodes = (
        data.get("data", {})
        .get("repository", {})
        .get("pullRequest", {})
        .get("reviewThreads", {})
        .get("nodes", [])
    )
    return sum(1 for thread in nodes if not thread.get("isResolved", True))


def read_buff_rounds_label(
    project_root: str, owner: str, repo: str, pr_number: int
) -> tuple[int, list[str]]:
    """Return ``(current_round, existing_round_label_names)`` for a PR.

    ``current_round`` is the highest ``buff-rounds/N`` value already on the PR
    (0 when none), and the second element lists every ``buff-rounds/*`` label
    so the bump can clear stale ones.
    """

    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--repo",
                f"{owner}/{repo}",
                "--json",
                "labels",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
            cwd=project_root,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 0, []
    if result.returncode != 0:
        return 0, []
    try:
        raw = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return 0, []
    data = cast(dict[str, Any], raw)
    current = 0
    existing: list[str] = []
    labels = cast(list[dict[str, Any]], data.get("labels") or [])
    for label in labels:
        name = str(label.get("name", ""))
        if name.startswith(BUFF_ROUNDS_PREFIX):
            existing.append(name)
            suffix = name[len(BUFF_ROUNDS_PREFIX) :]
            if suffix.isdigit():
                current = max(current, int(suffix))
    return current, existing


def bump_buff_rounds_label(
    project_root: str, owner: str, repo: str, pr_number: int
) -> int | None:
    """Increment the ``buff-rounds/N`` label on a PR.

    Reads the current round, creates ``buff-rounds/N+1`` (idempotently), adds
    it to the PR, and removes any stale round labels. Returns the new round
    number, or ``None`` if the label could not be applied.
    """

    current, existing = read_buff_rounds_label(project_root, owner, repo, pr_number)
    new_round = current + 1
    new_label = f"{BUFF_ROUNDS_PREFIX}{new_round}"

    # Ensure the label exists in the repo so `gh pr edit --add-label` succeeds.
    subprocess.run(
        [
            "gh",
            "label",
            "create",
            new_label,
            "--repo",
            f"{owner}/{repo}",
            "--color",
            "1f6feb",
            "--description",
            "Rounds of PR feedback weathered (set by sm buff).",
            "--force",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
        cwd=project_root,
        check=False,
    )

    cmd = [
        "gh",
        "pr",
        "edit",
        str(pr_number),
        "--repo",
        f"{owner}/{repo}",
        "--add-label",
        new_label,
    ]
    for old in existing:
        if old != new_label:
            cmd.extend(["--remove-label", old])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
        cwd=project_root,
        check=False,
    )
    if result.returncode != 0:
        return None
    return new_round


def note_for_completed_round(
    project_root: str, owner: str, repo: str, pr_number: int
) -> str:
    """Stamp a weathered-round note if this resolve cleared the last thread.

    Returns ``" Round N weathered (buff-rounds/N)."`` when the resolve closed
    every open thread and the label bump succeeded, otherwise an empty string.
    Uncertainty (``count`` returns ``None``) intentionally yields no note so a
    failed lookup never fabricates a round.
    """

    remaining = count_unresolved_threads(project_root, owner, repo, pr_number)
    if remaining != 0:
        return ""
    new_round = bump_buff_rounds_label(project_root, owner, repo, pr_number)
    if new_round is None:
        return ""
    return f" Round {new_round} weathered ({BUFF_ROUNDS_PREFIX}{new_round})."
