"""Pytest configuration and fixtures for slopmop tests."""

from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import pytest

from slopmop.cli.barnacle import QUEUE_DIR_ENVAR
from slopmop.core.result import CheckResult, CheckStatus


@pytest.fixture(autouse=True)
def _isolate_barnacle_queue(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Always point ``SLOPMOP_BARNACLE_DIR`` at a per-test tmp path.

    Without this, any test that ends up calling ``auto_file_barnacle`` (e.g.
    via ``cmd_upgrade`` covering the validation-failure path) leaks barnacles
    into the developer's real ``~/.slopmop/barnacles/`` queue. Tests that
    intentionally exercise the default queue location must explicitly call
    ``monkeypatch.delenv(QUEUE_DIR_ENVAR, raising=False)``.
    """

    isolated = tmp_path_factory.mktemp("slopmop-barnacles")
    monkeypatch.setenv(QUEUE_DIR_ENVAR, str(isolated))


class _FakeLock:
    """Synchronous no-op context manager for mocking sm_lock in refit tests."""

    def __enter__(self):
        return None

    def __exit__(self, _exc_type, _exc, _tb):
        return False


def fake_lock(_project_root, _verb):
    """Drop-in replacement for sm_lock that never blocks."""
    return _FakeLock()


@pytest.fixture
def temp_project(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary project directory with Python files."""
    # Create a minimal Python project
    (tmp_path / "setup.py").write_text("# setup")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("")
    (tmp_path / "src" / "main.py").write_text('''"""Main module."""

def hello() -> str:
    """Return greeting."""
    return "Hello, World!"
''')
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "__init__.py").write_text("")
    (tmp_path / "tests" / "test_main.py").write_text('''"""Tests for main."""

from src.main import hello


def test_hello():
    """Test hello function."""
    assert hello() == "Hello, World!"
''')

    yield tmp_path


@pytest.fixture
def temp_js_project(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary JavaScript project directory."""
    # Create a minimal JS project
    (tmp_path / "package.json").write_text("""{
  "name": "test-project",
  "version": "1.0.0",
  "scripts": {
    "test": "jest"
  },
  "devDependencies": {
    "jest": "^29.0.0"
  }
}""")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.js").write_text("""function hello() {
  return "Hello, World!";
}
module.exports = { hello };
""")

    yield tmp_path


@pytest.fixture
def slopmop_root() -> Path:
    """Return the slopmop project root directory."""
    return Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


def make_feedback_result(status: CheckStatus, **kwargs) -> CheckResult:
    """Build a CheckResult for the ``myopia:ignored-feedback`` gate."""
    return CheckResult(
        name="myopia:ignored-feedback",
        status=status,
        duration=0.01,
        output=kwargs.get("output", ""),
        error=kwargs.get("error"),
        fix_suggestion=kwargs.get("fix_suggestion"),
        status_detail=kwargs.get("status_detail"),
    )


def make_mock_status_registry(all_gates=None, swab_gates=None, scour_gates=None):
    """Build a mock registry for status tests."""
    mock_reg = MagicMock()
    mock_reg.list_checks.return_value = all_gates or []

    def _gate_names_for_level(level, _config=None):
        from slopmop.checks.base import GateLevel

        if level == GateLevel.SWAB:
            return swab_gates or all_gates or []
        return scour_gates or all_gates or []

    mock_reg.get_gate_names_for_level.side_effect = _gate_names_for_level

    mock_check = MagicMock()
    mock_check.is_applicable.return_value = True
    mock_check.skip_reason.return_value = ""
    mock_reg.get_check.return_value = mock_check
    return mock_reg
