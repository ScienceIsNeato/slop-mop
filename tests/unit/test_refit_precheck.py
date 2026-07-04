"""Focused tests for staged refit precheck state."""

from __future__ import annotations

from pathlib import Path

from slopmop.cli import _refit_precheck as precheck_mod
from slopmop.doctor.gate_preflight import GatePreflightRecord


class TestBuildPrecheck:
    def test_build_precheck_tracks_disabled_and_runnable_gates(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        records = [
            GatePreflightRecord(
                gate="deceptiveness:bogus-tests.js",
                display_name="bogus-tests.js",
                enabled=True,
                applicable=True,
                skip_reason="",
                config_fingerprint="abc",
                missing_tools=(),
            ),
            GatePreflightRecord(
                gate="overconfidence:coverage-gaps.js",
                display_name="coverage-gaps.js",
                enabled=False,
                applicable=True,
                skip_reason="",
                config_fingerprint="def",
                missing_tools=(),
            ),
        ]
        monkeypatch.setattr(
            precheck_mod,
            "gather_gate_preflight_records",
            lambda _root: records,
        )
        monkeypatch.setattr(precheck_mod, "_run_gate_probe", lambda *_args: 1)

        precheck = precheck_mod.build_precheck(tmp_path)

        assert precheck["status"] == "blocked_on_gate_fidelity"
        entries = {entry["gate"]: entry for entry in precheck["gates"]}
        assert entries["deceptiveness:bogus-tests.js"]["probe_status"] == "runnable"
        assert entries["deceptiveness:bogus-tests.js"]["review_status"] == "pending"
        assert entries["overconfidence:coverage-gaps.js"]["probe_status"] == "disabled"
        assert entries["overconfidence:coverage-gaps.js"]["review_status"] == "pending"

    def test_build_precheck_resets_approval_when_gate_stops_running(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        record = GatePreflightRecord(
            gate="deceptiveness:bogus-tests.js",
            display_name="bogus-tests.js",
            enabled=True,
            applicable=True,
            skip_reason="",
            config_fingerprint="same",
            missing_tools=(),
        )
        monkeypatch.setattr(
            precheck_mod,
            "gather_gate_preflight_records",
            lambda _root: [record],
        )
        monkeypatch.setattr(precheck_mod, "_run_gate_probe", lambda *_args: 2)

        previous = {
            "gates": [
                {
                    "gate": record.gate,
                    "config_fingerprint": "same",
                    "review_status": "approved",
                    "reviewed_at": "earlier",
                }
            ]
        }
        precheck = precheck_mod.build_precheck(tmp_path, previous=previous)
        entry = precheck["gates"][0]
        assert entry["probe_status"] == "blocked"
        assert entry["review_status"] == "pending"


class TestApplyReviewActions:
    def test_apply_review_actions_marks_approval_and_blocker(self) -> None:
        precheck = {
            "gates": [
                {
                    "gate": "deceptiveness:bogus-tests.js",
                    "enabled": True,
                    "applicable": True,
                    "probe_status": "runnable",
                    "review_status": "pending",
                },
                {
                    "gate": "overconfidence:coverage-gaps.js",
                    "enabled": False,
                    "applicable": True,
                    "probe_status": "disabled",
                    "review_status": "pending",
                },
            ]
        }

        error = precheck_mod.apply_review_actions(
            precheck,
            approve_gates=["deceptiveness:bogus-tests.js"],
            blocker_gate="overconfidence:coverage-gaps.js",
            blocker_issue="slop-mop#123",
            blocker_reason="runner is noisy on vendored coverage files",
        )

        assert error is None
        entries = {entry["gate"]: entry for entry in precheck["gates"]}
        assert entries["deceptiveness:bogus-tests.js"]["review_status"] == "approved"
        assert (
            entries["overconfidence:coverage-gaps.js"]["review_status"]
            == "blocked_disabled"
        )
        assert precheck["status"] == "ready_for_plan"

    def test_apply_review_actions_requires_disabled_gate_for_blocker(self) -> None:
        precheck = {
            "gates": [
                {
                    "gate": "overconfidence:coverage-gaps.js",
                    "enabled": True,
                    "applicable": True,
                    "probe_status": "runnable",
                    "review_status": "pending",
                }
            ]
        }

        error = precheck_mod.apply_review_actions(
            precheck,
            approve_gates=[],
            blocker_gate="overconfidence:coverage-gaps.js",
            blocker_issue="slop-mop#123",
            blocker_reason="still broken",
        )

        assert error is not None
        assert "Disable overconfidence:coverage-gaps.js" in error


class TestPreflightConfigSources:
    """Preflight must see the same RESOLVED config the gates run with.

    Regression: the loader used to read only .sb_config.json, silently
    ignoring [tool.slopmop] in pyproject.toml — so refit/doctor readiness
    disagreed with the actual sm swab/scour behavior on pyproject-configured
    repos (like slop-mop itself).
    """

    def test_pyproject_only_config_is_honored(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[tool.slopmop]\ndisabled_gates = ["myopia:github-actions-hygiene"]\n'
        )
        from slopmop.doctor.gate_preflight import _load_gate_preflight_config

        cfg = _load_gate_preflight_config(tmp_path)
        assert cfg.get("disabled_gates") == ["myopia:github-actions-hygiene"]

    def test_sb_config_layers_over_pyproject(self, tmp_path: Path) -> None:
        # Same layering contract as sm swab/scour: pyproject is the base,
        # .sb_config.json wins on conflicts.
        (tmp_path / "pyproject.toml").write_text(
            '[tool.slopmop]\ndisabled_gates = ["a:b"]\n'
        )
        (tmp_path / ".sb_config.json").write_text('{"disabled_gates": ["c:d"]}')
        from slopmop.doctor.gate_preflight import _load_gate_preflight_config
        from slopmop.sm import load_config

        cfg = _load_gate_preflight_config(tmp_path)
        assert cfg == load_config(tmp_path)  # byte-identical resolution
        assert cfg.get("disabled_gates") == ["c:d"]
