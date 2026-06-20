"""Tests for the gate external-dependency contract.

Covers the ``Requirement``/``Requirements`` declaration shape, the manifest
serialization (schema version + determinism), the in-process detection of
missing system tools, and the three-state result model: a missing *required*
tool yields a non-green ``ERROR`` (could-not-run), while a missing *optional*
tool does not block. The actionlint gate is the first real consumer.
"""

from __future__ import annotations

import json

from slopmop.checks.base import (
    REQUIREMENTS_MANIFEST_SCHEMA_VERSION,
    BaseCheck,
    Flaw,
    GateCategory,
    Requirement,
    Requirements,
    ToolContext,
    build_requirements_document,
)
from slopmop.checks.workflow import GitHubActionsHygieneCheck
from slopmop.core.result import CheckResult, CheckStatus


class _ToollessGate(BaseCheck):
    """Minimal gate that declares no requirements (exercises the default)."""

    tool_context = ToolContext.PURE

    @property
    def name(self) -> str:
        return "toolless"

    @property
    def display_name(self) -> str:
        return "toolless"

    @property
    def gate_description(self) -> str:
        return "no external tools"

    @property
    def category(self) -> GateCategory:
        return GateCategory.MYOPIA

    @property
    def flaw(self) -> Flaw:
        return Flaw.MYOPIA

    def is_applicable(self, project_root: str) -> bool:
        return True

    def run(self, project_root: str) -> CheckResult:
        return self._create_result(status=CheckStatus.PASSED, duration=0.0)


class _RequiredToolGate(_ToollessGate):
    """Gate that hard-requires a tool — exercises the could-not-run path."""

    @property
    def name(self) -> str:
        return "needs-frobnicate"

    def requirements(self) -> Requirements:
        return Requirements(
            items=(
                Requirement(
                    kind="system",
                    name="frobnicate",
                    reason="frobnicates the thing",
                    optional=False,
                ),
            )
        )

    def run(self, project_root: str) -> CheckResult:
        blocked = self.requirement_block_result(project_root)
        if blocked is not None:
            return blocked
        return self._create_result(status=CheckStatus.PASSED, duration=0.0)


class TestRequirementContract:
    def test_default_requirements_is_empty(self):
        assert _ToollessGate({}).requirements().items == ()

    def test_actionlint_declared_when_enabled(self):
        reqs = GitHubActionsHygieneCheck({"run_actionlint": True}).requirements()
        names = {r.name for r in reqs.items}
        assert names == {"actionlint"}
        (req,) = reqs.items
        assert req.kind == "system"
        assert req.optional is True  # native checks still run without it

    def test_actionlint_not_declared_when_disabled(self):
        reqs = GitHubActionsHygieneCheck({"run_actionlint": False}).requirements()
        assert reqs.items == ()


class TestMissingDetection:
    def test_missing_system_tool_is_reported(self, monkeypatch, tmp_path):
        monkeypatch.setattr("slopmop.checks.base.find_tool", lambda name, root: None)
        gate = _RequiredToolGate({})
        missing = gate.missing_requirements(str(tmp_path))
        assert [r.name for r in missing] == ["frobnicate"]

    def test_present_system_tool_is_not_reported(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "slopmop.checks.base.find_tool", lambda name, root: f"/usr/bin/{name}"
        )
        gate = _RequiredToolGate({})
        assert gate.missing_requirements(str(tmp_path)) == []

    def test_alternatives_satisfy_requirement(self, monkeypatch, tmp_path):
        # Only the alternative is present; the requirement is still satisfied.
        def fake_find(name: str, root: str):
            return "/usr/bin/podman" if name == "podman" else None

        monkeypatch.setattr("slopmop.checks.base.find_tool", fake_find)

        class _AltGate(_ToollessGate):
            def requirements(self) -> Requirements:
                return Requirements(
                    items=(
                        Requirement(
                            kind="system",
                            name="docker",
                            alternatives=("podman",),
                        ),
                    )
                )

        assert _AltGate({}).missing_requirements(str(tmp_path)) == []

    def test_path_resolution_and_missing_agree_on_alternatives(
        self, monkeypatch, tmp_path
    ):
        # The gate's own tool lookup and missing_requirements must agree: if an
        # alternative satisfies the requirement, the gate must resolve it (not
        # silently skip while doctor reports it present).
        def fake_find(name: str, root: str):
            return "/usr/bin/actionlint-bin" if name == "actionlint-bin" else None

        monkeypatch.setattr("slopmop.checks.base.find_tool", fake_find)

        class _AltActionlint(GitHubActionsHygieneCheck):
            def requirements(self) -> Requirements:
                return Requirements(
                    items=(
                        Requirement(
                            kind="system",
                            name="actionlint",
                            alternatives=("actionlint-bin",),
                            optional=True,
                        ),
                    )
                )

        gate = _AltActionlint({"run_actionlint": True})
        # Both views agree the requirement is satisfied via the alternative.
        assert gate.missing_requirements(str(tmp_path)) == []
        assert gate._actionlint_path(str(tmp_path)) == "/usr/bin/actionlint-bin"


class TestThreeStateResult:
    def test_missing_required_tool_yields_error_not_pass(self, monkeypatch, tmp_path):
        # The whole point: a required tool that isn't installed must be a
        # visible, non-green ERROR — never a silent PASSED.
        monkeypatch.setattr("slopmop.checks.base.find_tool", lambda name, root: None)
        result = _RequiredToolGate({}).run(str(tmp_path))
        assert result.status == CheckStatus.ERROR
        # ERROR fails the overall verdict (all_passed counts errors), so branch
        # protection is not bypassed by a broken environment.
        assert not result.passed
        assert "frobnicate" in (result.error or "")

    def test_present_required_tool_lets_gate_run(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "slopmop.checks.base.find_tool", lambda name, root: f"/usr/bin/{name}"
        )
        result = _RequiredToolGate({}).run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_missing_optional_tool_does_not_block(self, monkeypatch, tmp_path):
        # actionlint is optional — its absence must NOT produce an ERROR.
        monkeypatch.setattr("slopmop.checks.base.find_tool", lambda name, root: None)
        gate = GitHubActionsHygieneCheck({"run_actionlint": True})
        assert gate.requirement_block_result(str(tmp_path)) is None


class TestManifestDeterminism:
    def _scrambled(self) -> Requirements:
        # Deliberately out of (kind, name) order.
        return Requirements(
            items=(
                Requirement(kind="system", name="node"),
                Requirement(kind="python", name="bandit", version="1.7.5"),
                Requirement(kind="system", name="actionlint"),
                Requirement(kind="env", name="GH_TOKEN", optional=False),
            )
        )

    def test_manifest_is_sorted_and_stable(self):
        manifest = self._scrambled().to_manifest()
        order = [(e["kind"], e["name"]) for e in manifest]
        assert order == sorted(order)
        # Byte-stable across repeated serialization (no set/dict ordering leak).
        first = json.dumps(self._scrambled().to_manifest(), sort_keys=True)
        second = json.dumps(self._scrambled().to_manifest(), sort_keys=True)
        assert first == second

    def test_document_carries_schema_version(self):
        doc = build_requirements_document(self._scrambled())
        assert doc["schema_version"] == REQUIREMENTS_MANIFEST_SCHEMA_VERSION
        assert isinstance(doc["requirements"], list)
        # Pinned version round-trips for the consumer to install exactly.
        bandit = next(r for r in doc["requirements"] if r["name"] == "bandit")
        assert bandit["version"] == "1.7.5"
