"""Wake the angry, drunk captain — the agent's last-resort escalation verb.

Every other verb (``swab``, ``scour``, ``buff``, ``sail``) assumes there is
more *agent* work to do.  This one models the case the loop never had: the
barnacles are filed, the gates are green or genuinely unfixable, and the only
move left is a human judgment call.

The standing order is *"do not wake the captain unless there's an emergency."*
The captain is asleep.  He is angry.  He is drunk.  He went to bed because the
crew swore they had it handled.  Waking him is supposed to feel expensive —
that friction is the whole point.  An agent that reaches for this verb to dodge
hard work should picture his face first.

So the verb refuses to escalate on a whim.  A bare invocation gets the standing
order read back to it.  Escalation only happens when the agent supplies
structured proof that the loop is exhausted: what it was trying to do, which
verbs it already ran and how they died, why nothing remaining makes progress,
and the single decision only a human can make.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from slopmop.utils import (
    git_current_branch,
    iso_now,
    markdown_bullets,
    markdown_numbered,
)

SCHEMA_VERSION = "slopmop/captain-summons/v1"

# Return codes — mirror the sail "human decision needed" idiom.
EXIT_SUMMONED = 1  # Valid summons: captain spoke, loop halted, await orders.
EXIT_REFUSED = 2  # Insufficient justification: go back to the loop.
EXIT_NO_CAPTAIN = 3  # No human at the wheel: run this where one can answer.

# Max times to re-prompt a silent captain before giving up.
_MAX_PROMPT_ATTEMPTS = 3

# Placeholder rendered for an empty numbered list.
_EMPTY_NUMBERED = "1. (none provided)"


def _default_summons_file(project_root: str) -> Path:
    return Path(project_root) / ".slopmop" / "last_captain_summons.md"


@dataclass(frozen=True)
class CaptainSummons:
    """Structured payload justifying why a human must be woken."""

    objective: str
    verbs_tried: Sequence[str]
    why_stuck: str
    decision: str
    options: Sequence[str]
    project_root: str
    branch: str
    summoned_at: str
    orders: Sequence[str] = ()
    answered_at: Optional[str] = None


def _clean_lines(values: Sequence[str]) -> List[str]:
    return [value.strip() for value in values if value and value.strip()]


def _missing_fields(args: argparse.Namespace) -> List[str]:
    """Return the names of required justification fields the agent skipped."""
    missing: List[str] = []
    if not (getattr(args, "objective", "") or "").strip():
        missing.append("--objective")
    if not _clean_lines(getattr(args, "verbs_tried", None) or []):
        missing.append("--verbs-tried")
    if not (getattr(args, "why_stuck", "") or "").strip():
        missing.append("--why-stuck")
    if not (getattr(args, "decision", "") or "").strip():
        missing.append("--decision")
    return missing


def _print_standing_order() -> None:
    """Read the standing order back to an agent that came empty-handed."""
    print(
        "\n".join(
            [
                "",
                "🥃 THE CAPTAIN IS ASLEEP",
                "",
                'Standing order: "Do not wake me unless there\'s an emergency."',
                "",
                "He is angry. He is drunk. The crew swore they had it handled.",
                "Bring proof or do not knock. Required:",
                "",
                "  --objective     What you were trying to get done.",
                "  --verbs-tried   Each sm verb you ran and how it died.",
                "                  Repeat the flag — one per attempt.",
                "  --why-stuck     Why NO remaining sm verb moves you forward.",
                "  --decision      The one call only the captain can make.",
                "",
                "Optional:",
                "  --option        A choice you've laid out. Repeat per option.",
                "",
                "Miss one line and you do not have an emergency — you have",
                "unfinished work. Back to the loop:",
                "",
                "    sm sail",
                "",
            ]
        )
    )


def build_summons(args: argparse.Namespace) -> CaptainSummons:
    """Build a normalized captain summons from parsed CLI arguments."""
    project_root = str(Path(getattr(args, "project_root", ".")).resolve())
    return CaptainSummons(
        objective=(getattr(args, "objective", "") or "").strip(),
        verbs_tried=_clean_lines(getattr(args, "verbs_tried", None) or []),
        why_stuck=(getattr(args, "why_stuck", "") or "").strip(),
        decision=(getattr(args, "decision", "") or "").strip(),
        options=_clean_lines(getattr(args, "options", None) or []),
        project_root=project_root,
        branch=git_current_branch(project_root),
        summoned_at=iso_now(),
    )


def render_summons_body(summons: CaptainSummons) -> str:
    """Render the summons as structured Markdown for the human captain."""
    lines = [
        "# 🥃 Captain Summons",
        "",
        f"- Schema: {SCHEMA_VERSION}",
        f"- Summoned: {summons.summoned_at}",
        f"- Branch: {summons.branch}",
        f"- Repo: {summons.project_root}",
        "",
        "## Objective",
        summons.objective or "(none provided)",
        "",
        "## Verbs Tried (and how each one died)",
        markdown_numbered(summons.verbs_tried, _EMPTY_NUMBERED),
        "",
        "## Why the loop can't continue",
        summons.why_stuck or "(none provided)",
        "",
        "## The decision only the captain can make",
        summons.decision or "(none provided)",
        "",
        "## Options on the table",
        markdown_bullets(
            summons.options, "- (none on the table — captain's call is open)"
        ),
        "",
    ]
    if summons.orders:
        lines += [
            f"## Captain's Orders ({summons.answered_at or 'unrecorded'})",
            markdown_numbered(summons.orders, _EMPTY_NUMBERED),
            "",
        ]
    return "\n".join(lines)


def write_summons_file(summons: CaptainSummons, body: Optional[str] = None) -> Path:
    """Write the rendered summons to a retrievable Markdown artifact."""
    path = _default_summons_file(summons.project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        body if body is not None else render_summons_body(summons),
        encoding="utf-8",
    )
    return path


def _summons_payload(summons: CaptainSummons, body_path: Path) -> Dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "summoned_at": summons.summoned_at,
        "answered_at": summons.answered_at,
        "branch": summons.branch,
        "project_root": summons.project_root,
        "objective": summons.objective,
        "verbs_tried": list(summons.verbs_tried),
        "why_stuck": summons.why_stuck,
        "decision": summons.decision,
        "options": list(summons.options),
        "orders": list(summons.orders),
        "summons_file": str(body_path),
    }


def _present_case(summons: CaptainSummons) -> None:
    """Lay the agent's case in front of the captain (stderr, always shown)."""
    lines = [
        "",
        "🥃 CAPTAIN ON DECK",
        "",
        "*A deckhand shakes the captain awake, hat in hand.*",
        '"Aye, terribly sorry to wake ya, captain — but none of the officers',
        '   know what to do about the following:"',
        "",
        "THE QUESTION",
        f"   {summons.decision}",
    ]
    if summons.options:
        lines += ["", "Options on the table"]
        lines += [f"   - {option}" for option in summons.options]
    lines += [
        "",
        "— the crew's account of how it came to this —",
        "",
        "What we were trying to do",
        f"   {summons.objective}",
        "",
        "Verbs tried (and how they died)",
    ]
    for idx, verb in enumerate(summons.verbs_tried, 1):
        lines.append(f"   {idx}. {verb}")
    lines += [
        "",
        "Why the loop can't continue",
        f"   {summons.why_stuck}",
        "",
    ]
    print("\n".join(lines), file=sys.stderr)


