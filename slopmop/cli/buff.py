"""Post-PR buffing command.

`sm buff` is CI-first post-submit orchestration:
- read latest CI code-scan results
- summarize actionable status
- direct the next local fix/recheck loop
"""

from __future__ import annotations

import argparse
import json

from slopmop.cli.scan_triage import (
    TriageError,
    print_triage,
    run_triage,
    write_json_out,
)


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

    write_json_out(getattr(args, "output_file", None), payload)

    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2))
    else:
        print_triage(payload, show_low_coverage=False)

    if scan_exit != 0:
        if not getattr(args, "json_output", False):
            print("\nBuff failed: unresolved CI scan signals remain.")
        return 1

    if not getattr(args, "json_output", False):
        print("\nBuff clean: CI scan signals are resolved.")
    return 0
