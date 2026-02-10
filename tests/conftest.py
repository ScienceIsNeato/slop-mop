"""Pytest configuration and fixtures for slopmop tests."""

from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture
def temp_project(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary project directory with Python files."""
    # Create a minimal Python project
    (tmp_path / "setup.py").write_text("# setup")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("")
    (tmp_path / "src" / "main.py").write_text(
        '''"""Main module."""

def hello() -> str:
    """Return greeting."""
    return "Hello, World!"
'''
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "__init__.py").write_text("")
    (tmp_path / "tests" / "test_main.py").write_text(
        '''"""Tests for main."""

from src.main import hello


def test_hello():
    """Test hello function."""
    assert hello() == "Hello, World!"
'''
    )

    yield tmp_path


@pytest.fixture
def temp_js_project(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary JavaScript project directory."""
    # Create a minimal JS project
    (tmp_path / "package.json").write_text(
        """{
  "name": "test-project",
  "version": "1.0.0",
  "scripts": {
    "test": "jest"
  },
  "devDependencies": {
    "jest": "^29.0.0"
  }
}"""
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.js").write_text(
        """function hello() {
  return "Hello, World!";
}
module.exports = { hello };
"""
    )

    yield tmp_path


@pytest.fixture
def slopmop_root() -> Path:
    """Return the slopmop project root directory."""
    return Path(__file__).parent.parent
