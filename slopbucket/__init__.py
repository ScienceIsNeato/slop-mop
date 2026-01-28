"""
Slopbucket — AI-optimized code validation gate.

A bolt-on quality gate framework for any repository. Designed to catch
AI-generated slop before it reaches production. Runs checks in parallel,
fails fast, and provides maximally actionable output for rapid iteration.

Usage:
    python setup.py --help          # Show available checks and profiles
    python setup.py --checks commit # Fast pre-commit validation
    python setup.py --checks pr     # Full PR validation

Add as a git submodule:
    git submodule add https://github.com/ScienceIsNeato/slopbucket.git slopbucket
    python slopbucket/setup.py --help
"""

__version__ = "0.1.0"
__author__ = "ScienceIsNeato"
