"""Tests for SARIF 2.1.0 output.

SARIF is a write-once-read-elsewhere format: slopmop writes it, GitHub
Code Scanning reads it, and we never parse it back.  That asymmetry
means our tests need to check for the failure modes GitHub hits, not
the ones we'd hit — schema validity, exact key names, 1-based columns,
and the URI format that lets GitHub match results to repo files.

The schema validation test at the bottom is the safety net: it catches
whole classes of mistakes (wrong nesting, wrong type, missing required
field) that targeted asserts would miss.  If you're adding a new field
to the SARIF emitter, run that test first — it'll tell you if you've
broken the shape before you waste time debugging GitHub's silent drops.
"""

import json
from pathlib import Path
from typing import Any, Optional

import pytest

from slopmop.core.result import (
    CheckResult,
    CheckStatus,
    ExecutionSummary,
    Finding,
    FindingLevel,
)
from slopmop.reporting.sarif import (
    SARIF_SCHEMA_URI,
    SARIF_VERSION,
    SarifReporter,
)

# Path to vendored schema — see tests/fixtures/README if you need to
# regenerate.  We vendor it so tests don't hit the network and so the
# schema version we validate against is pinned (schemastore could
# theoretically change under us).
_SCHEMA_PATH = Path(__file__).parent.parent / "fixtures" / "sarif-2.1.0-schema.json"


def _make_summary(*results: CheckResult) -> ExecutionSummary:
    """Build an ExecutionSummary from results with the duration faked."""
    return ExecutionSummary.from_results(list(results), duration=1.0)


def _emit(summary: ExecutionSummary, root: str = ".") -> Any:
    """Convenience: construct a reporter and emit in one call.

    Returns Any rather than dict[str, object] because test code walks
    deeply nested JSON and pyright can't see through ["key"]["key"]["key"]
    chains when every level is typed as object.  The SARIF schema
    validator is the real type checker for this data — that's what
    TestSchemaValidation is for.
    """
    return SarifReporter(root).generate(summary)


class TestFindingModel:
    """The Finding dataclass is the contract between gates and the
    SARIF reporter.  These tests pin the serialisation shape so a
    change to Finding.to_dict() shows up here before it breaks the
    --json output schema downstream.
    """

    def test_minimal_finding_has_only_required_keys(self) -> None:
        """A Finding with just a message serialises to exactly two keys.
        The omit-None convention here matches CheckResult.to_dict() —
        LLM consumers of --json output pay per token, so we don't ship
        "file": null six times per finding.
        """
        f = Finding(message="problem")
        d = f.to_dict()
        assert d == {"message": "problem", "level": "error"}

    def test_full_finding_roundtrip(self) -> None:
        """Every field present → every key present.  Checks we didn't
        forget to wire a field into to_dict().
        """
        f = Finding(
            message="m",
            level=FindingLevel.WARNING,
            file="src/x.py",
            line=10,
            column=5,
            end_line=12,
            end_column=8,
            rule_id="E501",
        )
        d = f.to_dict()
        assert d["level"] == "warning"
        assert d["file"] == "src/x.py"
        assert d["line"] == 10
        assert d["column"] == 5
        assert d["end_line"] == 12
        assert d["end_column"] == 8
        assert d["rule_id"] == "E501"

    def test_finding_is_frozen(self) -> None:
        """Findings are value objects — once a gate emits one it's
        immutable.  Mutation would break fingerprint caching in the
        reporter (we'd hash stale data).
        """
        f = Finding(message="x")
        with pytest.raises(AttributeError):
            f.message = "y"  # type: ignore[misc]

    def test_findings_flow_through_check_result_to_dict(self) -> None:
        """CheckResult.to_dict() includes findings when present, omits
        when empty.  This is how findings reach --json output — the
        SARIF path reads CheckResult.findings directly, but JSON
        consumers get them via to_dict().
        """
        r_with = CheckResult(
            name="g",
            status=CheckStatus.FAILED,
            duration=0.1,
            findings=[Finding(message="a"), Finding(message="b")],
        )
        d: Any = r_with.to_dict()
        assert len(d["findings"]) == 2
        assert d["findings"][0]["message"] == "a"

        r_without = CheckResult(name="g", status=CheckStatus.FAILED, duration=0.1)
        d2: Any = r_without.to_dict()
        assert "findings" not in d2


