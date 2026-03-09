#!/usr/bin/env python3
"""Repository convenience wrapper for CI scan triage.

Uses the package implementation so behavior matches pipx users.
"""

from slopmop.cli.scan_triage import main

if __name__ == "__main__":
    raise SystemExit(main())
