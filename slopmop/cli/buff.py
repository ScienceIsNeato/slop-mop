"""Post-PR buffing command.

`sm buff` is CI-first post-submit orchestration:
- read latest CI code-scan results
- summarize actionable status
- direct the next local fix/recheck loop
"""

from __future__ import annotations

import argparse
import json
import os

from slopmop.checks.pr.comments import PRCommentsCheck
from slopmop.cli.scan_triage import (
    TriageError,
    print_triage,
    run_triage,
    write_json_out,
)
from slopmop.core.result import CheckResult, CheckStatus


def _run_pr_feedback_gate(pr_number: int | None) -> CheckResult:
    """Run ignored-feedback gate in blocking mode for buff semantics."""

    check = PRCommentsCheck({"fail_on_unresolved": True})
    original_pr_env = os.environ.get("GITHUB_PR_NUMBER")

    try:
        if pr_number is not None:
            os.environ["GITHUB_PR_NUMBER"] = str(pr_number)
        return check.run(os.getcwd())
    finally:
        if pr_number is not None:
            if original_pr_env is None:
                os.environ.pop("GITHUB_PR_NUMBER", None)
            else:
                os.environ["GITHUB_PR_NUMBER"] = original_pr_env


def cmd_buff(args: argparse.Namespace) -> int:
    """Run post-PR CI triage and return non-zero on unresolved signals."""

    if not getattr(args, "json_output", False):
        print("== Buff: checking CI code-scanning results ==")

    try:
        scan_exit, payload = run_triage(
            repo=args.repo,
            run_id=args.run_id,
            pr_number=args.pr_number,
            workflow=args.workflow,
            artifact=args.artifact,
            show_low_coverage=False,
            json_out=None,
            print_output=False,
        )
    except TriageError as exc:
        print(f"ERROR: {exc}")
        return 1

    if payload is None:
        print("ERROR: CI triage produced no payload.")
        return 1

    feedback_result = _run_pr_feedback_gate(args.pr_number)
    payload["pr_feedback"] = {
        "gate": "myopia:ignored-feedback",
        "status": feedback_result.status.value,
        "status_detail": feedback_result.status_detail,
        "error": feedback_result.error,
        "fix_suggestion": feedback_result.fix_suggestion,
    }

    write_json_out(getattr(args, "output_file", None), payload)

    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2))
    else:
        print_triage(payload, show_low_coverage=False)

    feedback_blocking = feedback_result.status in {
        CheckStatus.FAILED,
        CheckStatus.ERROR,
    }

    if scan_exit != 0 or feedback_blocking:
        if not getattr(args, "json_output", False):
            if scan_exit != 0:
                print("\nBuff failed: unresolved CI scan signals remain.")
            if feedback_result.status == CheckStatus.FAILED:
                print("Buff failed: unresolved PR review threads remain.")
                if feedback_result.output:
                    print(feedback_result.output)
            elif feedback_result.status == CheckStatus.ERROR:
                print("Buff failed: could not verify unresolved PR feedback.")
                if feedback_result.error:
                    print(f"ERROR: {feedback_result.error}")
        return 1

    if not getattr(args, "json_output", False):
        print("\nBuff clean: CI scan signals are resolved.")
    return 0