class TestSarifStructure:
    """Shape tests for the top-level SARIF document.  GitHub rejects
    uploads that get the envelope wrong before it even looks at
    results, so these failures are the cheap ones to catch early.
    """

    def test_empty_run_produces_valid_envelope(self) -> None:
        """No findings → valid SARIF with empty results.  This is the
        happy path: all gates passed.  GitHub accepts this and shows
        a green Security tab.
        """
        doc = _emit(_make_summary())
        assert doc["$schema"] == SARIF_SCHEMA_URI
        assert doc["version"] == SARIF_VERSION
        run = doc["runs"][0]
        assert run["results"] == []
        assert run["tool"]["driver"]["name"] == "slopmop"

    def test_passed_gate_emits_nothing(self) -> None:
        """Passing gates don't contribute results OR rules.  A rule
        with no results is noise in GitHub's filter dropdown.
        """
        passed = CheckResult(name="ok:gate", status=CheckStatus.PASSED, duration=0.1)
        doc = _emit(_make_summary(passed))
        assert doc["runs"][0]["results"] == []
        assert doc["runs"][0]["tool"]["driver"]["rules"] == []

    def test_error_status_emits_repo_root_result(self) -> None:
        """ERROR means infrastructure failure (tool missing, timeout).
        These still deserve visibility in the Security tab — they indicate
        a gate that can't run, which is a CI health issue.  The result is
        anchored at the repo root since there's no file to point at.
        """
        errored = CheckResult(
            name="broken:gate",
            status=CheckStatus.ERROR,
            duration=0.1,
            error="tool not found",
        )
        doc = _emit(_make_summary(errored))
        results = doc["runs"][0]["results"]
        assert len(results) == 1
        result = results[0]
        assert result["ruleId"] == "broken:gate"
        assert result["level"] == "error"
        assert result["message"]["text"] == "tool not found"
        # Locationless fallback anchors at repo root
        loc = result["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uri"] == "."

    def test_failed_gate_with_findings_emits_one_result_per_finding(
        self,
    ) -> None:
        r = CheckResult(
            name="lint:gate",
            status=CheckStatus.FAILED,
            duration=0.1,
            findings=[
                Finding(message="a", file="x.py", line=1),
                Finding(message="b", file="x.py", line=2),
                Finding(message="c", file="y.py", line=1),
            ],
        )
        doc = _emit(_make_summary(r))
        assert len(doc["runs"][0]["results"]) == 3


