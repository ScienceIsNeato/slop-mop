"""Integration tests for custom gate end-to-end flow.

These tests exercise the full lifecycle: JSON config is parsed,
custom gates are registered in a real registry, and execution
produces the expected results.  Unlike unit tests (which mock the
registry), these use real ``CheckRegistry`` instances and real
subprocess execution.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

from slopmop.checks.base import GateLevel
from slopmop.checks.custom import register_custom_gates
from slopmop.core.registry import CheckRegistry
from slopmop.core.result import CheckStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_checks(registry: CheckRegistry, config: Dict[str, Any] | None = None):
    """Return every check currently in *registry* as instances."""
    cfg = config or {}
    return registry.get_checks(names=list(registry._check_classes.keys()), config=cfg)


def _get_check(registry: CheckRegistry, full_name: str):
    """Return a single check instance by *full_name*, or ``None``."""
    return registry.get_check(full_name, config={})


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_registry():
    """Provide a fresh registry backed by a real CheckRegistry."""
    registry = CheckRegistry()
    with patch("slopmop.core.registry.get_registry", return_value=registry):
        yield registry


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCustomGateEndToEnd:
    """Full-lifecycle integration tests for custom gates."""

    def test_passing_gate_runs_and_passes(
        self, tmp_path: Path, fresh_registry: CheckRegistry
    ) -> None:
        """A custom gate with 'true' as command should pass."""
        config: Dict[str, Any] = {
            "custom_gates": [
                {
                    "name": "always-pass",
                    "description": "Gate that always passes",
                    "category": "laziness",
                    "command": "true",
                    "level": "swab",
                    "timeout": 10,
                }
            ]
        }
        registered = register_custom_gates(config)
        assert len(registered) == 1
        assert registered[0] == "laziness:always-pass"

        # Verify it's actually in the registry and runnable
        check = _get_check(fresh_registry, "laziness:always-pass")
        assert check is not None

        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_failing_gate_runs_and_fails(
        self, tmp_path: Path, fresh_registry: CheckRegistry
    ) -> None:
        """A custom gate with 'false' as command should fail."""
        config: Dict[str, Any] = {
            "custom_gates": [
                {
                    "name": "always-fail",
                    "description": "Gate that always fails",
                    "category": "overconfidence",
                    "command": "false",
                    "level": "swab",
                }
            ]
        }
        registered = register_custom_gates(config)
        assert len(registered) == 1

        check = _get_check(fresh_registry, "overconfidence:always-fail")
        assert check is not None

        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert result.error is not None
        assert "exit code" in result.error

    def test_gate_inspects_project_files(
        self, tmp_path: Path, fresh_registry: CheckRegistry
    ) -> None:
        """Gate command that inspects the project root finds created files."""
        # Create a file that the gate command will find
        (tmp_path / "bad_import.py").write_text("import pdb\n")

        config: Dict[str, Any] = {
            "custom_gates": [
                {
                    "name": "no-debugger",
                    "description": "No pdb imports",
                    "category": "deceptiveness",
                    "command": "! grep -rn 'import pdb' .",
                    "level": "swab",
                }
            ]
        }
        registered = register_custom_gates(config)
        assert len(registered) == 1

        check = _get_check(fresh_registry, "deceptiveness:no-debugger")
        assert check is not None
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED

    def test_gate_passes_when_no_violations(
        self, tmp_path: Path, fresh_registry: CheckRegistry
    ) -> None:
        """Same gate from above passes when no bad files exist."""
        (tmp_path / "clean.py").write_text("import os\n")

        config: Dict[str, Any] = {
            "custom_gates": [
                {
                    "name": "no-debugger",
                    "description": "No pdb imports",
                    "category": "deceptiveness",
                    "command": "! grep -rn 'import pdb' .",
                    "level": "swab",
                }
            ]
        }
        register_custom_gates(config)

        check = _get_check(fresh_registry, "deceptiveness:no-debugger")
        assert check is not None
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_multiple_gates_registered_and_independent(
        self, tmp_path: Path, fresh_registry: CheckRegistry
    ) -> None:
        """Multiple gates register independently; one can pass while another fails."""
        config: Dict[str, Any] = {
            "custom_gates": [
                {"name": "pass-gate", "command": "true", "category": "laziness"},
                {"name": "fail-gate", "command": "false", "category": "myopia"},
            ]
        }
        registered = register_custom_gates(config)
        assert len(registered) == 2

        checks = _all_checks(fresh_registry)
        results = {c.full_name: c.run(str(tmp_path)) for c in checks}

        assert results["laziness:pass-gate"].status == CheckStatus.PASSED
        assert results["myopia:fail-gate"].status == CheckStatus.FAILED

    def test_scour_gate_level_stored_correctly(
        self, tmp_path: Path, fresh_registry: CheckRegistry
    ) -> None:
        """A scour-level gate records GateLevel.SCOUR on its class."""
        config: Dict[str, Any] = {
            "custom_gates": [
                {"name": "scour-only", "command": "true", "level": "scour"},
                {"name": "swab-gate", "command": "true", "level": "swab"},
            ]
        }
        register_custom_gates(config)

        scour_check = _get_check(fresh_registry, "general:scour-only")
        swab_check = _get_check(fresh_registry, "general:swab-gate")
        assert scour_check is not None
        assert swab_check is not None

        assert type(scour_check).level == GateLevel.SCOUR
        assert type(swab_check).level == GateLevel.SWAB

    def test_gate_output_captured_in_result(
        self, tmp_path: Path, fresh_registry: CheckRegistry
    ) -> None:
        """Stdout from gate command appears in the check result output."""
        config: Dict[str, Any] = {
            "custom_gates": [
                {
                    "name": "chatty",
                    "command": "echo 'INTEGRATION_TEST_MARKER_12345'",
                    "category": "general",
                }
            ]
        }
        register_custom_gates(config)

        check = _get_check(fresh_registry, "general:chatty")
        assert check is not None
        result = check.run(str(tmp_path))
        assert "INTEGRATION_TEST_MARKER_12345" in (result.output or "")

    def test_pipes_and_subshells_work(
        self, tmp_path: Path, fresh_registry: CheckRegistry
    ) -> None:
        """Shell pipes and subshells execute properly."""
        config: Dict[str, Any] = {
            "custom_gates": [
                {
                    "name": "piped",
                    "command": "echo -e 'a\\nb\\nc' | wc -l | tr -d ' '",
                    "category": "laziness",
                }
            ]
        }
        register_custom_gates(config)

        check = _get_check(fresh_registry, "laziness:piped")
        assert check is not None
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED
        assert "3" in (result.output or "")

    def test_config_from_json_string(
        self, tmp_path: Path, fresh_registry: CheckRegistry
    ) -> None:
        """Simulate reading config from a JSON file."""
        json_str = json.dumps(
            {
                "custom_gates": [
                    {
                        "name": "json-gate",
                        "description": "From JSON",
                        "category": "myopia",
                        "command": "echo ok",
                        "level": "swab",
                        "timeout": 15,
                    }
                ]
            }
        )
        config = json.loads(json_str)
        registered = register_custom_gates(config)
        assert len(registered) == 1
        assert registered[0] == "myopia:json-gate"

    def test_custom_gate_has_is_custom_gate_attribute(
        self, tmp_path: Path, fresh_registry: CheckRegistry
    ) -> None:
        """Custom gates are identifiable via is_custom_gate class attribute."""
        config: Dict[str, Any] = {
            "custom_gates": [
                {"name": "marked", "command": "true", "category": "laziness"}
            ]
        }
        register_custom_gates(config)

        check = _get_check(fresh_registry, "laziness:marked")
        assert check is not None
        assert getattr(type(check), "is_custom_gate", False) is True

    def test_gate_cwd_is_project_root(
        self, tmp_path: Path, fresh_registry: CheckRegistry
    ) -> None:
        """Commands execute with cwd set to the project root."""
        config: Dict[str, Any] = {
            "custom_gates": [
                {"name": "cwd-check", "command": "pwd", "category": "laziness"}
            ]
        }
        register_custom_gates(config)

        check = _get_check(fresh_registry, "laziness:cwd-check")
        assert check is not None
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED
        # The output should contain the tmp_path (resolved)
        output = (result.output or "").strip()
        assert str(tmp_path.resolve()) in output or str(tmp_path) in output

    def test_invalid_entries_skipped_valid_ones_register(
        self, tmp_path: Path, fresh_registry: CheckRegistry
    ) -> None:
        """Mixed valid/invalid configs: only valid ones end up in registry."""
        config: Dict[str, Any] = {
            "custom_gates": [
                {"name": "good", "command": "true"},
                {"name": "bad"},  # missing command
                "not-a-dict",
                {"name": "also-good", "command": "echo hi"},
            ]
        }
        registered = register_custom_gates(config)
        assert len(registered) == 2

        checks = _all_checks(fresh_registry)
        names = {c.full_name for c in checks}
        assert "general:good" in names
        assert "general:also-good" in names
