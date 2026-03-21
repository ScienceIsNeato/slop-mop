"""Slop-Mop: Quality gates for AI-assisted codebases."""

from importlib.metadata import version as _pkg_version

from slopmop.exceptions import MissingDependencyError

__version__ = _pkg_version("slopmop")

__all__ = ["MissingDependencyError", "__version__"]