class TestSarifResultShape:
    """The result object is where GitHub's inline PR annotations come
    from.  Get the nesting wrong and GitHub silently drops the result —
    no error, no annotation, just nothing.  These tests pin the exact
    key names and nesting depth.
    """

    def _single_result(self, finding: Finding) -> Any:
        """Emit one result and return it unwrapped."""
        r = CheckResult(
            name="g", status=CheckStatus.FAILED, duration=0.1, findings=[finding]
        )
        doc = _emit(_make_summary(r))
        return doc["runs"][0]["results"][0]

    def test_physical_location_nesting(self) -> None:
        """locations[0].physicalLocation.artifactLocation.uri is the
        exact path GitHub reads.  Four levels of nesting, all required.
        This test would catch a typo like `artifactLocations` (plural)
        that schema validation also catches but with a less readable
        error.
        """
        result = self._single_result(Finding(message="m", file="src/app.py", line=42))
        loc = result["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uri"] == "src/app.py"
        assert loc["region"]["startLine"] == 42

    def test_region_only_includes_present_fields(self) -> None:
        """Don't emit startColumn: null — SARIF schema forbids null
        where it expects an integer.  Omit the key instead.
        """
        result = self._single_result(Finding(message="m", file="x.py", line=5))
        region = result["locations"][0]["physicalLocation"]["region"]
        assert region == {"startLine": 5}
        # column/endLine/endColumn absent, not null

    def test_full_region(self) -> None:
        result = self._single_result(
            Finding(
                message="m",
                file="x.py",
                line=5,
                column=3,
                end_line=7,
                end_column=10,
            )
        )
        region = result["locations"][0]["physicalLocation"]["region"]
        assert region == {
            "startLine": 5,
            "startColumn": 3,
            "endLine": 7,
            "endColumn": 10,
        }

    def test_locationless_finding_dropped(self) -> None:
        """A Finding with no file produces NO SARIF result at all.

        The original design emitted a location-less result here,
        reasoning that aggregate findings (coverage %, test count)
        have no meaningful file anchor and the SARIF schema permits
        ``locations`` to be absent.  True — but GitHub's
        ``upload-sarif`` action is stricter than the schema.  It
        rejects with ``locationFromSarifResult: expected at least one
        location`` and FAILS THE WORKFLOW.  We found out in CI.

        So the reporter now anchors file-less findings at the repo root
        (".").  The alert lands in the Security tab without an inline
        annotation, which is appropriate for aggregate/config-level issues.
        """
        r = CheckResult(
            name="cov:gate",
            status=CheckStatus.FAILED,
            duration=0.1,
            findings=[Finding(message="coverage too low")],  # no file=
        )
        doc = _emit(_make_summary(r))
        results = doc["runs"][0]["results"]
        assert len(results) == 1
        result = results[0]
        assert result["message"]["text"] == "coverage too low"
        loc = result["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uri"] == "."

    def test_mixed_findings_all_survive(self) -> None:
        """A gate emitting three findings, one without a file — all
        three reach SARIF.  The file-less finding gets anchored at
        the repo root (\".\").
        """
        r = CheckResult(
            name="g",
            status=CheckStatus.FAILED,
            duration=0.1,
            findings=[
                Finding(message="real problem A", file="a.py", line=1),
                Finding(message="aggregate: 2 issues"),  # repo root
                Finding(message="real problem B", file="b.py", line=5),
            ],
        )
        doc = _emit(_make_summary(r))
        results = doc["runs"][0]["results"]
        assert len(results) == 3
        assert {r["message"]["text"] for r in results} == {
            "real problem A",
            "aggregate: 2 issues",
            "real problem B",
        }

    def test_message_is_nested_under_text(self) -> None:
        """result.message is an object with a .text key, not a bare
        string.  Easy to get wrong; GitHub silently drops results
        where message is a string.
        """
        result = self._single_result(Finding(message="hello", file="x.py"))
        assert result["message"] == {"text": "hello"}


class TestRuleIdComposition:
    """ruleId links results to rules.  We compose it from gate name +
    sub-rule so one gate wrapping many tool rules (flake8's E501, W291,
    F401...) produces distinct rule entries that GitHub can filter on
    separately.
    """

    def test_sub_rule_appended_with_slash(self) -> None:
        """gate/sub-rule — slash is the SARIF hierarchical convention.
        GitHub's filter UI understands the prefix so you can filter
        by gate OR by specific tool rule.
        """
        r = CheckResult(
            name="lint:py",
            status=CheckStatus.FAILED,
            duration=0.1,
            findings=[Finding(message="m", file="x.py", rule_id="E501")],
        )
        doc = _emit(_make_summary(r))
        assert doc["runs"][0]["results"][0]["ruleId"] == "lint:py/E501"
        assert doc["runs"][0]["tool"]["driver"]["rules"][0]["id"] == "lint:py/E501"

    def test_no_sub_rule_uses_gate_name_alone(self) -> None:
        r = CheckResult(
            name="cov:py",
            status=CheckStatus.FAILED,
            duration=0.1,
            findings=[Finding(message="low", file="x.py")],
        )
        doc = _emit(_make_summary(r))
        assert doc["runs"][0]["results"][0]["ruleId"] == "cov:py"

    def test_rules_deduplicated_across_findings(self) -> None:
        """Ten F401 findings → one F401 rule entry.  GitHub's rule
        list is a filter dropdown; duplicates would be noise.
        """
        r = CheckResult(
            name="lint:py",
            status=CheckStatus.FAILED,
            duration=0.1,
            findings=[
                Finding(message=f"unused {i}", file="x.py", rule_id="F401")
                for i in range(10)
            ],
        )
        doc = _emit(_make_summary(r))
        assert len(doc["runs"][0]["results"]) == 10
        assert len(doc["runs"][0]["tool"]["driver"]["rules"]) == 1

    def test_distinct_sub_rules_produce_distinct_rule_entries(self) -> None:
        r = CheckResult(
            name="lint:py",
            status=CheckStatus.FAILED,
            duration=0.1,
            findings=[
                Finding(message="a", file="x.py", rule_id="E501"),
                Finding(message="b", file="x.py", rule_id="W291"),
                Finding(message="c", file="y.py", rule_id="E501"),
            ],
        )
        doc = _emit(_make_summary(r))
        rule_ids = {r["id"] for r in doc["runs"][0]["tool"]["driver"]["rules"]}
        assert rule_ids == {"lint:py/E501", "lint:py/W291"}


