"""Tests for the wake-angry-drunk-captain escalation CLI."""

import argparse
import json

from slopmop.cli.captain import (
    AGENT_DIRECTIVE,
    EXIT_REFUSED,
    EXIT_SUMMONED,
    SCHEMA_VERSION,
    CaptainSummons,
    build_relay_message,
    build_summons,
    cmd_captain,
    render_summons_body,
    write_summons_file,
)


def _captain_args(**kwargs) -> argparse.Namespace:
    defaults = dict(
        objective="ship the captain verb",
        verbs_tried=["sm swab — green", "sm scour — green"],
        why_stuck="no remaining verb advances; needs a product call",
        decision="approve the name wake-angry-drunk-captain",
        options=["keep the name", "rename to mayday"],
        project_root=".",
        json_output=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _summons(tmp_path, **kwargs) -> CaptainSummons:
    defaults = dict(
        objective="ship the verb",
        verbs_tried=["sm swab — green"],
        why_stuck="design call needed",
        decision="approve the name",
        options=["keep", "rename"],
        project_root=str(tmp_path),
        branch="feat/captain-verb",
        summoned_at="2026-05-29T00:00:00Z",
    )
    defaults.update(kwargs)
    return CaptainSummons(**defaults)


def test_bare_invocation_refuses_and_reads_standing_order(capsys):
    args = _captain_args(
        objective="", verbs_tried=[], why_stuck="", decision="", options=[]
    )
    code = cmd_captain(args)
    captured = capsys.readouterr()
    assert code == EXIT_REFUSED
    assert "THE CAPTAIN IS ASLEEP" in captured.err
    assert "do not wake" in captured.err.lower()
    # No artifact written when refused; stdout stays clean for --json callers.
    assert "CAPTAIN ON DECK" not in captured.out
    assert captured.out == ""


def test_partial_justification_names_missing_fields(capsys):
    args = _captain_args(why_stuck="", decision="")
    code = cmd_captain(args)
    captured = capsys.readouterr()
    assert code == EXIT_REFUSED
    # The nudge names exactly the fields left blank, not the ones provided.
    nudge = captured.err.split("left these blank:", 1)[1]
    assert "--why-stuck" in nudge
    assert "--decision" in nudge
    assert "--objective" not in nudge
    # All refusal UI stays on stderr; stdout is clean for --json callers.
    assert captured.out == ""


def test_valid_summons_halts_and_presents_case(tmp_path, capsys):
    args = _captain_args(project_root=str(tmp_path))
    code = cmd_captain(args)
    captured = capsys.readouterr()
    # A valid summons is a deliberate halt-and-await, not a failure.
    assert code == EXIT_SUMMONED
    # The captain's question is laid out for the human on stdout.
    assert "CAPTAIN ON DECK" in captured.out
    assert "approve the name wake-angry-drunk-captain" in captured.out
    artifact = tmp_path / ".slopmop" / "last_captain_summons.md"
    assert artifact.exists()
    body = artifact.read_text(encoding="utf-8")
    assert "ship the captain verb" in body


def test_valid_summons_json_output(tmp_path, capsys):
    args = _captain_args(project_root=str(tmp_path), json_output=True)
    code = cmd_captain(args)
    captured = capsys.readouterr()
    assert code == EXIT_SUMMONED
    envelope = json.loads(captured.out)
    assert envelope["schema"] == "slopmop/v3"
    assert envelope["command"] == "wake-angry-drunk-captain"
    assert envelope["status"] == "info"
    assert envelope["exit_code"] == EXIT_SUMMONED
    payload = envelope["data"]
    assert "schema" not in payload
    assert payload["outcome"] == "summoned"
    assert payload["turn_over"] is True
    assert payload["objective"] == "ship the captain verb"
    assert payload["verbs_tried"] == ["sm swab — green", "sm scour — green"]
    # The agent gets an explicit "turn over" directive and the verbatim relay.
    assert payload["agent_directive"] == AGENT_DIRECTIVE
    assert "CAPTAIN ON DECK" in payload["relay_to_human"]
    assert "approve the name wake-angry-drunk-captain" in payload["relay_to_human"]
    assert payload["summons_file"].endswith("last_captain_summons.md")
    # The machine signal to halt rides on next_steps + the info diagnostic.
    assert envelope["next_steps"][0]["action"] == "wait"
    assert envelope["diagnostics"][0]["code"] == "captain.summoned"


def test_build_summons_resolves_root_and_strips(tmp_path):
    args = _captain_args(
        project_root=str(tmp_path),
        objective="  padded objective  ",
        verbs_tried=["  sm swab — green  ", "", "   "],
    )
    summons = build_summons(args)
    assert summons.objective == "padded objective"
    assert summons.verbs_tried == ["sm swab — green"]
    assert summons.project_root == str(tmp_path.resolve())


def test_relay_message_carries_question_and_account(tmp_path):
    summons = _summons(tmp_path)
    relay = build_relay_message(summons)
    assert "THE QUESTION" in relay
    assert summons.decision in relay
    assert summons.objective in relay
    assert summons.why_stuck in relay
    # Ends on a direct ask to the human.
    assert "What's your call?" in relay


def test_render_body_handles_missing_options(tmp_path):
    summons = _summons(tmp_path, options=[])
    body = render_summons_body(summons)
    assert "captain's call is open" in body
    assert SCHEMA_VERSION in body


def test_write_summons_file_creates_parent(tmp_path):
    summons = _summons(tmp_path)
    path = write_summons_file(summons)
    assert path == tmp_path / ".slopmop" / "last_captain_summons.md"
    assert path.exists()
