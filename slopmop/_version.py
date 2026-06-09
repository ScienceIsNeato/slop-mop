"""Single source of truth for the slop-mop version.

Bump **only this value** to change the version — the release workflow does it
automatically. Everything else derives from it:

- ``pyproject.toml`` reads it via ``[tool.setuptools.dynamic]``.
- ``slopmop/__init__.py`` re-exports it as ``slopmop.__version__``.
- ``scripts/sync_version.py`` propagates it into the docs that state the
  current version.
- ``tests/unit/test_version_consistency.py`` fails CI if any of those drift
  from this value, so a mismatch can never be merged.
"""

__version__ = "2.3.1"
