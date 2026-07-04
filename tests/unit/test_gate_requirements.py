"""Tests for the gate external-dependency contract.

Covers the ``Requirement``/``Requirements`` declaration shape, the manifest
serialization (schema version + determinism), the in-process detection of
missing system tools, and the three-state result model: a missing *required*
tool yields a non-green ``ERROR`` (could-not-run), while a missing *optional*
tool does not block. The actionlint gate is the first real consumer.
"""

from __future__ import annotations

import json

import pytest

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
        # probe + import_name are part of the serialized contract.
        assert "probe" in bandit and "import_name" in bandit


class TestProbeKinds:
    """Detection probes the way kind/probe dictates (driven by the hard gates)."""

    def test_python_kind_probes_importability(self, monkeypatch, tmp_path):
        seen = {}

        def fake_module(name: str) -> bool:
            seen["name"] = name
            return True

        monkeypatch.setattr("slopmop.checks.base._module_available", fake_module)

        class _PyGate(_ToollessGate):
            def requirements(self) -> Requirements:
                return Requirements(items=(Requirement(kind="python", name="bandit"),))

        gate = _PyGate({})
        assert gate.is_requirement_satisfied(
            gate.requirements().items[0], str(tmp_path)
        )
        # Binary lookup is NOT used for a python/import requirement.
        assert seen["name"] == "bandit"
        # A python requirement has no resolvable path.
        assert (
            gate.resolve_requirement_path(gate.requirements().items[0], str(tmp_path))
            is None
        )

    def test_import_name_differs_from_install_name(self, monkeypatch, tmp_path):
        # detect-secrets installs under that name but imports as detect_secrets.
        importable = {"detect_secrets"}
        monkeypatch.setattr(
            "slopmop.checks.base._module_available", lambda n: n in importable
        )

        class _DS(_ToollessGate):
            def requirements(self) -> Requirements:
                return Requirements(
                    items=(
                        Requirement(
                            kind="python",
                            name="detect-secrets",
                            import_name="detect_secrets",
                        ),
                    )
                )

        gate = _DS({})
        assert gate.missing_requirements(str(tmp_path)) == []

    def test_semgrep_is_python_install_but_binary_probe(self, monkeypatch, tmp_path):
        # Probed as a binary even though kind=python (pip-installed CLI).
        monkeypatch.setattr(
            "slopmop.checks.base.find_tool",
            lambda name, root: "/usr/bin/semgrep" if name == "semgrep" else None,
        )
        # _module_available must NOT be consulted for a binary-probed req.
        monkeypatch.setattr(
            "slopmop.checks.base._module_available",
            lambda n: pytest.fail("import probe used for binary requirement"),
        )

        class _SG(_ToollessGate):
            def requirements(self) -> Requirements:
                return Requirements(
                    items=(Requirement(kind="python", name="semgrep", probe="binary"),)
                )

        gate = _SG({})
        assert gate.missing_requirements(str(tmp_path)) == []

    def test_env_kind_probes_environment(self, monkeypatch, tmp_path):
        class _EnvGate(_ToollessGate):
            def requirements(self) -> Requirements:
                return Requirements(
                    items=(Requirement(kind="env", name="SM_TEST_TOKEN"),)
                )

        gate = _EnvGate({})
        monkeypatch.delenv("SM_TEST_TOKEN", raising=False)
        assert [r.name for r in gate.missing_requirements(str(tmp_path))] == [
            "SM_TEST_TOKEN"
        ]
        monkeypatch.setenv("SM_TEST_TOKEN", "x")
        assert gate.missing_requirements(str(tmp_path)) == []

    def test_env_probe_honours_alternatives(self, monkeypatch, tmp_path):
        # GH_TOKEN with a GITHUB_TOKEN alternative — either set satisfies it.
        class _EnvAlt(_ToollessGate):
            def requirements(self) -> Requirements:
                return Requirements(
                    items=(
                        Requirement(
                            kind="env",
                            name="SM_PRIMARY_TOKEN",
                            alternatives=("SM_ALT_TOKEN",),
                        ),
                    )
                )

        gate = _EnvAlt({})
        monkeypatch.delenv("SM_PRIMARY_TOKEN", raising=False)
        monkeypatch.setenv("SM_ALT_TOKEN", "x")
        assert gate.missing_requirements(str(tmp_path)) == []


