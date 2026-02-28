"""Entry point for running slopmop as a module.

Usage: python -m slopmop swab
"""

import sys

from slopmop.sm import main

if __name__ == "__main__":
    sys.exit(main())
