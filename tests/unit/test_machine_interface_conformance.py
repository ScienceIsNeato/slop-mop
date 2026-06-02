"""Conformance harness for the slop-mop machine interface.

This is the enforcement half of the format-predictability guarantee. As
each verb is migrated onto the envelope it gains a packaged ``data``
schema and an entry here; the test then runs the verb in ``--format
json`` and asserts the output validates against the composed output
schema (envelope + that verb's data schema). A verb is not "done" until
it appears in this suite.

The schema-level tests below already run against every packaged schema,
so a malformed or non-composable data schema fails CI the moment it
lands — before any verb wiring exists.
"""

import argparse
import json
from typing import Dict

import pytest

from slopmop import sm
from slopmop.cli.schema import _compose_output_schema
from slopmop.reporting.envelope import (
    available_data_schemas,
    load_data_schema,
    load_envelope_schema,
)


def _check_schema(schema: Dict[str, object]) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(schema)


# ── sm schema CLI ────────────────────────────────────────────────


def test_sm_schema_cli_emits_valid_envelope_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sm.main(["schema"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["$id"].endswith("/v3/envelope.json")
    _check_schema(out)


def test_sm_schema_unknown_verb_reports_and_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sm.main(["schema", "does-not-exist"])
    assert rc == 1
    assert "No data schema" in capsys.readouterr().out


# ── every packaged data schema is valid and composes ─────────────


def test_all_data_schemas_are_valid_json_schema() -> None:
    for verb in available_data_schemas():
        schema = load_data_schema(verb)
        assert schema is not None
        _check_schema(schema)


def test_composed_output_schema_is_valid_and_replaces_data() -> None:
    for verb in available_data_schemas():
        data_schema = load_data_schema(verb)
        assert data_schema is not None
        composed = _compose_output_schema(verb, data_schema)
        _check_schema(composed)
        # The data slot is the verb's schema, not the bare envelope default.
        assert composed["properties"]["data"] == data_schema  # type: ignore[index]


def test_envelope_schema_data_is_open_object_by_default() -> None:
    # The bare envelope must accept any object in data; per-verb schemas
    # are what narrow it. If this regresses, unmigrated verbs break.
    schema = load_envelope_schema()
    assert schema["properties"]["data"]["type"] == "object"  # type: ignore[index]


# ── per-verb output conformance ──────────────────────────────────
#
# As verbs migrate onto the envelope, add them here. Each is run for
# real and its parsed stdout is validated against the composed output
# schema (envelope + that verb's data schema).
_MIGRATED_VERBS: list[str] = [
    "capabilities",
    "swab",
    "scour",
    "status",
    "audit",
    "doctor",
    "wake-angry-drunk-captain",
    "barnacle",
    "buff",
    "refit",
]


def _synthetic_report(level: str) -> "object":
    """Build a RunReport exercising passed/failed/warned/skipped + findings.

    Validation conformance must not shell out to a real gate run (slow,
    environment-dependent). A synthetic report drives JsonAdapter through
    every payload branch — actionable results with findings, a passed
    name list, the fix-first pointer — so the schema is checked against
    real adapter output, not a hand-built fixture.
    """
    from slopmop.core.registry import get_registry
    from slopmop.core.result import (
        CheckResult,
        CheckStatus,
        ExecutionSummary,
        Finding,
        FindingLevel,
        ScopeInfo,
        SkipReason,
    )
    from slopmop.reporting.report import RunReport

    results = [
        CheckResult(name="quality:lint", status=CheckStatus.PASSED, duration=0.4),
        CheckResult(
            name="quality:format",
            status=CheckStatus.FAILED,
            duration=1.2,
            error="2 files need formatting",
            fix_suggestion="run the formatter",
            category="quality",
            role="foundation",
            scope=ScopeInfo(files=3, lines=120),
            findings=[
                Finding(
                    message="line too long",
                    level=FindingLevel.WARNING,
                    file="a.py",
                    line=10,
                    column=80,
                    rule_id="E501",
                )
            ],
        ),
        CheckResult(
            name="security:audit",
            status=CheckStatus.WARNED,
            duration=0.3,
            error="1 advisory",
            role="diagnostic",
        ),
        CheckResult(
            name="js:eslint",
            status=CheckStatus.NOT_APPLICABLE,
            duration=0.0,
            skip_reason=SkipReason.NOT_APPLICABLE,
        ),
    ]
    summary = ExecutionSummary.from_results(results, duration=1.9)
    return RunReport.from_summary(
        summary,
        level=level,
        registry=get_registry(),
        sort_actionable_by_remediation_order=True,
    )


@pytest.mark.parametrize("level", ["swab", "scour"])
def test_validation_output_conforms_to_schema(level: str) -> None:
    from slopmop.checks import ensure_checks_registered
    from slopmop.reporting.adapters import JsonAdapter

    ensure_checks_registered()
    report = _synthetic_report(level)
    envelope = JsonAdapter.render(report)  # type: ignore[arg-type]

    assert envelope["command"] == level
    assert envelope["status"] == "fail"
    assert envelope["exit_code"] == 1

    data_schema = load_data_schema(level)
    assert data_schema is not None
    composed = _compose_output_schema(level, data_schema)

    jsonschema = pytest.importorskip("jsonschema")
    errors = list(jsonschema.Draft202012Validator(composed).iter_errors(envelope))
    assert not errors, [e.message for e in errors]


@pytest.mark.parametrize("verb", ["swab", "scour"])
def test_validation_describe_emits_output_schema(
    verb: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # `sm <verb> --describe` must emit the composed output schema without
    # running any gates — the predict-before-run path.
    rc = sm.main([verb, "--describe"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["$id"].endswith(f"/v3/output/{verb}.json")
    _check_schema(out)


def test_capabilities_output_conforms_to_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sm.main(["capabilities"])
    assert rc == 0
    envelope = json.loads(capsys.readouterr().out)

    data_schema = load_data_schema("capabilities")
    assert data_schema is not None
    composed = _compose_output_schema("capabilities", data_schema)

    jsonschema = pytest.importorskip("jsonschema")
    errors = list(jsonschema.Draft202012Validator(composed).iter_errors(envelope))
    assert not errors, [e.message for e in errors]


def test_capabilities_describe_emits_its_output_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # `sm capabilities --describe` must emit the same composed output
    # schema an agent would compose by hand — the predict-before-run path.
    rc = sm.main(["capabilities", "--describe"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["$id"].endswith("/v3/output/capabilities.json")
    _check_schema(out)


def test_audit_output_conforms_to_schema(
    tmp_path: "object",
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Run with git+gates disabled: fast, deterministic, and still drives
    # the envelope path. The data payload is then just the two required
    # keys, which must validate against the composed schema.
    rc = sm.main(
        [
            "audit",
            "--json",
            "--no-git",
            "--no-gates",
            "-q",
            "--project-root",
            str(tmp_path),
        ]
    )
    assert rc == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["command"] == "audit"
    assert envelope["status"] == "info"

    data_schema = load_data_schema("audit")
    assert data_schema is not None
    composed = _compose_output_schema("audit", data_schema)

    jsonschema = pytest.importorskip("jsonschema")
    errors = list(jsonschema.Draft202012Validator(composed).iter_errors(envelope))
    assert not errors, [e.message for e in errors]


def test_audit_describe_emits_output_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sm.main(["audit", "--describe"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["$id"].endswith("/v3/output/audit.json")
    _check_schema(out)


def test_doctor_output_conforms_to_schema(
    tmp_path: "object",
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Run one cheap check in JSON mode: drives the health-payload branch
    # of the doctor data schema's oneOf.
    rc = sm.main(
        ["doctor", "runtime.platform", "--json", "--project-root", str(tmp_path)]
    )
    assert rc in (0, 1)
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["command"] == "doctor"

    data_schema = load_data_schema("doctor")
    assert data_schema is not None
    composed = _compose_output_schema("doctor", data_schema)

    jsonschema = pytest.importorskip("jsonschema")
    errors = list(jsonschema.Draft202012Validator(composed).iter_errors(envelope))
    assert not errors, [e.message for e in errors]


def test_doctor_gates_output_conforms_to_schema(
    tmp_path: "object",
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The --gates tree drives the other branch of the oneOf.
    rc = sm.main(["doctor", "--gates", "--json", "--project-root", str(tmp_path)])
    assert rc == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["command"] == "doctor"
    assert "swab" in envelope["data"] and "scour" in envelope["data"]

    data_schema = load_data_schema("doctor")
    assert data_schema is not None
    composed = _compose_output_schema("doctor", data_schema)

    jsonschema = pytest.importorskip("jsonschema")
    errors = list(jsonschema.Draft202012Validator(composed).iter_errors(envelope))
    assert not errors, [e.message for e in errors]


def test_doctor_describe_emits_output_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sm.main(["doctor", "--describe"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["$id"].endswith("/v3/output/doctor.json")
    _check_schema(out)


def test_status_output_conforms_to_schema(
    tmp_path: "object",
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The dashboard runs no gates and always succeeds, so a bare temp dir
    # is enough to exercise the full payload (gates inventory + workflow).
    rc = sm.main(["status", "--json", "--project-root", str(tmp_path)])
    assert rc == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["command"] == "status"
    assert envelope["status"] == "info"
    assert envelope["exit_code"] == 0
    assert "gates" in envelope["data"]

    data_schema = load_data_schema("status")
    assert data_schema is not None
    composed = _compose_output_schema("status", data_schema)

    jsonschema = pytest.importorskip("jsonschema")
    errors = list(jsonschema.Draft202012Validator(composed).iter_errors(envelope))
    assert not errors, [e.message for e in errors]


def test_status_describe_emits_output_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sm.main(["status", "--describe"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["$id"].endswith("/v3/output/status.json")
    _check_schema(out)


def test_captain_refused_output_conforms_to_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A bare summons with no justification is refused — non-interactive,
    # fast, and drives the `unresolved` branch of the data oneOf.
    rc = sm.main(["wake-angry-drunk-captain", "--json"])
    assert rc == 2
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["command"] == "wake-angry-drunk-captain"
    assert envelope["status"] == "error"
    assert envelope["data"]["outcome"] == "refused"

    data_schema = load_data_schema("wake-angry-drunk-captain")
    assert data_schema is not None
    composed = _compose_output_schema("wake-angry-drunk-captain", data_schema)

    jsonschema = pytest.importorskip("jsonschema")
    errors = list(jsonschema.Draft202012Validator(composed).iter_errors(envelope))
    assert not errors, [e.message for e in errors]


def test_captain_summons_output_conforms_to_schema(
    tmp_path: "object",
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A valid summons halts and hands the agent the relay payload — no stdin,
    # so it drives straight through sm.main with full justification.
    rc = sm.main(
        [
            "wake-angry-drunk-captain",
            "--objective",
            "ship it",
            "--verbs-tried",
            "sm swab — green",
            "--why-stuck",
            "nothing left to automate",
            "--decision",
            "merge or hold?",
            "--option",
            "merge",
            "--option",
            "hold",
            "--project-root",
            str(tmp_path),
            "--json",
        ]
    )
    assert rc == 1
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["command"] == "wake-angry-drunk-captain"
    assert envelope["status"] == "info"
    assert envelope["data"]["outcome"] == "summoned"
    assert envelope["data"]["turn_over"] is True
    assert envelope["data"]["relay_to_human"]

    data_schema = load_data_schema("wake-angry-drunk-captain")
    assert data_schema is not None
    composed = _compose_output_schema("wake-angry-drunk-captain", data_schema)

    jsonschema = pytest.importorskip("jsonschema")
    errors = list(jsonschema.Draft202012Validator(composed).iter_errors(envelope))
    assert not errors, [e.message for e in errors]


def test_captain_describe_emits_output_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sm.main(["wake-angry-drunk-captain", "--describe"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["$id"].endswith("/v3/output/wake-angry-drunk-captain.json")
    _check_schema(out)


def test_barnacle_output_conforms_to_schema(
    tmp_path: "object",
    capsys: pytest.CaptureFixture[str],
) -> None:
    # --dry-run never touches the network: it renders the issue body and
    # emits the envelope without filing anything upstream.
    rc = sm.main(
        [
            "barnacle",
            "file",
            "--dry-run",
            "--json",
            "--command",
            "sm swab",
            "--expected",
            "gates pass",
            "--actual",
            "lint crashed",
            "--project-root",
            str(tmp_path),
        ]
    )
    assert rc == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["command"] == "barnacle"
    assert envelope["status"] == "ok"
    assert "body" in envelope["data"]

    data_schema = load_data_schema("barnacle")
    assert data_schema is not None
    composed = _compose_output_schema("barnacle", data_schema)

    jsonschema = pytest.importorskip("jsonschema")
    errors = list(jsonschema.Draft202012Validator(composed).iter_errors(envelope))
    assert not errors, [e.message for e in errors]


def test_barnacle_describe_emits_output_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sm.main(["barnacle", "--describe"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["$id"].endswith("/v3/output/barnacle.json")
    _check_schema(out)


def test_buff_output_conforms_to_schema(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: "object",
) -> None:
    # Drive `sm buff inspect` with the network mocked out (mirrors the buff
    # inspect unit tests) so the envelope is produced from a real payload.
    from unittest.mock import Mock

    from slopmop.cli import buff as buff_mod
    from slopmop.cli import scan_triage as triage
    from slopmop.core.result import CheckStatus
    from tests.conftest import make_feedback_result, patch_buff_pr_resolution

    args = argparse.Namespace(
        json_output=True,
        repo=None,
        run_id=None,
        pr_number=84,
        workflow=triage.WORKFLOW_NAME,
        artifact=triage.ARTIFACT_NAME,
        output_file=str(tmp_path / "buff.json"),  # type: ignore[operator]
    )
    payload = {
        "schema": "slopmop/ci-triage/v1",
        "source": "code-scanning",
        "run_id": 123,
        "pr_number": 84,
        "artifact_json": "/tmp/scan.json",
        "summary": {"failed": 0, "errors": 0, "warned": 0, "all_passed": True},
        "actionable": [],
        "hard_failures": [],
        "lowest_coverage": [],
        "next_steps": ["Run full validation locally: sm scour"],
    }
    monkeypatch.setattr(buff_mod, "run_inspect_scan", Mock(return_value=(0, payload)))
    monkeypatch.setattr(buff_mod, "_project_root_from_cwd", Mock(return_value="/repo"))
    patch_buff_pr_resolution(monkeypatch, 84)
    monkeypatch.setattr(
        buff_mod,
        "_run_pr_feedback_gate",
        Mock(return_value=make_feedback_result(CheckStatus.PASSED)),
    )

    assert buff_mod.cmd_buff(args) == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["command"] == "buff"
    assert envelope["status"] == "ok"

    data_schema = load_data_schema("buff")
    assert data_schema is not None
    composed = _compose_output_schema("buff", data_schema)

    jsonschema = pytest.importorskip("jsonschema")
    errors = list(jsonschema.Draft202012Validator(composed).iter_errors(envelope))
    assert not errors, [e.message for e in errors]


def test_buff_status_output_conforms_to_schema(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # `sm buff status --json` emits the status branch of the buff data
    # oneOf, a different shape from the inspect/triage payload above. Drive
    # it with the network mocked so a real envelope is produced.
    from unittest.mock import Mock

    from slopmop.cli import _buff_status as status_mod
    from slopmop.core.result import CheckStatus
    from tests.conftest import make_feedback_result

    monkeypatch.setattr(
        status_mod, "_project_root_from_cwd", Mock(return_value="/repo")
    )
    monkeypatch.setattr(status_mod, "_get_repo_slug", Mock(return_value="o/r"))
    monkeypatch.setattr(
        status_mod,
        "resolve_pr_number_with_source",
        Mock(return_value=(84, "explicit")),
    )
    monkeypatch.setattr(status_mod, "_fire_buff_hook", Mock())
    monkeypatch.setattr(
        status_mod,
        "_fetch_checks",
        Mock(return_value=([{"name": "CI", "bucket": "pass"}], None)),
    )
    monkeypatch.setattr(
        status_mod,
        "_run_pr_feedback_gate",
        Mock(return_value=make_feedback_result(CheckStatus.PASSED)),
    )

    assert status_mod.cmd_buff_status(84, False, 30, json_output=True) == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["command"] == "buff"
    assert envelope["data"]["overall_state"] == "clean"

    data_schema = load_data_schema("buff")
    assert data_schema is not None
    composed = _compose_output_schema("buff", data_schema)

    jsonschema = pytest.importorskip("jsonschema")
    errors = list(jsonschema.Draft202012Validator(composed).iter_errors(envelope))
    assert not errors, [e.message for e in errors]


def test_buff_describe_emits_output_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sm.main(["buff", "--describe"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["$id"].endswith("/v3/output/buff.json")
    _check_schema(out)


def test_refit_output_conforms_to_schema(
    tmp_path: "object",
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A fresh repo defaults to REMEDIATION, so `--iterate` with no persisted
    # plan emits the standalone `missing_plan` protocol (exit 1) without
    # touching git or the network.
    rc = sm.main(
        [
            "refit",
            "--iterate",
            "--json",
            "--project-root",
            str(tmp_path),  # type: ignore[arg-type]
        ]
    )
    assert rc == 1
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["command"] == "refit"
    # A non-zero exit must not be reported as INFO (which parsers treat as
    # non-blocking) — a blocked outcome is FAIL.
    assert envelope["status"] == "fail"
    assert envelope["exit_code"] == 1
    assert envelope["data"]["event"] == "missing_plan"

    data_schema = load_data_schema("refit")
    assert data_schema is not None
    composed = _compose_output_schema("refit", data_schema)

    jsonschema = pytest.importorskip("jsonschema")
    errors = list(jsonschema.Draft202012Validator(composed).iter_errors(envelope))
    assert not errors, [e.message for e in errors]


def test_refit_describe_emits_output_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sm.main(["refit", "--describe"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["$id"].endswith("/v3/output/refit.json")
    _check_schema(out)


def test_no_orphan_data_schemas() -> None:
    # Guard against a data schema shipping without its conformance entry.
    # Every packaged data schema should be exercised by a migrated verb
    # once Phase 3+ lands; until _MIGRATED_VERBS is populated this simply
    # documents the gap rather than failing the build.
    declared = set(available_data_schemas())
    migrated = set(_MIGRATED_VERBS)
    assert migrated <= declared
