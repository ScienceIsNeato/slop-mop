"""Tests for user-defined custom gates (issue #53)."""

import json

import pytest

from slopmop.checks.base import Flaw, GateCategory, GateLevel
from slopmop.checks.custom import (
    CustomGateError,
    _validate_spec,
    custom_gate_names,
    load_custom_gate_specs,
    make_custom_gate_class,
    register_custom_gates,
    scaffold_for_detected,
)
from slopmop.core.result import CheckStatus


# ── Spec validation ─────────────────────────────────────────────


class TestValidateSpec:
    def test_minimal_valid(self):
        _validate_spec({"name": "x", "command": "true"}, 0)

    def test_missing_name(self):
        with pytest.raises(CustomGateError, match="missing required field 'name'"):
            _validate_spec({"command": "true"}, 0)

    def test_missing_command(self):
        with pytest.raises(CustomGateError, match="missing required field 'command'"):
            _validate_spec({"name": "x"}, 0)

    def test_empty_name(self):
        with pytest.raises(CustomGateError, match="missing required field 'name'"):
            _validate_spec({"name": "", "command": "true"}, 0)

    def test_name_with_colon(self):
        with pytest.raises(CustomGateError, match="no ':' or '/'"):
            _validate_spec({"name": "a:b", "command": "true"}, 0)

    def test_name_with_slash(self):
        with pytest.raises(CustomGateError, match="no ':' or '/'"):
            _validate_spec({"name": "a/b", "command": "true"}, 0)

    def test_non_string_command(self):
        with pytest.raises(CustomGateError, match="'command' must be a string"):
            _validate_spec({"name": "x", "command": ["true"]}, 0)

    def test_bad_category(self):
        with pytest.raises(CustomGateError, match="unknown category"):
            _validate_spec(
                {"name": "x", "command": "true", "category": "nope"}, 0
            )

    def test_bad_level(self):
        with pytest.raises(CustomGateError, match="'level' must be"):
            _validate_spec(
                {"name": "x", "command": "true", "level": "both"}, 0
            )

    def test_bad_timeout_negative(self):
        with pytest.raises(CustomGateError, match="'timeout' must be"):
            _validate_spec(
                {"name": "x", "command": "true", "timeout": -1}, 0
            )

    def test_bad_timeout_zero(self):
        with pytest.raises(CustomGateError, match="'timeout' must be"):
            _validate_spec(
                {"name": "x", "command": "true", "timeout": 0}, 0
            )

    def test_bad_timeout_type(self):
        with pytest.raises(CustomGateError, match="'timeout' must be"):
            _validate_spec(
                {"name": "x", "command": "true", "timeout": "fast"}, 0
            )

    def test_error_message_includes_index_and_name(self):
        with pytest.raises(CustomGateError, match=r"custom_gates\[3\].*mygate"):
            _validate_spec(
                {"name": "mygate", "command": "true", "category": "bad"}, 3
            )


# ── Class factory ──────────────────────────────────────────────


class TestMakeCustomGateClass:
    def test_basic_properties(self):
        cls = make_custom_gate_class(
            {
                "name": "my-check",
                "description": "My project check",
                "category": "laziness",
                "command": "true",
                "level": "swab",
            }
        )
        inst = cls({})
        assert inst.name == "my-check"
        assert inst.category is GateCategory.LAZINESS
        assert inst.flaw is Flaw.LAZINESS
        assert inst.full_name == "laziness:my-check"
        assert "My project check" in inst.display_name
        assert "⚙" in inst.display_name
        assert cls.level is GateLevel.SWAB
        assert cls.is_custom is True

    def test_defaults(self):
        cls = make_custom_gate_class({"name": "x", "command": "true"})
        inst = cls({})
        assert inst.category is GateCategory.GENERAL
        assert cls.level is GateLevel.SWAB

    def test_scour_level(self):
        cls = make_custom_gate_class(
            {"name": "x", "command": "true", "level": "scour"}
        )
        assert cls.level is GateLevel.SCOUR

    def test_is_applicable_always_true(self, tmp_path):
        cls = make_custom_gate_class({"name": "x", "command": "true"})
        assert cls({}).is_applicable(str(tmp_path)) is True

    def test_class_name_is_stable(self):
        cls = make_custom_gate_class({"name": "go-vet", "command": "true"})
        assert "go_vet" in cls.__name__

    def test_general_maps_to_laziness_flaw(self):
        cls = make_custom_gate_class(
            {"name": "x", "command": "true", "category": "general"}
        )
        # Flaw enum has no GENERAL member — fall back sensibly.
        assert cls({}).flaw is Flaw.LAZINESS

    def test_pr_maps_to_myopia_flaw(self):
        cls = make_custom_gate_class(
            {"name": "x", "command": "true", "category": "pr"}
        )
        assert cls({}).flaw is Flaw.MYOPIA

    def test_timeout_capped(self):
        # Should not explode on huge timeout values — cap silently.
        cls = make_custom_gate_class(
            {"name": "x", "command": "true", "timeout": 99999}
        )
        # Just verify it constructs; cap is internal.
        assert cls({}).name == "x"


