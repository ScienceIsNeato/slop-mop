"""Tests for ProjectPipAuditRemediabilityCheck (split from test_doctor_checks.py)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slopmop.doctor import DoctorContext, DoctorStatus
from slopmop.doctor.project_env import ProjectPipAuditRemediabilityCheck

# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def ctx(tmp_path: Path) -> DoctorContext:  # noqa: ambiguity-mine
    return DoctorContext(project_root=tmp_path)


from tests.unit.conftest import mk_python_project as _mk_python_project, mk_project_venv as _mk_project_venv


# ── tests ─────────────────────────────────────────────────────────────────


class TestProjectPipAuditRemediabilityCheck:
    def test_skips_without_python_markers(self, ctx):
        assert ProjectPipAuditRemediabilityCheck().run(ctx).status is DoctorStatus.SKIP

    def test_skips_without_local_venv(self, tmp_path, monkeypatch):
        _mk_python_project(tmp_path)
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
        r = ProjectPipAuditRemediabilityCheck().run(
            DoctorContext(project_root=tmp_path)
        )
        assert r.status is DoctorStatus.SKIP
        assert "project.python_venv" in r.summary

    def test_no_vulnerabilities_ok(self, tmp_path):
        _mk_python_project(tmp_path)
        _mk_project_venv(tmp_path)
        pip_audit_proc = MagicMock(
            returncode=0,
            stdout=json.dumps({"dependencies": []}),
            stderr="",
        )
        with patch("subprocess.run", return_value=pip_audit_proc):
            r = ProjectPipAuditRemediabilityCheck().run(
                DoctorContext(project_root=tmp_path)
            )
        assert r.status is DoctorStatus.OK
        assert "no vulnerable dependencies" in r.summary

    def test_blocked_when_fix_versions_not_in_index(self, tmp_path):
        _mk_python_project(tmp_path)
        _mk_project_venv(tmp_path)

        pip_audit_payload = {
            "dependencies": [
                {
                    "name": "Pygments",
                    "version": "2.19.2",
                    "vulns": [
                        {
                            "id": "PYSEC-TEST-1",
                            "fix_versions": ["2.19.3"],
                        }
                    ],
                }
            ]
        }

        def _fake_run(cmd, **kwargs):
            if cmd[2:4] == ["pip_audit", "--format"]:
                return MagicMock(
                    returncode=1,
                    stdout=json.dumps(pip_audit_payload),
                    stderr="",
                )
            if cmd[2:5] == ["pip", "install", "--dry-run"]:
                return MagicMock(
                    returncode=1,
                    stdout="",
                    stderr=(
                        "ERROR: Could not find a version that satisfies the requirement "
                        "Pygments==2.19.3"
                    ),
                )
            raise AssertionError(f"Unexpected command: {cmd}")

        with patch("subprocess.run", side_effect=_fake_run):
            r = ProjectPipAuditRemediabilityCheck().run(
                DoctorContext(project_root=tmp_path)
            )

        assert r.status is DoctorStatus.FAIL
        assert "blocked by package index" in r.summary
        assert "Publish/mirror" in (r.fix_hint or "")
        assert r.data["blocked"][0]["name"] == "Pygments"

    def test_ok_when_at_least_one_fix_is_installable(self, tmp_path):
        _mk_python_project(tmp_path)
        _mk_project_venv(tmp_path)

        pip_audit_payload = {
            "dependencies": [
                {
                    "name": "Pygments",
                    "version": "2.19.2",
                    "vulns": [
                        {
                            "id": "PYSEC-TEST-1",
                            "fix_versions": ["2.19.3"],
                        }
                    ],
                }
            ]
        }

        def _fake_run(cmd, **kwargs):
            if cmd[2:4] == ["pip_audit", "--format"]:
                return MagicMock(
                    returncode=1,
                    stdout=json.dumps(pip_audit_payload),
                    stderr="",
                )
            if cmd[2:5] == ["pip", "install", "--dry-run"]:
                return MagicMock(returncode=0, stdout="Would install", stderr="")
            raise AssertionError(f"Unexpected command: {cmd}")

        with patch("subprocess.run", side_effect=_fake_run):
            r = ProjectPipAuditRemediabilityCheck().run(
                DoctorContext(project_root=tmp_path)
            )

        assert r.status is DoctorStatus.OK
        assert "installable" in r.summary
        assert r.data["remediable_count"] == 1

    def test_warn_when_upstream_has_no_fix_versions(self, tmp_path):
        _mk_python_project(tmp_path)
        _mk_project_venv(tmp_path)

        pip_audit_payload = {
            "dependencies": [
                {
                    "name": "pkg-no-fix",
                    "version": "1.0.0",
                    "vulns": [{"id": "PYSEC-TEST-2", "fix_versions": []}],
                }
            ]
        }

        pip_audit_proc = MagicMock(
            returncode=1,
            stdout=json.dumps(pip_audit_payload),
            stderr="",
        )
        with patch("subprocess.run", return_value=pip_audit_proc):
            r = ProjectPipAuditRemediabilityCheck().run(
                DoctorContext(project_root=tmp_path)
            )

        assert r.status is DoctorStatus.WARN
        assert "no upstream fix" in r.summary