class TestHardGateRequirements:
    """The two API-stressing gates declare their real deps."""

    def test_security_declares_configured_scanners(self):
        from slopmop.checks.security import SecurityLocalCheck

        reqs = SecurityLocalCheck({"scanners": ["bandit", "semgrep"]}).requirements()
        by_name = {r.name: r for r in reqs.items}
        assert set(by_name) == {"bandit", "semgrep"}
        assert by_name["semgrep"].probe == "binary"  # pip install, binary probe
        assert all(r.optional for r in reqs.items)  # graceful degradation

    def test_security_full_declares_fixed_set_regardless_of_config(self):
        from slopmop.checks.security import SecurityCheck

        # run() executes a fixed scanner set ignoring `scanners`, so
        # requirements() must declare that whole set even when config trims it,
        # or doctor/the Action would under-install (#306 review).
        by_name = {
            r.name: r
            for r in SecurityCheck({"scanners": ["bandit"]}).requirements().items
        }
        assert set(by_name) == {
            "bandit",
            "semgrep",
            "detect-secrets",  # pragma: allowlist secret
            "pip-audit",
        }
        # pip-audit runs as `python -m pip_audit`, so it's import-probed.
        assert by_name["pip-audit"].probe == "import"
        assert by_name["pip-audit"].import_name == "pip_audit"

    def test_detect_secrets_import_name_declared(self):
        from slopmop.checks.security import SecurityLocalCheck

        reqs = SecurityLocalCheck(
            {"scanners": ["detect-secrets"]}  # pragma: allowlist secret
        ).requirements()
        (ds,) = reqs.items
        assert ds.import_name == "detect_secrets"  # pragma: allowlist secret

    def test_duplicate_strings_declares_scanner_and_node(self):
        from slopmop.checks.quality.duplicate_strings import StringDuplicationCheck

        reqs = StringDuplicationCheck({}).requirements().items
        by_name = {r.name: r for r in reqs}
        # The scanner is an npm tool (the vendored copy is dev-only, gitignored),
        # so a deployed slop-mop installs it from npm — pinned, optional.
        scanner = by_name["find-duplicate-strings"]
        assert scanner.kind == "npm"
        assert scanner.version == "3.1.1"
        assert scanner.optional is True
        # node is the runtime, also optional (gate WARNs if absent).
        assert by_name["node"].kind == "system"
        assert by_name["node"].optional is True


class TestPythonToolGates:
    """Python tool-gates declare their pip-installed CLIs with exact pins."""

    def test_dead_code_declares_vulture(self):
        from slopmop.checks.quality.dead_code import DeadCodeCheck

        (req,) = DeadCodeCheck({}).requirements().items
        assert req.name == "vulture"
        assert req.kind == "python" and req.probe == "binary"
        assert req.version == "2.14"
        assert req.optional is True  # missing vulture WARNs, doesn't block

    def test_complexity_declares_radon(self):
        from slopmop.checks.quality.complexity import ComplexityCheck

        (req,) = ComplexityCheck({}).requirements().items
        assert req.name == "radon"
        assert req.version == "6.0.1"
        assert req.optional is True  # missing radon WARNs, doesn't block

    def test_complexity_invokes_radon_via_resolved_path(self, monkeypatch, tmp_path):
        # radon is invoked by the path the requirement resolves (venv-aware),
        # not a bare name — same drift fix as semgrep/node.
        from slopmop.checks.quality.complexity import ComplexityCheck

        (tmp_path / "m.py").write_text("def f():\n    return 1\n")
        monkeypatch.setattr(
            "slopmop.checks.base.find_tool",
            lambda name, root: "/venv/bin/radon" if name == "radon" else None,
        )
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            from unittest.mock import MagicMock

            return MagicMock(returncode=0, output="", success=True)

        check = ComplexityCheck({"src_dirs": [str(tmp_path)]})
        monkeypatch.setattr(check, "_run_command", fake_run)
        check.run(str(tmp_path))
        assert captured["cmd"][0] == "/venv/bin/radon"