class TestFindingsRail:
    """``_create_result`` warns when you FAIL/WARN without findings.

    Forgetting ``findings=`` is SILENT at the SARIF layer — the
    reporter drops file-less findings (GitHub's upload-sarif rejects
    them), and no-findings-at-all just means the gate contributes
    zero results.  No crash, no error, the gate just... isn't there.
    That's good for end users (an upgrade shouldn't break their CI
    because one gate wasn't migrated) but bad for gate authors —
    your gate fails, the PR shows no annotation, and you'd never
    know why without reading the SARIF JSON by hand.

    The rail is a ``UserWarning`` at result-construction time.  It
    surfaces during ``pytest`` (warnings-as-errors in strict mode)
    and during ``sm swab`` development (warning printed to stderr).
    Once you pass ``findings=[...]`` — even a single location-less
    ``Finding(message=...)`` for aggregate gates — it goes quiet.

    Tests use a real gate instance because ``BaseCheck`` is abstract
    and the rail lives on ``self._create_result``, not a module
    function.  Any concrete gate works; ``LocLockCheck`` is cheap
    to construct (no external tools, no file I/O in ``__init__``).
    """

    @pytest.fixture
    def gate(self) -> Any:
        """A concrete BaseCheck just for calling _create_result on."""
        from slopmop.checks.quality.loc_lock import LocLockCheck

        return LocLockCheck(config={})

    @pytest.mark.parametrize(
        ("status", "findings", "should_warn"),
        [
            (CheckStatus.FAILED, None, True),
            (CheckStatus.WARNED, None, True),
            (CheckStatus.FAILED, [Finding(message="x")], False),
            (CheckStatus.WARNED, [Finding(message="x")], False),
            (CheckStatus.PASSED, None, False),
            (CheckStatus.SKIPPED, None, False),
            (CheckStatus.ERROR, None, False),
            (CheckStatus.NOT_APPLICABLE, None, False),
        ],
        ids=[
            "failed-bare",
            "warned-bare",
            "failed-with-findings",
            "warned-with-findings",
            "passed",
            "skipped",
            "error",
            "n/a",
        ],
    )
    def test_rail_fires_only_on_bare_fail_or_warn(
        self,
        gate: Any,
        status: CheckStatus,
        findings: Any,
        should_warn: bool,
        recwarn: Any,
    ) -> None:
        gate._create_result(status=status, duration=0.0, findings=findings)
        got = [w for w in recwarn if issubclass(w.category, UserWarning)]
        if should_warn:
            assert len(got) == 1, (
                f"{status.value}/findings={findings!r} should warn, "
                f"got {len(got)} UserWarning(s)"
            )
            assert "findings" in str(got[0].message)
            assert "_create_result" in str(got[0].message)
        else:
            assert not got, (
                f"{status.value}/findings={findings!r} should NOT warn, "
                f"got: {[str(w.message) for w in got]}"
            )

    def test_warning_names_the_gate(self, gate: Any, recwarn: Any) -> None:
        """The warning should say WHICH gate forgot — you might have
        20 gates running in parallel and a bare 'missing findings'
        warning is useless for finding the offender."""
        gate._create_result(status=CheckStatus.FAILED, duration=0.0)
        warns = [w for w in recwarn if issubclass(w.category, UserWarning)]
        assert warns, "rail did not fire"
        # LocLockCheck's full_name is myopia:code-sprawl
        assert "myopia:code-sprawl" in str(warns[0].message)

    def test_rail_points_at_caller(self, gate: Any, recwarn: Any) -> None:
        """``stacklevel=2`` means the warning's filename/lineno point
        at the gate's ``run()`` method, not at ``base.py``.  Without
        this, every warning says 'base.py:570' which is useless."""
        gate._create_result(status=CheckStatus.FAILED, duration=0.0)
        warns = [w for w in recwarn if issubclass(w.category, UserWarning)]
        assert warns, "rail did not fire"
        # With stacklevel=2, the warning is attributed to THIS file,
        # not to base.py — we're the caller of _create_result here.
        # A gate calling it would be attributed to the gate file.
        assert "base.py" not in warns[0].filename, (
            f"warning attributed to {warns[0].filename!r} — stacklevel "
            f"is wrong, should point at the caller not _create_result"
        )


