"""Validate SARIF output against the official 2.1.0 JSON Schema.

The schema is vendored at ``tests/fixtures/sarif-2.1.0.schema.json``
(fetched from https://json.schemastore.org/sarif-2.1.0.json).  This is
a test-only validation — the runtime has no ``jsonschema`` dependency.
"""

import json
from pathlib import Path

import pytest

from slopmop.core.result import CheckResult, CheckStatus, ExecutionSummary, Finding
from slopmop.reporting.sarif import SarifReporter

jsonschema = pytest.importorskip("jsonschema")

_SCHEMA_PATH = Path(__file__).parent.parent / "fixtures" / "sarif-2.1.0.schema.json"


@pytest.fixture(scope="module")
def sarif_schema():
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate(doc, schema):
    jsonschema.validate(instance=doc, schema=schema)


class TestSarifSchemaValidity:
    """Every shape of output we produce must be schema-valid."""

    def test_empty_run(self, sarif_schema):
        doc = SarifReporter("0.6.0").build(ExecutionSummary.from_results([], 0.0))
        _validate(doc, sarif_schema)

    def test_all_passed(self, sarif_schema):
        doc = SarifReporter("0.6.0").build(
            ExecutionSummary.from_results(
                [
                    CheckResult("a:b", CheckStatus.PASSED, 1.0),
                    CheckResult("c:d", CheckStatus.PASSED, 0.5),
                ],
                1.5,
            )
        )
        _validate(doc, sarif_schema)

    def test_finding_with_full_location(self, sarif_schema):
        r = CheckResult(
            "laziness:sloppy-formatting.py",
            CheckStatus.FAILED,
            2.0,
            category="laziness",
            findings=[
                Finding(
                    message="line too long (105 > 100 characters)",
                    file="slopmop/checks/quality/complexity.py",
                    line=42,
                    column=101,
                    rule_id="E501",
                ),
            ],
        )
        doc = SarifReporter("0.6.0").build(ExecutionSummary.from_results([r], 2.0))
        _validate(doc, sarif_schema)

    def test_finding_file_only(self, sarif_schema):
        r = CheckResult(
            "myopia:config-debt",
            CheckStatus.WARNED,
            0.1,
            findings=[
                Finding(message="3 gates disabled", file=".sb_config.json"),
            ],
        )
        doc = SarifReporter("0.6.0").build(ExecutionSummary.from_results([r], 0.1))
        _validate(doc, sarif_schema)

    def test_locationless_fallback(self, sarif_schema):
        r = CheckResult(
            "custom:shell",
            CheckStatus.FAILED,
            1.0,
            error="exit code 1\nsomething broke",
        )
        doc = SarifReporter("0.6.0").build(ExecutionSummary.from_results([r], 1.0))
        _validate(doc, sarif_schema)

    def test_multi_line_region(self, sarif_schema):
        r = CheckResult(
            "quality:duplication",
            CheckStatus.FAILED,
            3.0,
            findings=[
                Finding(
                    message="duplicate block (15 lines)",
                    file="src/a.py",
                    line=100,
                    end_line=115,
                ),
            ],
        )
        doc = SarifReporter("0.6.0").build(ExecutionSummary.from_results([r], 3.0))
        _validate(doc, sarif_schema)

    def test_mixed_statuses(self, sarif_schema):
        """The realistic case — everything at once."""
        results = [
            CheckResult("a:pass", CheckStatus.PASSED, 1.0, category="py"),
            CheckResult(
                "b:fail",
                CheckStatus.FAILED,
                2.0,
                category="quality",
                findings=[
                    Finding("issue 1", file="x.py", line=1),
                    Finding("issue 2", file="y.py", line=50, column=3),
                ],
            ),
            CheckResult(
                "c:warn",
                CheckStatus.WARNED,
                0.5,
                findings=[Finding("heads up", file="z.py")],
            ),
            CheckResult("d:error", CheckStatus.ERROR, 0.1, error="crashed"),
            CheckResult("e:skip", CheckStatus.SKIPPED, 0.0),
            CheckResult("f:na", CheckStatus.NOT_APPLICABLE, 0.0),
        ]
        doc = SarifReporter("0.6.0").build(ExecutionSummary.from_results(results, 3.6))
        _validate(doc, sarif_schema)
        # Sanity: 4 results (2 findings + 1 warn + 1 error fallback)
        assert len(doc["runs"][0]["results"]) == 4
