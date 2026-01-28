#!/usr/bin/env python3
"""Setup script for slopbucket - AI-Focused Quality Gate Framework."""

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
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "black>=23.0.0",
    "isort>=5.12.0",
    "mypy>=1.0.0",
    "flake8>=6.0.0",
]

setup(
    name="slopbucket",
    version="1.0.0",
    author="ScienceIsNeato",
    author_email="scienceisneato@example.com",
    description="AI-Focused Quality Gate Framework",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ScienceIsNeato/slopbucket",
    packages=find_packages(exclude=["tests", "tests.*"]),
    python_requires=">=3.9",
    install_requires=requirements,
    extras_require={
        "dev": dev_requirements,
    },
    entry_points={
        "console_scripts": [
            "slopbucket=slopbucket.cli:main",
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
