"""Tests for the SARIF 2.1.0 reporter."""

from slopmop.core.result import CheckResult, CheckStatus, ExecutionSummary, Finding
from slopmop.reporting.sarif import (
    SARIF_SCHEMA_URI,
    SARIF_VERSION,
    TOOL_NAME,
    SarifReporter,
)


def _summary(*results: CheckResult) -> ExecutionSummary:
    return ExecutionSummary.from_results(list(results), 1.0)


class TestSarifEnvelope:
    """Top-level SARIF document structure."""

    def test_schema_and_version(self):
        doc = SarifReporter().build(_summary())
        assert doc["$schema"] == SARIF_SCHEMA_URI
        assert doc["version"] == SARIF_VERSION
        assert SARIF_VERSION == "2.1.0"

    def test_single_run(self):
        doc = SarifReporter().build(_summary())
        assert isinstance(doc["runs"], list)
        assert len(doc["runs"]) == 1

    def test_driver_metadata(self):
        doc = SarifReporter(version="1.2.3").build(_summary())
        driver = doc["runs"][0]["tool"]["driver"]
        assert driver["name"] == TOOL_NAME
        assert driver["version"] == "1.2.3"
        assert driver["informationUri"].startswith("https://")

    def test_to_json_is_compact(self):
        out = SarifReporter().to_json(_summary())
        assert "\n" not in out
        assert ": " not in out  # no space after colon


class TestRulesCatalog:
    """tool.driver.rules — one reportingDescriptor per gate."""

    def test_rule_per_gate_regardless_of_status(self):
        """Every gate that ran gets a rule, even if it passed."""
        doc = SarifReporter().build(
            _summary(
                CheckResult("a:passed", CheckStatus.PASSED, 1.0),
                CheckResult("b:failed", CheckStatus.FAILED, 1.0),
                CheckResult("c:skipped", CheckStatus.SKIPPED, 0.0),
            )
        )
        rule_ids = {r["id"] for r in doc["runs"][0]["tool"]["driver"]["rules"]}
        assert rule_ids == {"a:passed", "b:failed", "c:skipped"}

    def test_rule_default_configuration(self):
        doc = SarifReporter().build(
            _summary(CheckResult("test:gate", CheckStatus.PASSED, 1.0))
        )
        rule = doc["runs"][0]["tool"]["driver"]["rules"][0]
        assert rule["defaultConfiguration"] == {"level": "error"}

    def test_rule_category_from_check_result(self):
        """Category flows through even when gate isn't in registry."""
        doc = SarifReporter().build(
            _summary(CheckResult("x:y", CheckStatus.PASSED, 1.0, category="quality"))
        )
        rule = doc["runs"][0]["tool"]["driver"]["rules"][0]
        assert rule["properties"]["category"] == "quality"

    def test_no_duplicate_rules(self):
        """Same gate name twice → one rule."""
        # Realistically doesn't happen, but defence in depth
        doc = SarifReporter().build(
            _summary(
                CheckResult("dup", CheckStatus.PASSED, 1.0),
                CheckResult("dup", CheckStatus.FAILED, 1.0),
            )
        )
        rule_ids = [r["id"] for r in doc["runs"][0]["tool"]["driver"]["rules"]]
        assert rule_ids == ["dup"]


class TestResults:
    """results[] — one entry per Finding."""

    def test_all_passed_empty_results(self):
        doc = SarifReporter().build(_summary(CheckResult("a", CheckStatus.PASSED, 1.0)))
        assert doc["runs"][0]["results"] == []

    def test_one_result_per_finding(self):
        r = CheckResult(
            "test:gate",
            CheckStatus.FAILED,
            1.0,
            findings=[
                Finding("issue one", file="a.py", line=1),
                Finding("issue two", file="b.py", line=2),
                Finding("issue three", file="c.py", line=3),
            ],
        )
        doc = SarifReporter().build(_summary(r))
        assert len(doc["runs"][0]["results"]) == 3

    def test_status_to_level_mapping(self):
        """FAILED → error, WARNED → warning, ERROR → error."""
        doc = SarifReporter().build(
            _summary(
                CheckResult("a", CheckStatus.FAILED, 1.0, findings=[Finding("x")]),
                CheckResult("b", CheckStatus.WARNED, 1.0, findings=[Finding("y")]),
                CheckResult("c", CheckStatus.ERROR, 1.0, findings=[Finding("z")]),
            )
        )
        levels = [r["level"] for r in doc["runs"][0]["results"]]
        assert levels == ["error", "warning", "error"]

    def test_passed_and_skipped_emit_no_results(self):
        doc = SarifReporter().build(
            _summary(
                CheckResult("a", CheckStatus.PASSED, 1.0, findings=[Finding("x")]),
                CheckResult("b", CheckStatus.SKIPPED, 0.0, findings=[Finding("y")]),
                CheckResult("c", CheckStatus.NOT_APPLICABLE, 0.0),
            )
        )
        assert doc["runs"][0]["results"] == []

    def test_locationless_fallback_uses_error_text(self):
        """Gate FAILED with no findings → one locationless result."""
        r = CheckResult(
            "legacy:gate", CheckStatus.FAILED, 1.0, error="things went wrong"
        )
        doc = SarifReporter().build(_summary(r))
        results = doc["runs"][0]["results"]
        assert len(results) == 1
        assert results[0]["message"]["text"] == "things went wrong"
        assert "locations" not in results[0]

    def test_locationless_fallback_uses_output_when_no_error(self):
        r = CheckResult("legacy:gate", CheckStatus.FAILED, 1.0, output="some output")
        doc = SarifReporter().build(_summary(r))
        assert doc["runs"][0]["results"][0]["message"]["text"] == "some output"

    def test_locationless_fallback_never_empty_message(self):
        """SARIF requires non-empty message text."""
        r = CheckResult("x:y", CheckStatus.FAILED, 1.0, output="", error="")
        doc = SarifReporter().build(_summary(r))
        assert doc["runs"][0]["results"][0]["message"]["text"]


