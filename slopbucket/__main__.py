"""Entry point for running slopbucket as a module.

Usage: python -m slopbucket validate commit
"""

import sys

from slopbucket.sb import main

if __name__ == "__main__":
    sys.exit(main())