def _collect_captain_orders(
    input_fn: Optional[Callable[[str], str]] = None,
    isatty_fn: Optional[Callable[[], bool]] = None,
) -> Optional[List[str]]:
    """Block until the human captain types orders.

    Returns the typed order lines, or ``None`` when no human is at the wheel
    (non-interactive stdin, or the captain ends input without a word).
    """
    resolved_input: Callable[[str], str] = input_fn if input_fn is not None else input
    resolved_isatty: Callable[[], bool] = (
        isatty_fn if isatty_fn is not None else sys.stdin.isatty
    )

    if not resolved_isatty():
        return None

    prompt = (
        '"What\'s your call, captain?"\n'
        "(type your orders — blank line when you're done)\n> "
    )
    silent_retry = (
        "\"...Still nothing, captain? The crew's waiting on your word.\n"
        ' Give the order, or we send them back to the loop empty-handed."\n> '
    )

    for _ in range(_MAX_PROMPT_ATTEMPTS):
        orders: List[str] = []
        current = prompt
        while True:
            try:
                line = resolved_input(current)
            except EOFError:
                line = ""
                # EOF ends collection; fall through to evaluate what we have.
                if orders:
                    return orders
                break
            if not line.strip():
                if orders:
                    return orders
                break  # Empty first line — re-prompt sternly.
            orders.append(line.strip())
            current = "> "
        prompt = silent_retry

    return None


def cmd_captain(
    args: argparse.Namespace,
    input_fn: Optional[Callable[[str], str]] = None,
    isatty_fn: Optional[Callable[[], bool]] = None,
) -> int:
    """Wake the angry, drunk captain — only when the loop is truly exhausted.

    A valid summons does not resolve until a human at the keyboard types
    orders. The agent cannot satisfy this verb alone — that is the point.
    """
    missing = _missing_fields(args)
    if missing:
        _print_standing_order()
        if len(missing) < 4:
            # Came partway — name exactly what's still missing.
            print(
                "You started to make your case but left these blank: "
                + ", ".join(missing),
                file=sys.stderr,
            )
        return EXIT_REFUSED

    summons = build_summons(args)
    body_path = write_summons_file(summons, render_summons_body(summons))

    # Lay the case in front of the captain, then demand his orders.
    _present_case(summons)
    orders = _collect_captain_orders(input_fn=input_fn, isatty_fn=isatty_fn)

    if not orders:
        print(
            "\n".join(
                [
                    "",
                    "🥃 NO CAPTAIN AT THE WHEEL",
                    "",
                    "You hollered into an empty cabin — nobody's here to answer.",
                    "This verb only resolves when a human types orders at the",
                    "prompt. Run it where the captain can answer — an interactive",
                    "terminal, with him at the keyboard. Nothing was decided.",
                    "",
                ]
            ),
            file=sys.stderr,
        )
        return EXIT_NO_CAPTAIN

    summons = replace(summons, orders=orders, answered_at=iso_now())
    body_path = write_summons_file(summons, render_summons_body(summons))

    if getattr(args, "json_output", False):
        print(json.dumps(_summons_payload(summons, body_path), indent=2))
        return EXIT_SUMMONED

    ack = [
        "",
        "🥃 ORDERS RECEIVED — the captain has spoken",
        "",
    ]
    for idx, order in enumerate(orders, 1):
        ack.append(f"   {idx}. {order}")
    ack += [
        "",
        f"Logged to: {body_path}",
        "",
        '"You have your orders. Carry them out. And do NOT wake me again"',
        "   *...he mutters, stumbling back to his bunk.*",
        "",
    ]
    print("\n".join(ack))
    return EXIT_SUMMONED
