"""Packaged JSON Schema documents for slop-mop's machine interface.

Schemas ship inside the package (not at repo root) so ``sm schema`` and
``sm capabilities`` resolve them via ``importlib.resources`` after a
pip/pipx install, not just from a source checkout.
"""