# ── Execution ───────────────────────────────────────────────────


class TestCustomGateRun:
    def test_exit_zero_passes(self, tmp_path):
        cls = make_custom_gate_class({"name": "ok", "command": "true"})
        result = cls({}).run(str(tmp_path))
        assert result.status is CheckStatus.PASSED

    def test_nonzero_exit_fails(self, tmp_path):
        cls = make_custom_gate_class({"name": "bad", "command": "false"})
        result = cls({}).run(str(tmp_path))
        assert result.status is CheckStatus.FAILED
        assert "exit 1" in result.error

    def test_stdout_captured_on_fail(self, tmp_path):
        cls = make_custom_gate_class(
            {"name": "shouting", "command": "echo LOUD && false"}
        )
        result = cls({}).run(str(tmp_path))
        assert result.status is CheckStatus.FAILED
        assert "LOUD" in result.output

    def test_stderr_captured_on_fail(self, tmp_path):
        cls = make_custom_gate_class(
            {"name": "err", "command": "echo BAD >&2 && false"}
        )
        result = cls({}).run(str(tmp_path))
        assert result.status is CheckStatus.FAILED
        assert "BAD" in result.output

    def test_shell_metacharacters_work(self, tmp_path):
        # This is the whole point — the CommandValidator would reject
        # '|' and '&&', but custom gates are user-trusted and use a
        # shell directly.
        cls = make_custom_gate_class(
            {"name": "piped", "command": "echo hello | grep -q hello"}
        )
        result = cls({}).run(str(tmp_path))
        assert result.status is CheckStatus.PASSED

    def test_issue53_example_syntax_runs(self, tmp_path):
        # The literal example from issue #53: negated grep with a pipe
        # inside the pattern.  Should not trip the validator.
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "clean.py").write_text("x = 1\n")
        cls = make_custom_gate_class(
            {
                "name": "no-debugger-imports",
                "command": "! grep -rn 'import pdb\\|import debugpy' src/",
            }
        )
        result = cls({}).run(str(tmp_path))
        assert result.status is CheckStatus.PASSED

    def test_issue53_example_fails_when_debugger_found(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "dirty.py").write_text("import pdb\n")
        cls = make_custom_gate_class(
            {
                "name": "no-debugger-imports",
                "command": "! grep -rn 'import pdb\\|import debugpy' src/",
            }
        )
        result = cls({}).run(str(tmp_path))
        assert result.status is CheckStatus.FAILED

    def test_runs_in_project_root(self, tmp_path):
        (tmp_path / "sentinel.txt").write_text("here")
        cls = make_custom_gate_class(
            {"name": "cwd", "command": "test -f sentinel.txt"}
        )
        result = cls({}).run(str(tmp_path))
        assert result.status is CheckStatus.PASSED

    def test_timeout(self, tmp_path):
        cls = make_custom_gate_class(
            {"name": "slow", "command": "sleep 5", "timeout": 1}
        )
        result = cls({}).run(str(tmp_path))
        assert result.status is CheckStatus.FAILED
        assert "timed out" in result.error
        assert "timeout" in result.fix_suggestion.lower()

    def test_fix_suggestion_on_fail(self, tmp_path):
        cls = make_custom_gate_class({"name": "x", "command": "false"})
        result = cls({}).run(str(tmp_path))
        assert result.fix_suggestion
        assert "false" in result.fix_suggestion

    def test_full_name_in_result(self, tmp_path):
        cls = make_custom_gate_class(
            {"name": "x", "command": "true", "category": "laziness"}
        )
        result = cls({}).run(str(tmp_path))
        assert result.name == "laziness:x"


