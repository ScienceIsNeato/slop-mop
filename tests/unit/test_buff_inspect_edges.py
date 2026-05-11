"""Focused edge tests for buff inspect argument and feedback handling."""

from __future__ import annotations

import argparse
from unittest.mock import Mock

from slopmop.cli import buff as buff_mod
from slopmop.cli import scan_triage as triage
from slopmop.core.result import CheckStatus
from tests.conftest import make_feedback_result, patch_buff_pr_resolution


def _inspect_args(**overrides) -> argparse.Namespace:
    defaults = {
        "json_output": False,
        "repo": None,
        "run_id": None,
        "pr_number": 84,
        "workflow": triage.WORKFLOW_NAME,
        "artifact": triage.ARTIFACT_NAME,
        "output_file": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_cmd_buff_rejects_non_integer_inspect_pr(capsys):
    args = argparse.Namespace(
        pr_or_action="inspect",
        action_args=["notint"],
    )

    assert buff_mod.cmd_buff(args) == 2
    assert "PR number must be an integer" in capsys.readouterr().out


def test_cmd_buff_rejects_extra_inspect_pr_args(capsys):
    args = argparse.Namespace(
        pr_or_action="inspect",
        action_args=["84", "85"],
    )

    assert buff_mod.cmd_buff(args) == 2
    assert "buff inspect accepts at most one PR number" in capsys.readouterr().out


def test_cmd_buff_rejects_extra_status_pr_args(capsys):
    args = argparse.Namespace(
        pr_or_action="status",
        action_args=["84", "85"],
        interval=30,
        fail_fast=False,
    )

    assert buff_mod.cmd_buff(args) == 2
    assert "buff status accepts at most one PR number" in capsys.readouterr().out


def test_cmd_buff_reports_pr_feedback_error(monkeypatch, capsys):
    args = _inspect_args()

    monkeypatch.setattr(
        buff_mod,
        "run_inspect_scan",
        Mock(return_value=(0, {"summary": {}, "actionable": [], "next_steps": []})),
    )
    monkeypatch.setattr(buff_mod, "write_json_out", Mock())
    monkeypatch.setattr(buff_mod, "print_triage", Mock())
    monkeypatch.setattr(
        buff_mod,
        "_project_root_from_cwd",
        Mock(return_value="/repo"),
    )
    patch_buff_pr_resolution(monkeypatch, 84)
    monkeypatch.setattr(
        buff_mod,
        "_run_pr_feedback_gate",
        Mock(
            return_value=make_feedback_result(
                CheckStatus.ERROR,
                error="feedback lookup failed",
            )
        ),
    )

    assert buff_mod.cmd_buff(args) == 1
    out = capsys.readouterr().out
    assert "Buff inspect failed: could not verify unresolved PR feedback." in out
    assert "ERROR: feedback lookup failed" in out
