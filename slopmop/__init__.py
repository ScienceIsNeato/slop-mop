"""Slop-Mop: Quality gates for AI-assisted codebases."""

from slopmop._version import __version__
from slopmop.exceptions import MissingDependencyError

__all__ = ["MissingDependencyError", "__version__"]