class TestUnmigratedGate:
    """Gates that haven't migrated to structured findings yet still
    FAIL — they just don't have Finding objects.  The reporter now
    emits a single result anchored at the repo root (".") using
    the gate's error or output text as the message.

    This ensures every failing gate gets visibility in GitHub's
    Security tab, even without file-level annotations.  The sentinel
    location satisfies upload-sarif's requirement that every result
    must have at least one location.

    The ``_create_result`` UserWarning rail (tested in
    ``TestFindingsRail`` below) is what catches this at development
    time — fail without ``findings=`` and pytest's warnings-as-errors
    lights up.
    """

    def test_failed_gate_without_findings_emits_repo_root(self) -> None:
        r = CheckResult(
            name="legacy:gate",
            status=CheckStatus.FAILED,
            duration=0.1,
            error="something broke",
        )
        doc = _emit(_make_summary(r))
        results = doc["runs"][0]["results"]
        assert len(results) == 1
        result = results[0]
        assert result["ruleId"] == "legacy:gate"
        assert result["message"]["text"] == "something broke"
        loc = result["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uri"] == "."

    def test_warned_gate_without_findings_emits_repo_root(self) -> None:
        """Same fallback for WARNED.  The sentinel location satisfies
        GitHub's requirement."""
        r = CheckResult(
            name="soft:gate",
            status=CheckStatus.WARNED,
            duration=0.1,
            error="mild concern",
        )
        doc = _emit(_make_summary(r))
        results = doc["runs"][0]["results"]
        assert len(results) == 1
        assert results[0]["message"]["text"] == "mild concern"
        loc = results[0]["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uri"] == "."

    def test_every_emitted_result_has_locations(self) -> None:
        """The invariant GitHub enforces: if it's in results[], it has
        locations[].  All findings — with or without file — must carry
        at least one location (file-less ones anchor at repo root).
        """
        mixed = CheckResult(
            name="g",
            status=CheckStatus.FAILED,
            duration=0.1,
            findings=[
                Finding(message="a", file="f.py", line=1),
                Finding(message="b"),  # no file — anchored at "."
                Finding(message="c", file="g.py"),  # file, no line — still OK
            ],
        )
        doc = _emit(_make_summary(mixed))
        assert len(doc["runs"][0]["results"]) == 3
        for result in doc["runs"][0]["results"]:
            assert "locations" in result, (
                f"Result without locations[] would be rejected by "
                f"GitHub's upload-sarif:\n{result}"
            )
            assert len(result["locations"]) >= 1


