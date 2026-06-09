"""Unit tests for buff inspect scan-unavailable fallback."""

from __future__ import annotations

import argparse
from unittest.mock import Mock

from slopmop.cli import buff as buff_mod
from slopmop.cli import buff_scan
from slopmop.cli import scan_triage as triage
from slopmop.core.result import CheckStatus
from tests.conftest import make_feedback_result, patch_buff_pr_resolution


class TestBuffScanFallback:
    def test_cmd_buff_resolves_pr_when_scan_fails_before_payload(
        self, monkeypatch, capsys
    ):
        args = argparse.Namespace(
            json_output=False,
            repo=None,
            run_id=None,
            pr_number=None,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
        )

        monkeypatch.setattr(
            buff_mod,
            "run_inspect_scan",
            Mock(
                return_value=(
                    1,
                    buff_scan.build_scan_unavailable_payload(
                        pr_number=86,
                        error=(
                            "No workflow runs found for that PR/workflow. "
                            "Pass --run-id explicitly."
                        ),
                    ),
                )
            ),
        )
        monkeypatch.setattr(buff_mod, "write_json_out", Mock())
        monkeypatch.setattr(
            buff_mod,
            "_project_root_from_cwd",
            Mock(return_value="/repo"),
        )
        patch_buff_pr_resolution(monkeypatch, 86, "branch")
        feedback_gate = Mock(return_value=make_feedback_result(CheckStatus.PASSED))
        monkeypatch.setattr(buff_mod, "_run_pr_feedback_gate", feedback_gate)

        # #252 Case A: genuine absence (no code-scanning run on this repo)
        # degrades to a pass once PR feedback is resolved — nothing to verify.
        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert "PR feedback resolved" in out
        assert "no code-scanning gate" in out
        assert "Buff inspect incomplete" not in out
        feedback_gate.assert_called_once_with(86, "/repo")

    def test_cmd_buff_blocks_when_artifact_missing_from_existing_run(
        self, monkeypatch, capsys
    ):
        args = argparse.Namespace(
            json_output=False,
            repo=None,
            run_id=25540673430,
            pr_number=84,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
        )

        monkeypatch.setattr(
            buff_mod,
            "run_inspect_scan",
            Mock(
                return_value=(
                    1,
                    buff_scan.build_scan_unavailable_payload(
                        pr_number=84,
                        error=(
                            "gh command failed: gh run download 25540673430 "
                            "--name slopmop-results\n"
                            "no artifact matches any of the names or patterns provided"
                        ),
                    ),
                )
            ),
        )
        monkeypatch.setattr(buff_mod, "write_json_out", Mock())
        monkeypatch.setattr(
            buff_mod,
            "_project_root_from_cwd",
            Mock(return_value="/repo"),
        )
        patch_buff_pr_resolution(monkeypatch, 84)
        feedback_gate = Mock(return_value=make_feedback_result(CheckStatus.PASSED))
        monkeypatch.setattr(buff_mod, "_run_pr_feedback_gate", feedback_gate)

        # #252 Case B: a run exists but didn't produce the artifact — a CI
        # defect buff surfaces (blocks) instead of silently passing.
        assert buff_mod.cmd_buff(args) == 1
        out = capsys.readouterr().out
        assert "CI scan artifact unavailable" in out
        assert "did not produce the 'slopmop-results' artifact" in out
        feedback_gate.assert_called_once_with(84, "/repo")

    def test_cmd_buff_scan_fallback_still_blocks_on_review_feedback(
        self, monkeypatch, capsys
    ):
        args = argparse.Namespace(
            json_output=False,
            repo=None,
            run_id=None,
            pr_number=85,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
        )

        monkeypatch.setattr(
            buff_mod,
            "run_inspect_scan",
            Mock(
                return_value=(
                    1,
                    buff_scan.build_scan_unavailable_payload(
                        pr_number=85,
                        error=(
                            "No workflow runs found for that PR/workflow. "
                            "Pass --run-id explicitly."
                        ),
                    ),
                )
            ),
        )
        monkeypatch.setattr(buff_mod, "write_json_out", Mock())
        monkeypatch.setattr(
            buff_mod,
            "_project_root_from_cwd",
            Mock(return_value="/repo"),
        )
        patch_buff_pr_resolution(monkeypatch, 85)
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(
                return_value=make_feedback_result(
                    CheckStatus.FAILED,
                    status_detail="1 unresolved",
                    output="PR #85 has unresolved review threads.",
                    error="1 unresolved PR comment(s)",
                )
            ),
        )

        assert buff_mod.cmd_buff(args) == 1
        out = capsys.readouterr().out
        assert "CI scan artifact unavailable" in out
        assert "no code-scanning run for this repo" in out
        assert "Buff inspect found unresolved PR review threads." in out
        assert "PR #85 has unresolved review threads." in out

    def test_cmd_buff_warns_when_assuming_latest_open_pr(self, monkeypatch, capsys):
        args = argparse.Namespace(
            json_output=False,
            repo=None,
            run_id=None,
            pr_number=None,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
        )

        run_scan = Mock(
            return_value=(0, {"summary": {}, "actionable": [], "next_steps": []})
        )
        monkeypatch.setattr(buff_mod, "run_inspect_scan", run_scan)
        monkeypatch.setattr(buff_mod, "write_json_out", Mock())
        monkeypatch.setattr(buff_mod, "print_triage", Mock())
        monkeypatch.setattr(
            buff_mod,
            "_project_root_from_cwd",
            Mock(return_value="/repo"),
        )
        patch_buff_pr_resolution(monkeypatch, 90, "latest_open")
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=make_feedback_result(CheckStatus.PASSED)),
        )

        assert buff_mod.cmd_buff(args) == 0
        out = capsys.readouterr().out
        assert "Assuming most recently updated open PR #90" in out
        run_scan.assert_called_once_with(args, 90, resolved_repo="o/r")

    def test_print_scan_unavailable_handles_missing_error(self, capsys):
        buff_scan.print_scan_unavailable({"scan_unavailable": None})

        out = capsys.readouterr().out
        assert "CI scan artifact unavailable" in out
        assert "Scan detail:" not in out

    def test_cmd_buff_json_mode_blocks_when_artifact_missing(self, monkeypatch, capsys):
        args = argparse.Namespace(
            json_output=True,
            repo=None,
            run_id=None,
            pr_number=84,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
            output_file=None,
        )

        monkeypatch.setattr(
            buff_mod,
            "run_inspect_scan",
            Mock(
                return_value=(
                    1,
                    buff_scan.build_scan_unavailable_payload(
                        pr_number=84,
                        error="no artifact matches any of the names provided",
                    ),
                )
            ),
        )
        monkeypatch.setattr(buff_mod, "write_json_out", Mock())
        monkeypatch.setattr(
            buff_mod,
            "_project_root_from_cwd",
            Mock(return_value="/repo"),
        )
        patch_buff_pr_resolution(monkeypatch, 84)
        monkeypatch.setattr(
            buff_mod,
            "_run_pr_feedback_gate",
            Mock(return_value=make_feedback_result(CheckStatus.PASSED)),
        )

        # #252 Case B: a missing artifact from an existing run is a CI defect —
        # the JSON envelope reports fail, scan_unavailable kept for detail.
        assert buff_mod.cmd_buff(args) == 1
        out = capsys.readouterr().out
        assert '"scan_unavailable"' in out
        assert '"status": "fail"' in out


