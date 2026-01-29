"""Entry point for running slopmop as a module.

Usage: python -m slopmop validate commit
"""

import sys

from slopmop.sm import main

if __name__ == "__main__":
    sys.exit(main())