class TestUriNormalisation:
    """GitHub matches artifactLocation.uri against repo file paths.
    Get the format wrong and the annotation has no file link — the
    result shows in the Security tab but not inline on the PR.
    Relative POSIX paths are the target; everything else gets coerced.
    """

    def test_relative_path_passthrough(self) -> None:
        r = CheckResult(
            name="g",
            status=CheckStatus.FAILED,
            duration=0.1,
            findings=[Finding(message="m", file="src/app.py", line=1)],
        )
        doc = _emit(_make_summary(r))
        uri = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
            "artifactLocation"
        ]["uri"]
        assert uri == "src/app.py"

    def test_absolute_path_inside_root_made_relative(self, tmp_path: Path) -> None:
        """Gates sometimes get absolute paths from tool output (pyright,
        mypy with certain configs).  We strip the root prefix so GitHub
        can match it.  Without this, the URI would be
        file:///home/runner/work/... which matches nothing.
        """
        src = tmp_path / "pkg" / "mod.py"
        src.parent.mkdir()
        src.write_text("pass\n")

        r = CheckResult(
            name="g",
            status=CheckStatus.FAILED,
            duration=0.1,
            findings=[Finding(message="m", file=str(src), line=1)],
        )
        doc = _emit(_make_summary(r), root=str(tmp_path))
        uri = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
            "artifactLocation"
        ]["uri"]
        assert uri == "pkg/mod.py"

    def test_path_with_space_is_percent_encoded(self) -> None:
        """SARIF URIs are RFC 3986 — spaces must be %20.  GitHub's
        parser is strict about this; unencoded spaces cause the whole
        URI to be treated as invalid.
        """
        r = CheckResult(
            name="g",
            status=CheckStatus.FAILED,
            duration=0.1,
            findings=[Finding(message="m", file="my file.py", line=1)],
        )
        doc = _emit(_make_summary(r))
        uri = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
            "artifactLocation"
        ]["uri"]
        assert uri == "my%20file.py"


