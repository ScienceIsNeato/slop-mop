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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from slopmop.reporting.envelope import (
    Diagnostic,
    NextStep,
    Status,
    build_envelope,
)
from slopmop.utils import (
    git_current_branch,
    iso_now,
    markdown_bullets,
    markdown_numbered,
)

COMMAND = "wake-angry-drunk-captain"

# Version stamp for the human-facing Markdown summons document. The machine
# JSON format is the v3 envelope, whose schema rides on the envelope itself.
SCHEMA_VERSION = "slopmop/captain-summons/v1"

# Return codes — mirror the sail "human decision needed" idiom.
EXIT_SUMMONED = 1  # Valid summons: turn is over, await the human's reply.
EXIT_REFUSED = 2  # Insufficient justification: go back to the loop.

# Placeholder rendered for an empty numbered list.
_EMPTY_NUMBERED = "1. (none provided)"

# The verbatim directive handed to the agent on a valid summons. The whole
# point of this verb is that the agent cannot resolve it alone: it surfaces
# the captain's question to the human and ends its turn. Reading stdin is
# pointless — an agent's stdin is a pipe, never a live human — so instead the
# verb hands back an explicit "your turn is over" instruction and the exact
# words to relay, the same JSON-envelope contract every other verb speaks.
AGENT_DIRECTIVE = (
    "YOUR TURN IS OVER. Show the user the text in `relay_to_human` exactly as "
    "written — verbatim, nothing added, nothing summarized, nothing after it — "
    "then STOP and wait for the human's reply. Do not run any sm verb. Do not "
    "continue the loop. The human's next message carries the captain's orders."
)


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
        ),
        file=sys.stderr,
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
        "outcome": "summoned",
        "turn_over": True,
        "summoned_at": summons.summoned_at,
        "branch": summons.branch,
        "project_root": summons.project_root,
        "objective": summons.objective,
        "verbs_tried": list(summons.verbs_tried),
        "why_stuck": summons.why_stuck,
        "decision": summons.decision,
        "options": list(summons.options),
        "summons_file": str(body_path),
        "agent_directive": AGENT_DIRECTIVE,
        "relay_to_human": build_relay_message(summons),
    }


def build_relay_message(summons: CaptainSummons) -> str:
    """Render the exact words the agent must relay to the human, verbatim.

    This is the captain's question laid in front of the human, ending on a
    direct ask. The agent does not paraphrase it — it shows this text and
    ends its turn, and the human answers in the chat.
    """
    lines = [
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
        "*The captain squints at you, swaying, and waits.*",
        '"Well? What\'s your call?"',
    ]
    return "\n".join(lines)


def cmd_captain(args: argparse.Namespace) -> int:
    """Wake the angry, drunk captain — only when the loop is truly exhausted.

    A valid summons does not resolve into more agent work: the verb hands the
    agent the captain's question and an explicit "your turn is over" directive,
    then halts. The agent relays the question to the human and waits. The agent
    cannot satisfy this verb alone — that is the point.
    """
    json_output = bool(getattr(args, "json_output", False))

    missing = _missing_fields(args)
    if missing:
        reason = (
            "Insufficient justification — the standing order stands: do not "
            "wake the captain without structured proof the loop is exhausted. "
            "Missing required field(s): " + ", ".join(missing) + "."
        )
        if json_output:
            print(
                json.dumps(
                    build_envelope(
                        command=COMMAND,
                        status=Status.ERROR,
                        exit_code=EXIT_REFUSED,
                        data={
                            "outcome": "refused",
                            "reason": reason,
                            "missing": list(missing),
                        },
                        diagnostics=[
                            Diagnostic(
                                code="captain.refused",
                                level="error",
                                message=reason,
                                suggested_command="sm refit",
                            )
                        ],
                    ),
                    indent=2,
                )
            )
            return EXIT_REFUSED
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
    relay = build_relay_message(summons)

    if json_output:
        # A valid summons is a deliberate halt-and-await, not a failure —
        # INFO carries the non-zero exit_code that signals "loop paused".
        # The agent reads the directive, relays `relay_to_human` verbatim,
        # and ends its turn; the human answers in the chat.
        print(
            json.dumps(
                build_envelope(
                    command=COMMAND,
                    status=Status.INFO,
                    exit_code=EXIT_SUMMONED,
                    data=_summons_payload(summons, body_path),
                    next_steps=[
                        NextStep(
                            action="wait",
                            reason=(
                                "Your turn is over. Relay `relay_to_human` to "
                                "the user verbatim, then wait for their reply."
                            ),
                        )
                    ],
                    diagnostics=[
                        Diagnostic(
                            code="captain.summoned",
                            level="info",
                            message=AGENT_DIRECTIVE,
                        )
                    ],
                ),
                indent=2,
            )
        )
        return EXIT_SUMMONED

    # Human running the verb directly: lay the case out, then stop. There is
    # no prompt to type into — the question stands and the human answers it.
    print(relay)
    print(f"\nLogged to: {body_path}")
    return EXIT_SUMMONED
