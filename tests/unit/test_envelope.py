"""Tests for the slop-mop response envelope (machine interface v3).

The envelope is the invariant frame every verb speaks. These tests pin
the contract: the builder produces schema-conformant objects, the value
objects reject malformed input at construction, and the packaged schema
is itself a valid JSON Schema. Together they are the local half of the
"format predictability" guarantee — the conformance suite in
``test_machine_interface_conformance.py`` is the other half.
"""

import json

import pytest

from slopmop.reporting import envelope as env
from slopmop.reporting.envelope import (
    ENVELOPE_SCHEMA_VERSION,
    Diagnostic,
    NextStep,
    Status,
    available_data_schemas,
    build_envelope,
    load_envelope_schema,
    render_envelope,
    status_for_exit_code,
)


def _validator():
    """Return a Draft 2020-12 validator bound to the envelope schema."""
    jsonschema = pytest.importorskip("jsonschema")
    return jsonschema.Draft202012Validator(load_envelope_schema())


# ── schema document ──────────────────────────────────────────────


def test_packaged_schema_is_valid_json_schema() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(load_envelope_schema())


def test_schema_version_matches_const() -> None:
    schema = load_envelope_schema()
    const = schema["properties"]["schema"]["const"]  # type: ignore[index]
    assert const == ENVELOPE_SCHEMA_VERSION == "slopmop/v3"


# ── builder conformance ──────────────────────────────────────────


def test_minimal_envelope_validates() -> None:
    env = build_envelope(command="swab", status=Status.OK, exit_code=0, data={})
    assert not list(_validator().iter_errors(env))


def test_minimal_envelope_omits_optional_arrays() -> None:
    env = build_envelope(command="swab", status=Status.OK, exit_code=0, data={})
    assert "next_steps" not in env
    assert "diagnostics" not in env


def test_full_envelope_validates() -> None:
    env = build_envelope(
        command="swab",
        status=Status.FAIL,
        exit_code=1,
        data={"summary": {"failed": 1}},
        next_steps=[
            NextStep(action="inspect", command="cat log", reason="first to fix"),
        ],
        diagnostics=[
            Diagnostic(
                code="cached_results_present",
                level="warn",
                message="some results came from cache",
                suggested_command="sm swab --no-cache",
            ),
        ],
    )
    assert not list(_validator().iter_errors(env))


def test_envelope_carries_required_keys() -> None:
    env = build_envelope(command="status", status=Status.INFO, exit_code=0, data={})
    assert env["schema"] == "slopmop/v3"
    assert env["command"] == "status"
    assert env["status"] == "info"
    assert env["exit_code"] == 0
    assert env["data"] == {}


@pytest.mark.parametrize("status", list(Status))
def test_every_status_value_validates(status: Status) -> None:
    env = build_envelope(command="x", status=status, exit_code=0, data={})
    assert not list(_validator().iter_errors(env))


# ── negative controls — the schema must reject malformed envelopes ──


def test_unknown_status_is_rejected() -> None:
    env = build_envelope(command="x", status=Status.OK, exit_code=0, data={})
    env["status"] = "bogus"
    assert list(_validator().iter_errors(env))


def test_extra_top_level_key_is_rejected() -> None:
    env = build_envelope(command="x", status=Status.OK, exit_code=0, data={})
    env["surprise"] = 1
    assert list(_validator().iter_errors(env))


def test_missing_required_key_is_rejected() -> None:
    env = build_envelope(command="x", status=Status.OK, exit_code=0, data={})
    del env["data"]
    assert list(_validator().iter_errors(env))


# ── value objects validate at construction ───────────────────────


def test_next_step_rejects_unknown_action() -> None:
    with pytest.raises(ValueError):
        NextStep(action="teleport")


def test_next_step_emits_fixed_key_set() -> None:
    d = NextStep(action="rerun").to_dict()
    assert d == {"action": "rerun", "command": None, "reason": None}


def test_diagnostic_rejects_unknown_level() -> None:
    with pytest.raises(ValueError):
        Diagnostic(code="c", level="fatal", message="m")


def test_diagnostic_rejects_empty_code() -> None:
    with pytest.raises(ValueError):
        Diagnostic(code="", level="info", message="m")


def test_diagnostic_omits_absent_suggested_command() -> None:
    d = Diagnostic(code="c", level="info", message="m").to_dict()
    assert "suggested_command" not in d


# ── render + helpers ─────────────────────────────────────────────


def test_render_envelope_is_compact_parseable_json() -> None:
    raw = render_envelope(
        command="status", status=Status.INFO, exit_code=0, data={"x": 1}
    )
    assert ", " not in raw  # compact separators
    assert json.loads(raw)["data"] == {"x": 1}


def test_status_for_exit_code() -> None:
    assert status_for_exit_code(0) is Status.OK
    assert status_for_exit_code(1) is Status.FAIL
    assert status_for_exit_code(2) is Status.FAIL


# ── packaged schema loading ──────────────────────────────────────


def test_load_packaged_schema_rejects_non_object(monkeypatch) -> None:
    """A schema file that parses to a non-object is a packaging error."""
    monkeypatch.setattr(env.json, "loads", lambda _text: ["not", "an", "object"])
    with pytest.raises(ValueError, match="not a JSON object"):
        env._load_packaged_schema("envelope.json")


def test_available_data_schemas_empty_when_dir_missing(monkeypatch) -> None:
    """No packaged ``data/`` directory yields an empty catalog, not a crash."""

    class _FakeResource:
        def joinpath(self, _name: str) -> "_FakeResource":
            return self

        def is_dir(self) -> bool:
            return False

    monkeypatch.setattr(env.resources, "files", lambda _pkg: _FakeResource())
    assert available_data_schemas() == []