class TestVersionPinsTrackPyproject:
    """Exact pins must satisfy pyproject's declared floor (no drift below it)."""

    def _pyproject_floor(self, tool: str) -> str:
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        text = (root / "pyproject.toml").read_text()
        m = re.search(rf'"{re.escape(tool)}>=([0-9][^"]*)"', text)
        assert m, f"{tool} not found with a floor in pyproject.toml"
        return m.group(1)

    def test_pins_satisfy_pyproject_floors(self):
        from packaging.version import Version

        from slopmop.checks.quality.complexity import ComplexityCheck
        from slopmop.checks.quality.dead_code import DeadCodeCheck

        for gate in (DeadCodeCheck({}), ComplexityCheck({})):
            for req in gate.requirements().items:
                if req.version is None:
                    continue
                floor = self._pyproject_floor(req.name)
                assert Version(req.version) >= Version(
                    floor
                ), f"{req.name} pin {req.version} is below pyproject floor {floor}"


class TestAllToolGatesDeclareRequirements:
    """Registry-wide invariant: the requirements() contract is now the single
    source of "what external tools do gates need". These guard that the derived
    inventory stays complete and well-formed (the legacy required_tools /
    REQUIRED_TOOLS sources have been retired)."""

    def _registry(self):
        from slopmop.checks import ensure_checks_registered
        from slopmop.core.registry import get_registry

        ensure_checks_registered()
        return get_registry()

    def test_inventory_covers_the_core_first_party_tools(self):
        # The derived inventory must keep covering the tools the gates run — a
        # snapshot so a future gate that drops a requirement is caught.
        from slopmop.checks.tool_inventory import gate_tool_inventory

        tools = {t for t, _gate, _hint in gate_tool_inventory()}
        expected = {
            "black",
            "isort",
            "autoflake",
            "flake8",
            "ruff",
            "mypy",
            "pyright",
            "vulture",
            "radon",
            "bandit",
            "semgrep",
            "detect-secrets",  # pragma: allowlist secret
            "pip-audit",
            "flutter",
            "dart",
        }
        assert expected <= tools, f"inventory missing: {expected - tools}"

    def test_inventory_rows_carry_a_nonempty_install_hint(self):
        from slopmop.checks.tool_inventory import gate_tool_inventory

        for tool, gate, hint in gate_tool_inventory():
            assert hint, f"{tool} (in {gate}) has no install hint"

    def test_security_tools_share_the_extras_install_hint(self):
        # The extras-group remediation that REQUIRED_TOOLS used to hardcode is
        # now derived from requirements().
        from slopmop.checks.security import SecurityCheck

        for req in SecurityCheck({}).requirements().items:
            assert req.resolved_install_hint() == "pipx install slopmop[security]"

    def test_every_declared_requirement_is_well_formed(self):
        registry = self._registry()
        valid_kinds = {"system", "python", "npm", "env"}
        valid_probes = {"", "binary", "import", "env", "none"}
        for name in registry.list_checks():
            check = registry.get_check(name, {})
            if check is None:
                continue
            for req in check.requirements().items:
                assert req.kind in valid_kinds, f"{name}: bad kind {req.kind!r}"
                assert req.probe in valid_probes, f"{name}: bad probe {req.probe!r}"
                assert req.name, f"{name}: empty requirement name"
                # version is an exact pin or None — never a floor specifier.
                if req.version is not None:
                    assert not any(
                        c in req.version for c in "<>=~ "
                    ), f"{name}: {req.name} version {req.version!r} looks like a range"