class TestBuffScanHelpers:
    def test_scan_unavailable_kind_distinguishes_absence_from_missing(self):
        assert (
            buff_scan.scan_unavailable_kind(
                "No workflow runs found for that PR/workflow. Pass --run-id."
            )
            == "no_workflow_run"
        )
        assert (
            buff_scan.scan_unavailable_kind(
                "no artifact matches any of the names or patterns provided"
            )
            == "artifact_missing"
        )

    def test_is_scan_unavailable_error_matches_known_missing_sources(self):
        assert buff_scan.is_scan_unavailable_error(
            triage.TriageError("No workflow runs found for that PR/workflow")
        )
        assert buff_scan.is_scan_unavailable_error(
            triage.TriageError("no valid artifacts found to download")
        )
        assert not buff_scan.is_scan_unavailable_error(
            triage.TriageError("Could not parse JSON")
        )

    def test_run_inspect_scan_success(self, monkeypatch):
        args = argparse.Namespace(
            repo=None,
            run_id=None,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
        )
        triage_runner = Mock(return_value=(0, {"summary": {}, "actionable": []}))
        monkeypatch.setattr(buff_scan, "run_triage", triage_runner)

        code, payload = buff_scan.run_inspect_scan(args, 84)

        assert code == 0
        assert payload is not None
        assert triage_runner.call_args.kwargs["repo"] is None

    def test_run_inspect_scan_uses_resolved_repo(self, monkeypatch):
        args = argparse.Namespace(
            repo=None,
            run_id=None,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
        )
        triage_runner = Mock(return_value=(0, {"summary": {}, "actionable": []}))
        monkeypatch.setattr(buff_scan, "run_triage", triage_runner)

        code, payload = buff_scan.run_inspect_scan(
            args,
            84,
            resolved_repo="o/r",
        )

        assert code == 0
        assert payload is not None
        assert triage_runner.call_args.kwargs["repo"] == "o/r"

    def test_run_inspect_scan_reraises_real_triage_errors(self, monkeypatch):
        args = argparse.Namespace(
            repo=None,
            run_id=None,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
        )
        monkeypatch.setattr(
            buff_scan,
            "run_triage",
            Mock(side_effect=triage.TriageError("Could not parse JSON")),
        )

        try:
            buff_scan.run_inspect_scan(args, 84)
        except triage.TriageError as exc:
            assert "Could not parse JSON" in str(exc)
        else:
            raise AssertionError("Expected TriageError")

    def test_run_inspect_scan_returns_scan_unavailable_payload(self, monkeypatch):
        args = argparse.Namespace(
            repo=None,
            run_id=None,
            workflow=triage.WORKFLOW_NAME,
            artifact=triage.ARTIFACT_NAME,
        )
        monkeypatch.setattr(
            buff_scan,
            "run_triage",
            Mock(
                side_effect=triage.TriageError(
                    "no artifact matches any of the names or patterns provided"
                )
            ),
        )

        code, payload = buff_scan.run_inspect_scan(args, 84)

        assert code == 1
        assert payload is not None
        assert payload["scan_unavailable"]["error"]