# ── Config loading ──────────────────────────────────────────────


def _write_config(tmp_path, body):
    (tmp_path / ".sb_config.json").write_text(json.dumps(body))


class TestLoadCustomGateSpecs:
    def test_no_config_file(self, tmp_path):
        assert load_custom_gate_specs(str(tmp_path)) == []

    def test_no_custom_gates_key(self, tmp_path):
        _write_config(tmp_path, {"version": "1.0"})
        assert load_custom_gate_specs(str(tmp_path)) == []

    def test_custom_gates_null(self, tmp_path):
        _write_config(tmp_path, {"custom_gates": None})
        assert load_custom_gate_specs(str(tmp_path)) == []

    def test_loads_valid_specs(self, tmp_path):
        _write_config(
            tmp_path,
            {
                "custom_gates": [
                    {"name": "a", "command": "true"},
                    {"name": "b", "command": "false", "category": "laziness"},
                ]
            },
        )
        specs = load_custom_gate_specs(str(tmp_path))
        assert len(specs) == 2
        assert specs[0]["name"] == "a"

    def test_rejects_non_list(self, tmp_path):
        _write_config(tmp_path, {"custom_gates": {"name": "x"}})
        with pytest.raises(CustomGateError, match="must be a list"):
            load_custom_gate_specs(str(tmp_path))

    def test_rejects_non_dict_entry(self, tmp_path):
        _write_config(tmp_path, {"custom_gates": ["not-a-dict"]})
        with pytest.raises(CustomGateError, match="must be an object"):
            load_custom_gate_specs(str(tmp_path))

    def test_rejects_invalid_spec(self, tmp_path):
        _write_config(tmp_path, {"custom_gates": [{"name": "x"}]})  # no command
        with pytest.raises(CustomGateError, match="'command'"):
            load_custom_gate_specs(str(tmp_path))

    def test_malformed_json_returns_empty(self, tmp_path):
        (tmp_path / ".sb_config.json").write_text("{not json")
        assert load_custom_gate_specs(str(tmp_path)) == []


# ── Registry integration ────────────────────────────────────────


class TestRegisterCustomGates:
    def _reset(self):
        # Fresh registry + clear our dedup set so tests are isolated.
        import slopmop.checks.custom as custom_mod
        import slopmop.core.registry as registry_mod

        registry_mod._default_registry = None
        custom_mod._registered_custom.clear()

    def test_registers_into_registry(self, tmp_path):
        from slopmop.core.registry import get_registry

        self._reset()
        _write_config(
            tmp_path,
            {"custom_gates": [{"name": "foo", "command": "true", "category": "laziness"}]},
        )
        names = register_custom_gates(str(tmp_path))
        assert names == ["laziness:foo"]
        assert "laziness:foo" in get_registry().list_checks()

    def test_appears_in_level_listing(self, tmp_path):
        from slopmop.core.registry import get_registry

        self._reset()
        _write_config(
            tmp_path,
            {
                "custom_gates": [
                    {"name": "fast", "command": "true", "level": "swab"},
                    {"name": "slow", "command": "true", "level": "scour"},
                ]
            },
        )
        register_custom_gates(str(tmp_path))
        reg = get_registry()
        swab = reg.get_gate_names_for_level(GateLevel.SWAB)
        scour = reg.get_gate_names_for_level(GateLevel.SCOUR)
        assert "general:fast" in swab
        assert "general:fast" in scour  # scour is superset
        assert "general:slow" not in swab
        assert "general:slow" in scour

    def test_idempotent(self, tmp_path):
        self._reset()
        _write_config(
            tmp_path, {"custom_gates": [{"name": "x", "command": "true"}]}
        )
        first = register_custom_gates(str(tmp_path))
        second = register_custom_gates(str(tmp_path))
        assert first == second  # Same names, no crash, no dup registration

    def test_no_config_is_noop(self, tmp_path):
        self._reset()
        assert register_custom_gates(str(tmp_path)) == []