class TestMigrationCoverage:
    """Exercise the consumer-migration code paths."""

    def test_resolved_install_hint_fallbacks(self):
        assert (
            Requirement(
                kind="python", name="x", install_hint="custom hint"
            ).resolved_install_hint()
            == "custom hint"
        )
        assert (
            Requirement(kind="python", name="bandit").resolved_install_hint()
            == "pip install bandit"
        )
        assert (
            Requirement(kind="npm", name="jscpd").resolved_install_hint()
            == "npm install -g jscpd"
        )
        assert (
            Requirement(kind="system", name="flutter").resolved_install_hint()
            == "Install flutter"
        )

    def test_inventory_skips_env_requirements(self, monkeypatch):
        # env-kind requirements are not installable tools — excluded.
        from slopmop.checks import tool_inventory

        class _FakeReg:
            def list_checks(self):
                return ["fake:gate"]

            def get_check(self, name, cfg):
                return _EnvAndToolGate({})

        class _EnvAndToolGate(_ToollessGate):
            def requirements(self):
                return Requirements(
                    items=(
                        Requirement(kind="env", name="GH_TOKEN"),
                        Requirement(kind="system", name="sometool"),
                    )
                )

        # tool_inventory lazily imports these — patch them at their source.
        import slopmop.checks as checks_mod
        import slopmop.core.registry as reg_mod

        monkeypatch.setattr(reg_mod, "get_registry", lambda: _FakeReg())
        monkeypatch.setattr(checks_mod, "ensure_checks_registered", lambda: None)
        rows = tool_inventory.gate_tool_inventory()
        names = {t for t, _g, _h in rows}
        assert "sometool" in names
        assert "GH_TOKEN" not in names

    def test_gate_preflight_missing_tools_uses_requirements(
        self, monkeypatch, tmp_path
    ):
        from pathlib import Path

        from slopmop.doctor.gate_preflight import _missing_required_tools

        monkeypatch.setattr("slopmop.checks.base.find_tool", lambda name, root: None)
        gate = _RequiredToolGate({})
        assert _missing_required_tools(gate, Path(tmp_path)) == ("frobnicate",)


class TestDoctorMigrationFixes:
    """Cover the #310 review-fix paths."""

    def test_resolved_install_hint_env_fallback(self):
        assert (
            Requirement(kind="env", name="GH_TOKEN").resolved_install_hint()
            == "Set the GH_TOKEN environment variable"
        )

    def test_load_repo_config_reads_sb_config(self, tmp_path):
        import json

        from slopmop.doctor.sm_env import load_repo_config

        assert load_repo_config(tmp_path) == {}  # missing file → {}
        (tmp_path / ".sb_config.json").write_text(json.dumps({"k": "v"}))
        assert load_repo_config(tmp_path) == {"k": "v"}
        (tmp_path / ".sb_config.json").write_text("not json{")
        assert load_repo_config(tmp_path) == {}  # invalid → {}

    def test_optional_missing_tool_does_not_block_preflight(
        self, monkeypatch, tmp_path
    ):
        from pathlib import Path

        from slopmop.doctor.gate_preflight import _missing_required_tools

        class _OptionalToolGate(_ToollessGate):
            def requirements(self) -> Requirements:
                return Requirements(
                    items=(
                        Requirement(kind="system", name="opt", optional=True),
                        Requirement(kind="system", name="req", optional=False),
                    )
                )

        monkeypatch.setattr("slopmop.checks.base.find_tool", lambda *_a: None)
        # Only the required tool counts toward "blocked".
        assert _missing_required_tools(_OptionalToolGate({}), Path(tmp_path)) == (
            "req",
        )

    def test_inventory_forwards_config_to_get_check(self, monkeypatch):
        # Config-awareness: the repo config reaches get_check so config-gated
        # requirements reflect the repo (#310 review).
        from unittest.mock import MagicMock

        from slopmop.checks import tool_inventory

        captured = {}

        class _Reg:
            def list_checks(self):
                return ["g"]

            def get_check(self, name, cfg):
                captured["cfg"] = cfg
                m = MagicMock()
                m.requirements.return_value = Requirements()
                return m

        import slopmop.checks as checks_mod
        import slopmop.core.registry as reg_mod

        monkeypatch.setattr(reg_mod, "get_registry", lambda: _Reg())
        monkeypatch.setattr(checks_mod, "ensure_checks_registered", lambda: None)
        tool_inventory.gate_tool_inventory({"x": 1})
        assert captured["cfg"] == {"x": 1}


