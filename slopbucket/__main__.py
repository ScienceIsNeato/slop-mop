"""Entry point for running slopbucket as a module.

Usage: python -m slopbucket --checks commit
"""

import sys

from slopbucket.cli import main

if __name__ == "__main__":
    sys.exit(main())