# ── Name lookup for status badging ──────────────────────────────


class TestCustomGateNames:
    def test_returns_full_names(self, tmp_path):
        _write_config(
            tmp_path,
            {
                "custom_gates": [
                    {"name": "a", "command": "true", "category": "laziness"},
                    {"name": "b", "command": "true"},  # default general
                ]
            },
        )
        names = custom_gate_names(str(tmp_path))
        assert names == {"laziness:a", "general:b"}

    def test_swallows_malformed(self, tmp_path):
        # status.py calls this for badging — should NOT raise even on
        # a bad spec, because `sm status` is an observatory.
        _write_config(tmp_path, {"custom_gates": [{"name": "x"}]})  # bad
        assert custom_gate_names(str(tmp_path)) == set()

    def test_no_config(self, tmp_path):
        assert custom_gate_names(str(tmp_path)) == set()


# ── Init scaffolding ─────────────────────────────────────────────


class TestScaffoldForDetected:
    def test_go(self):
        out = scaffold_for_detected({"has_go": True})
        names = {s["name"] for s in out}
        assert "go-vet" in names
        assert "go-build" in names
        assert "gofmt-drift" in names

    def test_rust(self):
        out = scaffold_for_detected({"has_rust": True})
        names = {s["name"] for s in out}
        assert "cargo-check" in names
        assert "cargo-clippy" in names
        assert "cargo-fmt-drift" in names

    def test_c(self):
        out = scaffold_for_detected({"has_c": True})
        names = {s["name"] for s in out}
        assert "make-check" in names

    def test_polyglot(self):
        # next.js is JS+Rust — scaffold the Rust side.
        out = scaffold_for_detected({"has_rust": True, "has_javascript": True})
        names = {s["name"] for s in out}
        assert "cargo-check" in names

    def test_pure_python_scaffolds_nothing(self):
        assert scaffold_for_detected({"has_python": True}) == []

    def test_every_scaffold_gate_is_valid(self):
        # Dogfood: every gate we scaffold must pass our own validator.
        out = scaffold_for_detected(
            {"has_go": True, "has_rust": True, "has_c": True}
        )
        for i, spec in enumerate(out):
            _validate_spec(spec, i)  # Should not raise


# ── Detection plumbing ───────────────────────────────────────────


class TestLanguageDetection:
    def test_go_via_gomod(self, tmp_path):
        from slopmop.cli.detection import detect_project_type

        (tmp_path / "go.mod").write_text("module example.com/x\n")
        d = detect_project_type(tmp_path)
        assert d["has_go"] is True

    def test_rust_via_cargo(self, tmp_path):
        from slopmop.cli.detection import detect_project_type

        (tmp_path / "Cargo.toml").write_text("[package]\nname = 'x'\n")
        d = detect_project_type(tmp_path)
        assert d["has_rust"] is True

    def test_c_via_configure(self, tmp_path):
        from slopmop.cli.detection import detect_project_type

        (tmp_path / "configure.ac").write_text("AC_INIT\n")
        d = detect_project_type(tmp_path)
        assert d["has_c"] is True

    def test_c_via_makefile_with_sources(self, tmp_path):
        from slopmop.cli.detection import detect_project_type

        (tmp_path / "Makefile").write_text("all:\n")
        (tmp_path / "main.c").write_text("int main(){}\n")
        d = detect_project_type(tmp_path)
        assert d["has_c"] is True

    def test_plain_makefile_not_c(self, tmp_path):
        # Makefile alone (no .c files) is not a C project — could be
        # anything.
        from slopmop.cli.detection import detect_project_type

        (tmp_path / "Makefile").write_text("all:\n")
        d = detect_project_type(tmp_path)
        assert d["has_c"] is False

    def test_go_not_triggered_by_stray_go_file(self, tmp_path):
        # Deliberately NOT globbing *.go — polyglot repos vendor Go
        # examples all the time.
        from slopmop.cli.detection import detect_project_type

        (tmp_path / "example.go").write_text("package main\n")
        d = detect_project_type(tmp_path)
        assert d["has_go"] is False
