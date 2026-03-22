"""Focused tests for run_status direct invocation."""

import json
from unittest.mock import patch

from slopmop.cli.status import run_status
from tests.conftest import make_mock_status_registry


class TestRunStatus:
    """Tests for the run_status() function called directly."""

    def _run(self, tmp_path):
        """Helper: call run_status with standard mocks."""
        (tmp_path / ".sb_config.json").write_text(json.dumps({}))
        registry = make_mock_status_registry()
        with (
            patch("slopmop.cli.status.get_registry", return_value=registry),
            patch("slopmop.cli.status.load_timings", return_value={}),
        ):
            result = run_status(project_root=str(tmp_path), json_output=False)
        return result, registry

    def test_always_returns_0(self, tmp_path):
        """run_status always returns 0 (observatory)."""
        result, _ = self._run(tmp_path)
        assert result == 0

    def test_invalid_project_root(self, tmp_path, capsys):
        """run_status returns 1 for non-existent path."""
        result = run_status(
            project_root=str(tmp_path / "nonexistent"), json_output=False
        )
        assert result == 1
        assert "not found" in capsys.readouterr().out

    def test_shows_dashboard_header(self, tmp_path, capsys):
        """run_status shows dashboard header."""
        (tmp_path / ".sb_config.json").write_text(json.dumps({}))
        registry = make_mock_status_registry()
        with (
            patch("slopmop.cli.status.get_registry", return_value=registry),
            patch("slopmop.cli.status.load_timings", return_value={}),
        ):
            run_status(project_root=str(tmp_path), json_output=False)
        out = capsys.readouterr().out
        assert "project dashboard" in out
        assert "Historical dashboard only" in out

    def test_inventory_uses_latest_artifact_result_for_scour_only_gate(
        self, tmp_path, capsys
    ):
        (tmp_path / ".sb_config.json").write_text(json.dumps({}))
        sm_dir = tmp_path / ".slopmop"
        sm_dir.mkdir()
        (sm_dir / "last_scour.json").write_text(
            json.dumps(
                {
                    "summary": {
                        "passed": 1,
                        "failed": 0,
                        "warned": 0,
                        "errors": 0,
                        "skipped": 0,
                    },
                    "passed_gates": ["myopia:dependency-risk.py"],
                    "schema": "slopmop/v2",
                    "level": "scour",
                }
            )
        )
        registry = make_mock_status_registry(
            all_gates=["myopia:dependency-risk.py"],
            swab_gates=[],
            scour_gates=["myopia:dependency-risk.py"],
        )
        with (
            patch("slopmop.cli.status.get_registry", return_value=registry),
            patch("slopmop.cli.status.load_timings", return_value={}),
        ):
            run_status(project_root=str(tmp_path), json_output=False)

        out = capsys.readouterr().out
        assert "dependency-risk.py" in out
        assert "last: passed" in out

    def test_no_executor_used(self, tmp_path):
        """run_status does NOT use CheckExecutor."""
        (tmp_path / ".sb_config.json").write_text(json.dumps({}))
        registry = make_mock_status_registry()
        with (
            patch("slopmop.cli.status.get_registry", return_value=registry),
            patch("slopmop.cli.status.load_timings", return_value={}),
            patch("slopmop.core.executor.CheckExecutor", side_effect=AssertionError),
        ):
            result = run_status(project_root=str(tmp_path), json_output=False)
            assert result == 0

    def test_generate_baseline_snapshot_without_artifact_fails(self, tmp_path, capsys):
        """Generating a baseline snapshot needs a persisted run artifact."""
        result = run_status(
            project_root=str(tmp_path),
            json_output=False,
            generate_baseline_snapshot_flag=True,
        )
        assert result == 1
        assert "No persisted run artifact found" in capsys.readouterr().out

    def test_generate_baseline_snapshot_from_latest_artifact(self, tmp_path, capsys):
        """Status can save a baseline snapshot from the latest run artifact."""
        (tmp_path / ".sb_config.json").write_text(json.dumps({}))
        sm_dir = tmp_path / ".slopmop"
        sm_dir.mkdir()
        (sm_dir / "last_swab.json").write_text(
            json.dumps(
                {
                    "schema": "slopmop/v2",
                    "level": "swab",
                    "summary": {"failed": 1},
                    "results": [
                        {
                            "name": "laziness:dead-code.py",
                            "status": "failed",
                            "duration": 0.1,
                            "output": "dead code found",
                        }
                    ],
                }
            )
        )
        registry = make_mock_status_registry()
        with (
            patch("slopmop.cli.status.get_registry", return_value=registry),
            patch("slopmop.cli.status.load_timings", return_value={}),
        ):
            result = run_status(
                project_root=str(tmp_path),
                json_output=False,
                generate_baseline_snapshot_flag=True,
            )

        assert result == 0
        snapshot = tmp_path / ".slopmop" / "baseline_snapshot.json"
        assert snapshot.exists()
        data = json.loads(snapshot.read_text())
        assert data["source_file"] == "last_swab.json"
        assert data["failure_fingerprints"]
        out = capsys.readouterr().out
        assert "BASELINE SNAPSHOT GENERATED" in out
        assert "BASELINE SNAPSHOT" in out