class TestPhysicalLocation:
    """locations[].physicalLocation — file URI and region."""

    def test_full_location(self):
        f = Finding("bad", file="src/foo.py", line=42, column=5)
        r = CheckResult("g", CheckStatus.FAILED, 1.0, findings=[f])
        doc = SarifReporter().build(_summary(r))
        loc = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uri"] == "src/foo.py"
        assert loc["region"]["startLine"] == 42
        assert loc["region"]["startColumn"] == 5

    def test_file_only_no_region(self):
        """File-level finding (no line) → artifactLocation without region."""
        f = Finding("bad", file="src/foo.py")
        r = CheckResult("g", CheckStatus.FAILED, 1.0, findings=[f])
        doc = SarifReporter().build(_summary(r))
        loc = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uri"] == "src/foo.py"
        assert "region" not in loc

    def test_no_file_no_locations(self):
        """Message-only finding → no locations key."""
        f = Finding("project-wide issue")
        r = CheckResult("g", CheckStatus.FAILED, 1.0, findings=[f])
        doc = SarifReporter().build(_summary(r))
        assert "locations" not in doc["runs"][0]["results"][0]

    def test_multi_line_region(self):
        f = Finding("block", file="x.py", line=10, end_line=20, column=1, end_column=80)
        r = CheckResult("g", CheckStatus.FAILED, 1.0, findings=[f])
        doc = SarifReporter().build(_summary(r))
        region = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
            "region"
        ]
        assert region == {
            "startLine": 10,
            "endLine": 20,
            "startColumn": 1,
            "endColumn": 80,
        }

    def test_sub_rule_in_properties(self):
        f = Finding("bad type", file="x.py", line=1, rule_id="type-arg")
        r = CheckResult("g", CheckStatus.FAILED, 1.0, findings=[f])
        doc = SarifReporter().build(_summary(r))
        assert doc["runs"][0]["results"][0]["properties"]["subRule"] == "type-arg"


class TestFingerprints:
    """partialFingerprints — stable across line shifts."""

    def test_present_on_every_result(self):
        f = Finding("x", file="a.py", line=1)
        r = CheckResult("g", CheckStatus.FAILED, 1.0, findings=[f])
        doc = SarifReporter().build(_summary(r))
        fp = doc["runs"][0]["results"][0]["partialFingerprints"]
        assert "slopmopFingerprint/v1" in fp
        assert len(fp["slopmopFingerprint/v1"]) == 32  # truncated sha256

    def test_same_inputs_same_fingerprint(self):
        f1 = Finding("same msg", file="a.py", line=10)
        f2 = Finding("same msg", file="a.py", line=10)
        fp1 = SarifReporter._fingerprint("rule", f1)
        fp2 = SarifReporter._fingerprint("rule", f2)
        assert fp1 == fp2

    def test_line_shift_does_not_change_fingerprint(self):
        """The whole point — same issue, moved 3 lines down, same alert."""
        f1 = Finding("function foo too complex", file="a.py", line=10)
        f2 = Finding("function foo too complex", file="a.py", line=13)
        assert SarifReporter._fingerprint("r", f1) == SarifReporter._fingerprint(
            "r", f2
        )

    def test_different_message_different_fingerprint(self):
        f1 = Finding("foo is bad", file="a.py", line=10)
        f2 = Finding("bar is bad", file="a.py", line=10)
        assert SarifReporter._fingerprint("r", f1) != SarifReporter._fingerprint(
            "r", f2
        )

    def test_different_file_different_fingerprint(self):
        f1 = Finding("same", file="a.py")
        f2 = Finding("same", file="b.py")
        assert SarifReporter._fingerprint("r", f1) != SarifReporter._fingerprint(
            "r", f2
        )

    def test_different_rule_different_fingerprint(self):
        f = Finding("same", file="a.py")
        assert SarifReporter._fingerprint("r1", f) != SarifReporter._fingerprint(
            "r2", f
        )
