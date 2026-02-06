#!/usr/bin/env python3
"""Setup script for slopmop - AI-Focused Quality Gate Framework."""

from pathlib import Path

from setuptools import find_packages, setup

# Read README for long description
readme_path = Path(__file__).parent / "README.md"
long_description = ""
if readme_path.exists():
    long_description = readme_path.read_text(encoding="utf-8")

# No external dependencies for core functionality
# Checks may require additional tools to be installed
requirements = []

dev_requirements = [
    # Testing
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "diff-cover>=7.0.0",
    "jinja2>=3.0.0",
    # Linting and formatting
    "black>=23.0.0",
    "isort>=5.12.0",
    "autoflake>=2.0.0",
    "flake8>=6.0.0",
    # Type checking
    "mypy>=1.0.0",
    "pyright>=1.1.0",
    # Security scanning
    "bandit>=1.7.0",
    "detect-secrets>=1.4.0",
    "semgrep>=1.0.0",
    "pip-audit>=2.0.0",
    # Quality analysis
    "vulture>=2.14",
]

setup(
    name="slopmop",
    version="1.0.0",
    author="ScienceIsNeato",
    author_email="scienceisneato@example.com",
    description="AI-Focused Quality Gate Framework",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ScienceIsNeato/slopmop",
    packages=find_packages(exclude=["tests", "tests.*"]),
    python_requires=">=3.9",
    install_requires=requirements,
    extras_require={
        "dev": dev_requirements,
    },
    entry_points={
        "console_scripts": [
            "sm=slopmop.sm:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Software Development :: Quality Assurance",
        "Topic :: Software Development :: Testing",
    ],
    keywords="quality-gate, linting, testing, ci-cd, code-quality",
)