class TestFingerprints:
    """partialFingerprints.primaryLocationLineHash is how GitHub
    deduplicates alerts across commits.  Without it, every push looks
    like a fresh set of problems and the alert count climbs forever.

    Our hash deliberately excludes the line NUMBER (it drifts when
    unrelated code is added above) and includes the line CONTENT
    (when that changes, the finding genuinely changed).
    """

    @pytest.fixture
    def project(self, tmp_path: Path) -> Path:
        """A tiny project with known file contents so fingerprint
        hashes are deterministic.
        """
        (tmp_path / "a.py").write_text(
            "import os\n"  # line 1
            "import sys\n"  # line 2
            "x = 1\n"  # line 3
            "x = 1\n"  # line 4 — duplicate of line 3
        )
        return tmp_path

    def _fingerprint_of(self, doc: Any, idx: int = 0) -> Optional[str]:
        results = doc["runs"][0]["results"]
        return (
            results[idx].get("partialFingerprints", {}).get("primaryLocationLineHash")
        )

    def test_fingerprint_present_for_located_finding(self, project: Path) -> None:
        r = CheckResult(
            name="g",
            status=CheckStatus.FAILED,
            duration=0.1,
            findings=[Finding(message="m", file="a.py", line=1)],
        )
        doc = _emit(_make_summary(r), root=str(project))
        fp = self._fingerprint_of(doc)
        assert fp is not None
        # Format: hexdigest:occurrence
        digest, _, occ = fp.partition(":")
        assert len(digest) == 16
        assert occ == "1"

    def test_fingerprint_absent_without_line_number(self, project: Path) -> None:
        """File but no line → nothing to hash.  The fingerprint is a
        hash of the LINE CONTENT at ``finding.line`` — without a line
        there's no content to read.  Omit the fingerprint entirely;
        upload-sarif will skip it too (it also can't hash nothing).

        (File-less findings would also lack a fingerprint, but those
        don't reach ``_build_result`` at all — the ``_collect`` filter
        drops them.  File-without-line is the surviving case.)
        """
        r = CheckResult(
            name="g",
            status=CheckStatus.FAILED,
            duration=0.1,
            findings=[Finding(message="whole-file issue", file="a.py")],
        )
        doc = _emit(_make_summary(r), root=str(project))
        result = doc["runs"][0]["results"][0]
        assert "partialFingerprints" not in result
        # But it DOES get a location — GitHub accepts artifactLocation
        # without a region.  The finding anchors to the file, just not
        # to a specific line.
        assert result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]

    def test_fingerprint_stable_across_line_shift(self, project: Path) -> None:
        """The core property: same content at a different line number
        produces the same hash.  This is what makes dedup work when
        someone adds an import at the top and shifts everything down.
        """
        f_line1 = Finding(message="m", file="a.py", line=1)  # "import os"
        f_line2 = Finding(message="m", file="a.py", line=2)  # "import sys"

        # Rewrite the file with a blank line prepended — what was
        # line 1 is now line 2.
        (project / "a.py").write_text(
            "\n"
            "import os\n"  # now line 2
            "import sys\n"  # now line 3
        )
        f_shifted = Finding(message="m", file="a.py", line=2)  # "import os" again

        # Before the shift, line 1 and line 2 have different content
        # → different hashes.
        r_before = CheckResult(
            name="g",
            status=CheckStatus.FAILED,
            duration=0.1,
            findings=[f_line1, f_line2],
        )
        # Restore original content first — the fixture above already
        # overwrote it demonstrating the shift, but we need the pre-shift
        # state for the "before" hash.  Need fresh reporters per state:
        # they cache file contents on first read.
        (project / "a.py").write_text("import os\nimport sys\nx = 1\nx = 1\n")
        doc_before: Any = SarifReporter(str(project)).generate(_make_summary(r_before))
        fp_os_before = self._fingerprint_of(doc_before, 0)
        fp_sys_before = self._fingerprint_of(doc_before, 1)
        assert fp_os_before != fp_sys_before  # different content

        # After the shift: "import os" at line 2 should hash the same
        # as "import os" at line 1 did before.
        (project / "a.py").write_text("\nimport os\nimport sys\n")
        r_after = CheckResult(
            name="g",
            status=CheckStatus.FAILED,
            duration=0.1,
            findings=[f_shifted],
        )
        doc_after: Any = SarifReporter(str(project)).generate(_make_summary(r_after))
        fp_os_after = self._fingerprint_of(doc_after, 0)
        assert fp_os_after == fp_os_before

    def test_identical_lines_get_distinct_occurrence_suffixes(
        self, project: Path
    ) -> None:
        """Two identical lines in the same file hash identically — the
        :N suffix disambiguates.  Without it GitHub would collapse
        them into one alert and lose the second location.

        Lines 3 and 4 of the fixture are both "x = 1".
        """
        r = CheckResult(
            name="g",
            status=CheckStatus.FAILED,
            duration=0.1,
            findings=[
                Finding(message="a", file="a.py", line=3),
                Finding(message="b", file="a.py", line=4),
            ],
        )
        doc = _emit(_make_summary(r), root=str(project))
        fp0 = self._fingerprint_of(doc, 0)
        fp1 = self._fingerprint_of(doc, 1)
        assert fp0 is not None and fp1 is not None
        # Same digest, different occurrence
        assert fp0.rsplit(":", 1)[0] == fp1.rsplit(":", 1)[0]
        assert fp0.endswith(":1")
        assert fp1.endswith(":2")

    def test_missing_file_skips_fingerprint_gracefully(self, project: Path) -> None:
        """If the file was deleted between check-run and SARIF-emit
        (rare but possible in watch-mode workflows), skip the
        fingerprint rather than crash.  The result is still valid
        SARIF; upload-sarif will compute its own fingerprint or skip.
        """
        r = CheckResult(
            name="g",
            status=CheckStatus.FAILED,
            duration=0.1,
            findings=[Finding(message="m", file="deleted.py", line=5)],
        )
        doc = _emit(_make_summary(r), root=str(project))
        # Result exists, fingerprint doesn't
        result = doc["runs"][0]["results"][0]
        assert "locations" in result
        assert "partialFingerprints" not in result


