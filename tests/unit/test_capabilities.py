"""Tests for `sm capabilities` — the machine-interface discovery catalog.

These pin the catalog's invariants: it speaks the envelope, it advertises
every registered verb, its data-schema references match what actually
ships, and each gate entry carries the metadata an agent needs to plan a
run. The output-conformance check (envelope + capabilities data schema)
lives in test_machine_interface_conformance.py.
"""

import argparse
import json

import pytest

from slopmop import sm
from slopmop.cli.capabilities import _VERB_CATALOG, cmd_capabilities
from slopmop.reporting.envelope import available_data_schemas


def _capabilities_envelope(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    rc = cmd_capabilities(argparse.Namespace(project_root="."))
    assert rc == 0
    return json.loads(capsys.readouterr().out)


def test_capabilities_speaks_the_envelope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = _capabilities_envelope(capsys)
    assert env["schema"] == "slopmop/v3"
    assert env["command"] == "capabilities"
    assert env["status"] == "info"
    assert env["exit_code"] == 0


def test_data_carries_version_and_schema_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = _capabilities_envelope(capsys)["data"]
    assert isinstance(data, dict)
    assert data["schema_version"] == "slopmop/v3"
    assert isinstance(data["version"], str) and data["version"]


def test_catalog_lists_every_registered_verb(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The catalog must describe every verb the parser exposes — a missing
    # verb means an agent can't predict that command's contract.
    parser = sm.create_parser()
    subparsers_action = next(
        a
        for a in parser._actions  # type: ignore[attr-defined]
        if isinstance(a, argparse._SubParsersAction)
    )
    registered_verbs = set(subparsers_action.choices.keys())

    data = _capabilities_envelope(capsys)["data"]
    assert isinstance(data, dict)
    verbs = data["verbs"]
    assert isinstance(verbs, list)
    cataloged = {v["name"] for v in verbs}  # type: ignore[index]
    assert registered_verbs <= cataloged, registered_verbs - cataloged


def test_verb_data_schema_refs_match_shipped_schemas(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A non-null data_schema must point at a schema that actually ships;
    # a verb with no shipped schema must advertise null, not a dead link.
    declared = set(available_data_schemas())
    data = _capabilities_envelope(capsys)["data"]
    assert isinstance(data, dict)
    for verb in data["verbs"]:  # type: ignore[union-attr]
        name = verb["name"]
        ref = verb["data_schema"]
        if name in declared:
            assert ref == f"https://slopmop.dev/schemas/v3/data/{name}.json"
        else:
            assert ref is None


def test_capabilities_self_describes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # capabilities has shipped its own data schema, so it must point at it.
    data = _capabilities_envelope(capsys)["data"]
    assert isinstance(data, dict)
    entry = next(
        v for v in data["verbs"] if v["name"] == "capabilities"  # type: ignore[union-attr,index]
    )
    assert entry["data_schema"] == (
        "https://slopmop.dev/schemas/v3/data/capabilities.json"
    )


def test_gate_entries_carry_required_metadata(
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = _capabilities_envelope(capsys)["data"]
    assert isinstance(data, dict)
    gates = data["gates"]
    assert isinstance(gates, list) and gates
    required = {
        "name",
        "category",
        "category_label",
        "emoji",
        "level",
        "role",
        "description",
        "applicable",
    }
    for gate in gates:
        assert required <= set(gate.keys())  # type: ignore[union-attr]
        assert gate["level"] in ("swab", "scour")  # type: ignore[index]
        assert gate["role"] in ("foundation", "diagnostic")  # type: ignore[index]


def test_inapplicable_gates_explain_themselves(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # When a gate is skipped, an agent needs to know why — otherwise it
    # can't tell "irrelevant here" from "broken".
    data = _capabilities_envelope(capsys)["data"]
    assert isinstance(data, dict)
    for gate in data["gates"]:  # type: ignore[union-attr]
        if gate["applicable"] is False:
            assert isinstance(gate.get("skip_reason"), str)
            assert gate["skip_reason"]


def test_catalog_groups_are_in_the_known_vocabulary() -> None:
    # Groups must stay within the enum the capabilities data schema pins,
    # or the output stops validating.
    allowed = {
        "core",
        "workflow",
        "setup",
        "config",
        "introspection",
        "feedback",
        "escalation",
    }
    for verb in _VERB_CATALOG:
        assert verb["group"] in allowed
