"""Tests for the wake-angry-drunk-captain escalation CLI."""

import argparse
import json

from slopmop.cli.captain import (
    EXIT_NO_CAPTAIN,
    EXIT_REFUSED,
    EXIT_SUMMONED,
    SCHEMA_VERSION,
    CaptainSummons,
    build_summons,
    cmd_captain,
    render_summons_body,
    write_summons_file,
)


def _scripted_captain(*lines):
    """Return an input() stand-in that feeds the given lines, then EOF."""
    queue = list(lines)

    def _input(_prompt=""):
        if not queue:
            raise EOFError
        return queue.pop(0)

    return _input


def _at_the_wheel():
    return True


def _no_wheel():
    return False


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


def test_valid_summons_requires_orders_and_halts(tmp_path, capsys):
    args = _captain_args(project_root=str(tmp_path))
    code = cmd_captain(
        args,
        input_fn=_scripted_captain("hold the merge", "rename later", ""),
        isatty_fn=_at_the_wheel,
    )
    captured = capsys.readouterr()
    assert code == EXIT_SUMMONED
    # The case is presented to the captain on stderr.
    assert "CAPTAIN ON DECK" in captured.err
    # Orders acknowledged on stdout.
    assert "ORDERS RECEIVED" in captured.out
    assert "hold the merge" in captured.out
    artifact = tmp_path / ".slopmop" / "last_captain_summons.md"
    assert artifact.exists()
    body = artifact.read_text(encoding="utf-8")
    assert "ship the captain verb" in body
    assert "Captain's Orders" in body
    assert "hold the merge" in body
    assert "rename later" in body


def test_no_captain_at_the_wheel_refuses(tmp_path, capsys):
    args = _captain_args(project_root=str(tmp_path))
    code = cmd_captain(args, isatty_fn=_no_wheel)
    captured = capsys.readouterr()
    assert code == EXIT_NO_CAPTAIN
    assert "NO CAPTAIN AT THE WHEEL" in captured.err
    # Nothing decided: no orders recorded in the artifact.
    artifact = tmp_path / ".slopmop" / "last_captain_summons.md"
    body = artifact.read_text(encoding="utf-8")
    assert "Captain's Orders" not in body


def test_silent_captain_eventually_refuses(tmp_path, capsys):
    args = _captain_args(project_root=str(tmp_path))
    # Captain stares at the prompt, types nothing, then walks off (EOF).
    code = cmd_captain(
        args,
        input_fn=_scripted_captain("", "", ""),
        isatty_fn=_at_the_wheel,
    )
    captured = capsys.readouterr()
    assert code == EXIT_NO_CAPTAIN
    assert "NO CAPTAIN AT THE WHEEL" in captured.err


def test_valid_summons_json_output(tmp_path, capsys):
    args = _captain_args(project_root=str(tmp_path), json_output=True)
    code = cmd_captain(
        args,
        input_fn=_scripted_captain("approved", ""),
        isatty_fn=_at_the_wheel,
    )
    captured = capsys.readouterr()
    assert code == EXIT_SUMMONED
    envelope = json.loads(captured.out)
    assert envelope["schema"] == "slopmop/v3"
    assert envelope["command"] == "wake-angry-drunk-captain"
    assert envelope["status"] == "info"
    assert envelope["exit_code"] == EXIT_SUMMONED
    payload = envelope["data"]
    assert "schema" not in payload
    assert payload["objective"] == "ship the captain verb"
    assert payload["verbs_tried"] == ["sm swab — green", "sm scour — green"]
    assert payload["orders"] == ["approved"]
    assert payload["answered_at"]
    assert payload["summons_file"].endswith("last_captain_summons.md")


def test_no_captain_json_output(tmp_path, capsys):
    """No human at the wheel + --json emits the no_captain error envelope."""
    args = _captain_args(project_root=str(tmp_path), json_output=True)
    code = cmd_captain(args, isatty_fn=_no_wheel)
    assert code == EXIT_NO_CAPTAIN
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["command"] == "wake-angry-drunk-captain"
    assert envelope["status"] == "error"
    assert envelope["exit_code"] == EXIT_NO_CAPTAIN
    assert envelope["data"]["outcome"] == "no_captain"
    assert envelope["diagnostics"][0]["code"] == "captain.no_human"


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
