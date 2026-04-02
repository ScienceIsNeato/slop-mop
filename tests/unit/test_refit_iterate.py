"""Unit tests for the refit iterate (continue) pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import Mock

from slopmop.cli import refit as refit_mod
from slopmop.cli._refit_iteration import _summarise_failure_artifact
from tests.conftest import fake_lock as _fake_lock  # shared no-op sm_lock


class TestSummariseFailureArtifact:
    """The block-on-failure message should surface findings, not just a path."""

    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert _summarise_failure_artifact(tmp_path / "nope.json") == []

    def test_malformed_json_returns_empty(self, tmp_path: Path):
        p = tmp_path / "bad.json"
        p.write_text("{not json")
        assert _summarise_failure_artifact(p) == []

    def test_surfaces_findings_and_fix(self, tmp_path: Path):
        """Top findings + fix_suggestion should appear in block output.

        Observed against manim: block message said only "Inspect: <path>"
        with 162 findings sitting in the JSON. Agent had to parse JSON
        manually to learn anything about what failed.
        """
        artifact = {
            "results": [
                {
                    "findings": [
                        {
                            "file": "tests/test_cli.py",
                            "line": 42,
                            "message": "Duplicate of tests/test_cli.py:10 (8 lines)",
                        },
                        {
                            "file": "tests/test_cli.py",
                            "line": 99,
                            "message": "Duplicate of tests/other.py:5 (6 lines)",
                        },
                    ],
                    "fix_suggestion": "Add tests/ to exclude_dirs.",
                }
            ]
        }
        p = tmp_path / "scour.json"
        p.write_text(json.dumps(artifact))

        lines = _summarise_failure_artifact(p)
        joined = "\n".join(lines)
        assert "2 finding(s)" in joined
        assert "tests/test_cli.py:42" in joined
        assert "Duplicate of tests/test_cli.py:10" in joined
        assert "Fix: Add tests/ to exclude_dirs." in joined

    def test_truncates_long_finding_lists(self, tmp_path: Path):
        findings = [
            {"file": f"f{i}.py", "line": i, "message": f"clone {i}"} for i in range(20)
        ]
        p = tmp_path / "scour.json"
        p.write_text(json.dumps({"results": [{"findings": findings}]}))

        lines = _summarise_failure_artifact(p)
        joined = "\n".join(lines)
        assert "20 finding(s)" in joined
        assert "... and 15 more" in joined
        # Only first 5 findings shown
        assert "f0.py:0" in joined
        assert "f4.py:4" in joined
        assert "f5.py" not in joined


# ---------------------------------------------------------------------------
# Off-rail guards: dirty-entry, config drift, and head-drift recovery hint
# ---------------------------------------------------------------------------


def _base_plan(tmp_path: Path, item_status: str = "pending") -> dict:
    """Minimal plan dict for off-rail guard tests."""
    return {
        "project_root": str(tmp_path),
        "branch": "feat/refit",
        "expected_head": "abc123",
        "status": "ready",
        "current_index": 0,
        "current_gate": "laziness:repeated-code",
        "items": [
            {
                "gate": "laziness:repeated-code",
                "status": item_status,
                "attempt_count": 0,
                "commit_message": "refactor: fix repeated code",
                "log_file": None,
            }
        ],
    }


class TestDirtyEntryGuard:
    """blocked_on_dirty_entry fires when worktree is dirty before a fresh gate."""

    def _common_mocks(self, monkeypatch, plan, dirty_status):
        monkeypatch.setattr(refit_mod, "_load_plan", Mock(return_value=plan))
        monkeypatch.setattr(refit_mod, "_save_plan", Mock())
        monkeypatch.setattr(refit_mod, "_save_protocol", Mock())
        monkeypatch.setattr(
            refit_mod, "_current_branch", Mock(return_value="feat/refit")
        )
        monkeypatch.setattr(refit_mod, "_current_head", Mock(return_value="abc123"))
        monkeypatch.setattr(
            refit_mod, "_worktree_status", Mock(return_value=dirty_status)
        )
        monkeypatch.setattr(refit_mod, "sm_lock", _fake_lock)

    def test_fresh_gate_with_dirty_worktree_blocks(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        """An unblocked gate with uncommitted files in the worktree must block.

        Without this guard, git add -A would silently bundle the agent's
        unrelated changes into the refit commit, breaking commit attribution.
        """
        args = argparse.Namespace(start=False, iterate=True, project_root=str(tmp_path))
        plan = _base_plan(tmp_path, item_status="pending")
        dirty = [" M agent_scratch.py"]
        self._common_mocks(monkeypatch, plan, dirty)

        assert refit_mod.cmd_refit(args) == 1
        out = capsys.readouterr().out
        assert "uncommitted changes" in out
        assert "silently bundled" in out
        assert "agent_scratch.py" in out

    def test_empty_item_status_treated_as_fresh(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        """Item with status='' (unset) counts as fresh — guard must still fire."""
        args = argparse.Namespace(start=False, iterate=True, project_root=str(tmp_path))
        plan = _base_plan(tmp_path, item_status="")
        self._common_mocks(monkeypatch, plan, [" M file.py"])

        assert refit_mod.cmd_refit(args) == 1
        out = capsys.readouterr().out
        assert "uncommitted changes" in out
        assert "silently bundled" in out

    def test_blocked_item_with_dirty_worktree_is_allowed(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        """An item in blocked_on_failure state with dirty worktree is normal.

        This is the fix-and-retry flow: the agent committed changes to fix
        the gate and the formatter may have left adjacent files dirty.
        Guard must not fire here.
        """
        args = argparse.Namespace(start=False, iterate=True, project_root=str(tmp_path))
        plan = _base_plan(tmp_path, item_status="blocked_on_failure")
        dirty = [" M fix.py"]
        self._common_mocks(monkeypatch, plan, dirty)
        # Gate passes so the dirty files get committed normally.
        monkeypatch.setattr(refit_mod, "_run_scour", Mock(return_value=0))
        monkeypatch.setattr(
            refit_mod, "_commit_current_changes", Mock(return_value=(0, "ok"))
        )
        # HEAD after commit is different from before.
        heads = iter(["abc123", "abc123", "abc123", "def456"])
        monkeypatch.setattr(
            refit_mod, "_current_head", Mock(side_effect=lambda _root: next(heads))
        )
        statuses = iter([dirty, dirty])
        monkeypatch.setattr(
            refit_mod,
            "_worktree_status",
            Mock(side_effect=lambda _root: next(statuses)),
        )

        result = refit_mod.cmd_refit(args)
        out = capsys.readouterr().out
        assert "blocked_on_dirty_entry" not in out
        # Gate passed and commit happened — the run should succeed.
        assert result == 0

    def test_clean_worktree_fresh_gate_is_not_blocked(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        """Clean worktree with fresh gate should not trigger the dirty-entry guard."""
        args = argparse.Namespace(start=False, iterate=True, project_root=str(tmp_path))
        plan = _base_plan(tmp_path, item_status="pending")
        self._common_mocks(monkeypatch, plan, [])  # clean
        monkeypatch.setattr(refit_mod, "_run_scour", Mock(return_value=1))

        assert refit_mod.cmd_refit(args) == 1
        out = capsys.readouterr().out
        assert "blocked_on_dirty_entry" not in out
        assert "Refit stopped on failing gate" in out


class TestConfigDriftWarning:
    """warn_config_drift is emitted (non-blocking) when .sb_config.json changes."""

    def test_config_drift_emits_warning_and_continues(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        """Config hash mismatch should warn but NOT return 1 — iterate continues."""
        (tmp_path / ".sb_config.json").write_text(
            '{"test": "changed"}', encoding="utf-8"
        )
        args = argparse.Namespace(start=False, iterate=True, project_root=str(tmp_path))
        plan = _base_plan(tmp_path)
        plan["config_hash"] = "deadbeef00000000"  # stale hash

        monkeypatch.setattr(refit_mod, "_load_plan", Mock(return_value=plan))
        monkeypatch.setattr(refit_mod, "_save_plan", Mock())
        monkeypatch.setattr(refit_mod, "_save_protocol", Mock())
        monkeypatch.setattr(
            refit_mod, "_current_branch", Mock(return_value="feat/refit")
        )
        monkeypatch.setattr(refit_mod, "_current_head", Mock(return_value="abc123"))
        monkeypatch.setattr(refit_mod, "_worktree_status", Mock(return_value=[]))
        monkeypatch.setattr(refit_mod, "_run_scour", Mock(return_value=1))
        monkeypatch.setattr(refit_mod, "sm_lock", _fake_lock)

        result = refit_mod.cmd_refit(args)
        out = capsys.readouterr().out
        assert ".sb_config.json has changed" in out, "drift warning must be emitted"
        # Warning is non-blocking — iterate still runs and fails on the gate.
        assert "Refit stopped on failing gate" in out
        assert result == 1

    def test_no_config_hash_in_plan_skips_drift_check(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        """Older plans without config_hash must not trigger a spurious warning."""
        args = argparse.Namespace(start=False, iterate=True, project_root=str(tmp_path))
        plan = _base_plan(tmp_path)
        # No config_hash key — backward compat scenario.
        assert "config_hash" not in plan

        monkeypatch.setattr(refit_mod, "_load_plan", Mock(return_value=plan))
        monkeypatch.setattr(refit_mod, "_save_plan", Mock())
        monkeypatch.setattr(refit_mod, "_save_protocol", Mock())
        monkeypatch.setattr(
            refit_mod, "_current_branch", Mock(return_value="feat/refit")
        )
        monkeypatch.setattr(refit_mod, "_current_head", Mock(return_value="abc123"))
        monkeypatch.setattr(refit_mod, "_worktree_status", Mock(return_value=[]))
        monkeypatch.setattr(refit_mod, "_run_scour", Mock(return_value=1))
        monkeypatch.setattr(refit_mod, "sm_lock", _fake_lock)

        refit_mod.cmd_refit(args)
        out = capsys.readouterr().out
        assert ".sb_config.json has changed" not in out


class TestHeadDriftRecoveryHint:
    """blocked_on_head_drift message includes --skip recovery hint."""

    def test_head_drift_message_includes_skip_hint(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        """When HEAD drifts on a completed-gate plan, the message must tell the
        agent to use `sm refit --skip` to recover, not just 'review the repo'."""
        args = argparse.Namespace(start=False, iterate=True, project_root=str(tmp_path))
        # Make items[0] look completed so the drift is NOT in the allowed window.
        plan = _base_plan(tmp_path)
        plan["items"][0]["status"] = "completed"
        plan["current_index"] = 1
        plan["items"].append(
            {
                "gate": "overconfidence:coverage-gaps.py",
                "status": "pending",
                "attempt_count": 0,
                "commit_message": "test: coverage",
                "log_file": None,
            }
        )
        plan["expected_head"] = "abc123"

        monkeypatch.setattr(refit_mod, "_load_plan", Mock(return_value=plan))
        monkeypatch.setattr(refit_mod, "_save_plan", Mock())
        monkeypatch.setattr(refit_mod, "_save_protocol", Mock())
        monkeypatch.setattr(
            refit_mod, "_current_branch", Mock(return_value="feat/refit")
        )
        # Live HEAD is ahead of expected — agent committed directly.
        monkeypatch.setattr(refit_mod, "_current_head", Mock(return_value="deadbeef"))
        monkeypatch.setattr(refit_mod, "sm_lock", _fake_lock)

        assert refit_mod.cmd_refit(args) == 1
        out = capsys.readouterr().out
        assert "HEAD changed unexpectedly" in out
        assert "sm refit --skip" in out