class TestRequiredDepsManifest:
    """The sm doctor --required-deps emitter (feeds the v2 Action)."""

    def test_aggregate_dedups_by_tool_name(self, monkeypatch):
        from unittest.mock import MagicMock

        from slopmop.checks import tool_inventory

        black = Requirement(kind="python", name="black", version="26.5.1")

        def gate(*reqs):
            m = MagicMock()
            m.requirements.return_value = Requirements(items=tuple(reqs))
            return m

        # Two gates both declare black; the union lists it once. A None gate
        # (get_check miss) and a non-str entry are skipped defensively.
        gates = {
            "g1": gate(black, Requirement(kind="python", name="ruff")),
            "g2": gate(black),
            "g3": None,
        }
        import slopmop.checks as checks_mod
        import slopmop.core.registry as reg_mod

        monkeypatch.setattr(
            reg_mod,
            "get_registry",
            lambda: MagicMock(
                list_checks=lambda: [*gates, 123],  # 123 is a non-str entry
                get_check=lambda n, c: gates.get(n),
            ),
        )
        monkeypatch.setattr(checks_mod, "ensure_checks_registered", lambda: None)

        reqs = tool_inventory.aggregate_requirements()
        names = sorted(r.name for r in reqs.items)
        assert names == ["black", "ruff"]

    def test_cmd_doctor_routes_required_deps(self, capsys, tmp_path):
        import argparse

        from slopmop.cli.doctor import cmd_doctor

        args = argparse.Namespace(
            list_checks=False,
            required_deps=True,
            gates=False,
            project_root=str(tmp_path),
        )
        assert cmd_doctor(args) == 0
        doc = json.loads(capsys.readouterr().out)
        assert doc["schema_version"] == REQUIREMENTS_MANIFEST_SCHEMA_VERSION

    def test_emitter_outputs_schema_versioned_manifest(self, capsys, tmp_path):
        from slopmop.cli.doctor import _print_required_deps

        # The emitter filters by applicability, so the repo needs Python content
        # for the Python tool-gates (black/mypy/pyright/bandit) to apply.
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "__init__.py").write_text("x = 1\n")

        assert _print_required_deps(tmp_path) == 0
        doc = json.loads(capsys.readouterr().out)
        assert doc["schema_version"] == REQUIREMENTS_MANIFEST_SCHEMA_VERSION
        names = {r["name"] for r in doc["requirements"]}
        # Real gates' tools show up — the manifest is registry-derived.
        assert {"black", "mypy", "pyright", "bandit"} <= names
        # Each entry carries what the Action needs to install.
        for r in doc["requirements"]:
            assert r["kind"] in {"system", "python", "npm", "env"}
            assert "version" in r and "install_hint" in r

    def test_emitter_is_deterministic(self, capsys, tmp_path):
        from slopmop.cli.doctor import _print_required_deps

        _print_required_deps(tmp_path)
        first = capsys.readouterr().out
        _print_required_deps(tmp_path)
        second = capsys.readouterr().out
        assert first == second  # byte-stable for a fixed config

    @pytest.mark.parametrize(
        "first, second",
        [
            # Every identity field the aggregator compares must trip the raise.
            (
                Requirement(kind="python", name="black", version="26.5.1"),
                Requirement(kind="python", name="black", version="25.1.0"),
            ),  # version
            (
                Requirement(kind="python", name="black"),
                Requirement(kind="npm", name="black"),
            ),  # kind
            (
                Requirement(kind="python", name="black", probe="binary"),
                Requirement(kind="python", name="black", probe="import"),
            ),  # probe
            (
                Requirement(kind="python", name="black", import_name="black"),
                Requirement(kind="python", name="black", import_name="blackd"),
            ),  # import_name
        ],
    )
    def test_aggregate_raises_on_conflicting_declarations(
        self, monkeypatch, first, second
    ):
        from unittest.mock import MagicMock

        from slopmop.checks import tool_inventory

        def gate(*reqs):
            m = MagicMock()
            m.requirements.return_value = Requirements(items=tuple(reqs))
            return m

        # Two gates declare the same tool but disagree — must fail fast.
        gates = {"g1": gate(first), "g2": gate(second)}
        import slopmop.checks as checks_mod
        import slopmop.core.registry as reg_mod

        monkeypatch.setattr(
            reg_mod,
            "get_registry",
            lambda: MagicMock(
                list_checks=lambda: list(gates), get_check=lambda n, c: gates[n]
            ),
        )
        monkeypatch.setattr(checks_mod, "ensure_checks_registered", lambda: None)

        with pytest.raises(
            ValueError, match="Conflicting requirements for tool 'black'"
        ):
            tool_inventory.aggregate_requirements()

    def test_aggregate_filters_not_applicable_gates(self, monkeypatch):
        from unittest.mock import MagicMock

        from slopmop.checks import tool_inventory

        def gate(applicable, *reqs):
            m = MagicMock()
            m.requirements.return_value = Requirements(items=tuple(reqs))
            m.is_applicable.return_value = applicable
            return m

        gates = {
            "applies": gate(True, Requirement(kind="system", name="actionlint")),
            "nope": gate(False, Requirement(kind="system", name="dart")),
        }
        import slopmop.checks as checks_mod
        import slopmop.core.registry as reg_mod

        monkeypatch.setattr(
            reg_mod,
            "get_registry",
            lambda: MagicMock(
                list_checks=lambda: list(gates), get_check=lambda n, c: gates[n]
            ),
        )
        monkeypatch.setattr(checks_mod, "ensure_checks_registered", lambda: None)

        # With a project_root, the not-applicable gate's tool is excluded.
        filtered = tool_inventory.aggregate_requirements({}, project_root="/repo")
        assert sorted(r.name for r in filtered.items) == ["actionlint"]
        # Without a project_root, the full set is returned (back-compat).
        full = tool_inventory.aggregate_requirements({})
        assert sorted(r.name for r in full.items) == ["actionlint", "dart"]

    def test_aggregate_includes_gate_when_is_applicable_raises(self, monkeypatch):
        # Conservative: an is_applicable that blows up must not silently drop a
        # potentially-needed tool.
        from unittest.mock import MagicMock

        from slopmop.checks import tool_inventory

        boom = MagicMock()
        boom.requirements.return_value = Requirements(
            items=(Requirement(kind="system", name="actionlint"),)
        )
        boom.is_applicable.side_effect = RuntimeError("cannot tell")

        import slopmop.checks as checks_mod
        import slopmop.core.registry as reg_mod

        monkeypatch.setattr(
            reg_mod,
            "get_registry",
            lambda: MagicMock(list_checks=lambda: ["g"], get_check=lambda n, c: boom),
        )
        monkeypatch.setattr(checks_mod, "ensure_checks_registered", lambda: None)

        out = tool_inventory.aggregate_requirements({}, project_root="/repo")
        assert [r.name for r in out.items] == ["actionlint"]