class TestSchemaValidation:
    """Validate against the actual SARIF 2.1.0 JSON schema.  This is
    the backstop — it catches structural mistakes that the targeted
    tests above don't cover.  If this test passes but GitHub still
    rejects the upload, the problem is in GitHub's additional
    constraints (URI format, field length limits) not the schema.
    """

    @pytest.fixture(scope="class")
    def schema(self) -> Any:
        return json.loads(_SCHEMA_PATH.read_text())

    @pytest.fixture(scope="class")
    def validator_cls(self) -> type:
        """SARIF 2.1.0 uses draft-07.  Using the wrong draft gives
        confusing errors about $schema itself being invalid.
        """
        from jsonschema import Draft7Validator

        return Draft7Validator

    def _validate(self, doc: Any, schema: Any, cls: type) -> None:
        """Run validation and surface ALL errors, not just the first.
        jsonschema's default .validate() stops at the first error;
        iter_errors gives the full picture when you break multiple
        things at once (common during development).
        """
        errors = list(cls(schema).iter_errors(doc))
        if errors:
            summary = "\n".join(
                f"  {list(e.absolute_path)}: {e.message}" for e in errors
            )
            pytest.fail(f"SARIF schema violations:\n{summary}")

    def test_empty_run_is_schema_valid(self, schema: Any, validator_cls: type) -> None:
        doc = _emit(_make_summary())
        self._validate(doc, schema, validator_cls)

    def test_full_featured_document_is_schema_valid(
        self, schema: Any, validator_cls: type, tmp_path: Path
    ) -> None:
        """Kitchen sink: every Finding field populated, multiple gates,
        multiple rules, file-only alongside file+region findings.  If
        this validates, the shape is right.
        """
        (tmp_path / "src.py").write_text("line1\nline2\nline3\n")
        (tmp_path / "cov.py").write_text("uncovered\n")

        results = [
            # Linter gate with sub-rules and full regions
            CheckResult(
                name="laziness:lint.py",
                status=CheckStatus.FAILED,
                duration=1.0,
                error="3 lint errors",
                fix_suggestion="Run the autofixer.",
                findings=[
                    Finding(
                        message="line too long (90 > 79)",
                        level=FindingLevel.WARNING,
                        file="src.py",
                        line=1,
                        column=80,
                        end_line=1,
                        end_column=91,
                        rule_id="E501",
                    ),
                    Finding(
                        message="unused import 'os'",
                        level=FindingLevel.ERROR,
                        file="src.py",
                        line=2,
                        rule_id="F401",
                    ),
                ],
            ),
            # Gate with file but no line — artifactLocation without
            # region.  Still valid: GitHub needs a file to anchor on,
            # not necessarily a line.
            CheckResult(
                name="overconfidence:coverage.py",
                status=CheckStatus.FAILED,
                duration=2.0,
                error="Coverage below threshold",
                findings=[
                    Finding(
                        message="Coverage 72.0% below 80%",
                        level=FindingLevel.ERROR,
                        file="cov.py",
                    )
                ],
            ),
            # Warned gate — soft failure, warning level
            CheckResult(
                name="myopia:debt.py",
                status=CheckStatus.WARNED,
                duration=0.5,
                error="config drift detected",
                findings=[
                    Finding(
                        message="Gate threshold loosened",
                        level=FindingLevel.WARNING,
                        file="src.py",
                        line=3,
                    )
                ],
            ),
            # Legacy gate with no findings — emits a repo-root result
            # using the error text (see TestUnmigratedGate)
            CheckResult(
                name="legacy:old.py",
                status=CheckStatus.FAILED,
                duration=0.1,
                error="old-style failure",
            ),
            # Passed gate — contributes nothing
            CheckResult(name="ok:gate", status=CheckStatus.PASSED, duration=0.1),
        ]
        doc = _emit(_make_summary(*results), root=str(tmp_path))
        self._validate(doc, schema, validator_cls)

        # 2 from lint + 1 coverage + 1 warned + 1 legacy fallback = 5.
        # Passed gate contributes zero.
        assert len(doc["runs"][0]["results"]) == 5
        # Every result has locations[] — the GitHub invariant.
        for r in doc["runs"][0]["results"]:
            assert "locations" in r and r["locations"]
