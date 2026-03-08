"""Integration tests: SARIF output against real gate failures.

The unit suite (``tests/unit/test_sarif.py``) proves ``SarifReporter``
produces correctly-shaped documents from hand-built ``Finding``
fixtures.  That's necessary but not sufficient — it doesn't catch the
class of bug where a gate's parsing logic is wrong and it emits
``Finding(file=None)`` for something that SHOULD have a file, or the
gate forgets to thread ``findings=`` through ``_create_result`` and
it silently vanishes from SARIF (the reporter drops file-less
findings because GitHub's upload-sarif rejects them).

These tests close that gap by running ``sm swab --sarif`` against
``bucket-o-slop:all-fail`` — a repo deliberately broken in ways that
trip every gate that can fail — and asserting on the REAL output.
Schema validation here is the actual acceptance criterion from the
task spec: "sm scour --sarif produces schema-valid SARIF 2.1.0" is
only meaningful when the SARIF has content in it.

Verifying in GitHub
-------------------
This suite proves the payload is correct.  It can't prove GitHub
RENDERS it — that needs ``upload-sarif`` to run against a real PR.
To see annotations live:

  1. Fork ``bucket-o-slop``
    2. Copy ``.github/workflows/slopmop-sarif.yml`` from slop-mop into it
    3. Open a PR from ``all-fail`` into ``all-pass``
  4. The workflow runs, uploads SARIF, and Code Scanning decorates
     the diff with every gate's findings

Branch policy for fixture evolution:

    - Land test/workflow plumbing on ``all-pass`` first (clean baseline)
    - Then port to ``all-fail`` for alert-heavy screenshots/validation
    - Update ``mixed`` opportunistically when behavior diverges

That's the full loop.  The integration test gets you 95% of the way
there; the last 5% is GitHub's ingestion, which is their code not ours.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.integration.docker_manager import DockerManager

_ok, _reason = DockerManager.prerequisites_met()
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _ok, reason=_reason or "prerequisites not met"),
]

_SCHEMA_PATH = Path(__file__).parent.parent / "fixtures" / "sarif-2.1.0-schema.json"


# ------------------------------------------------------------------
# Helpers — Any-typed because we're walking untyped JSON.  The schema
# validator is the real type checker; pyright can't see through
# ["key"] chains and annotating every intermediate dict would be
# hundreds of lines of TypedDict that duplicate the schema file.
# ------------------------------------------------------------------


def _results(sarif: Any) -> list[Any]:
    return sarif["runs"][0]["results"]


def _rules(sarif: Any) -> list[Any]:
    return sarif["runs"][0]["tool"]["driver"]["rules"]


def _rule_ids(sarif: Any) -> set[str]:
    return {r["id"] for r in _rules(sarif)}


def _results_with_location(sarif: Any) -> list[Any]:
    """Results that carry a full physicalLocation → uri + startLine."""
    out: list[Any] = []
    for r in _results(sarif):
        for loc in r.get("locations", []):
            phys = loc.get("physicalLocation", {})
            uri = phys.get("artifactLocation", {}).get("uri")
            line = phys.get("region", {}).get("startLine")
            if uri and isinstance(line, int):
                out.append(r)
                break
    return out


# ------------------------------------------------------------------
# Schema — the acceptance criterion
# ------------------------------------------------------------------


class TestSchemaOnRealOutput:
    """``sm swab --sarif`` produces schema-valid SARIF 2.1.0.

    The unit suite validates schema on synthetic fixtures.  This
    validates schema on actual gate output — real vulture findings,
    real bandit issues, real pyright errors.  If a gate's parsing
    produces a ``Finding(column=0)`` (SARIF columns are 1-based and
    the schema rejects 0), the unit tests won't catch it because the
    fixtures were hand-authored to be correct.  This will.
    """

    def test_validates_against_draft7(self, sarif_all_fail: Any) -> None:
        jsonschema = pytest.importorskip("jsonschema")
        schema = json.loads(_SCHEMA_PATH.read_text())
        errors = list(jsonschema.Draft7Validator(schema).iter_errors(sarif_all_fail))
        if errors:
            detail = "\n".join(
                f"  {list(e.absolute_path)}: {e.message}" for e in errors[:10]
            )
            pytest.fail(
                f"SARIF from real gate output has {len(errors)} schema "
                f"violation(s):\n{detail}"
            )

    def test_has_content(self, sarif_all_fail: Any) -> None:
        """Empty SARIF is schema-valid but useless — all-fail MUST produce
        findings.  If this fails, either the fixture branch drifted or
        gates stopped emitting file-anchored findings (file-less ones
        are dropped at the reporter, so they wouldn't show up here)."""
        assert _results(sarif_all_fail), (
            "SARIF from all-fail has zero results — every gate should "
            "have failed and emitted at least one finding"
        )
        assert _rules(sarif_all_fail), "SARIF from all-fail has zero rules"


# ------------------------------------------------------------------
# physicalLocation — proving the file:line pipeline works end-to-end
# ------------------------------------------------------------------


class TestPhysicalLocation:
    """Enriched gates produce results with ``physicalLocation``.

    Second acceptance criterion.  The unit tests prove that IF a gate
    builds ``Finding(file=..., line=...)`` THEN the reporter nests it
    into ``physicalLocation``.  This proves gates actually DO build
    those findings from real tool output.

    Not every gate is expected to have a location — test failures and
    coverage shortfalls are aggregate metrics with no meaningful
    anchor point.  But dead-code, debugger-artifacts, and lint gates
    parse ``file:line`` from their tools and those MUST flow through.
    """

    def test_at_least_one_result_has_full_location(self, sarif_all_fail: Any) -> None:
        """Sanity floor: SOME gate produced a clickable annotation."""
        located = _results_with_location(sarif_all_fail)
        assert located, (
            f"None of the {len(_results(sarif_all_fail))} SARIF results "
            f"have a physicalLocation with uri+startLine.  Either every "
            f"gate is emitting file-less findings (check the UserWarning "
            f"rail in base.py — it should have fired) or the reporter is "
            f"dropping location data.\n"
            f"Rule IDs present: {sorted(_rule_ids(sarif_all_fail))}"
        )

    def test_dead_code_has_location(self, sarif_all_fail: Any) -> None:
        """Dead-code parses vulture's ``file:line:`` lines — location
        is the whole POINT of that gate, so a missing one means the
        parsing regressed."""
        dead = [
            r
            for r in _results_with_location(sarif_all_fail)
            if "dead-code" in r["ruleId"]
        ]
        assert dead, (
            f"laziness:dead-code.py produced no results with "
            f"physicalLocation.  bucket-o-slop:all-fail has "
            f"deliberately-unreferenced functions; vulture should find "
            f"them and the gate should emit Finding(file=, line=) for "
            f"each.  Rules seen: {sorted(_rule_ids(sarif_all_fail))}"
        )
        # Verify the shape deeply — uri is relative, line is positive
        loc = dead[0]["locations"][0]["physicalLocation"]
        uri = loc["artifactLocation"]["uri"]
        assert not uri.startswith(
            "/"
        ), f"uri should be repo-root-relative, got absolute: {uri!r}"
        assert not uri.startswith(
            "file://"
        ), f"uri should be a bare path, GitHub rejects file://: {uri!r}"
        assert (
            loc["region"]["startLine"] >= 1
        ), f"startLine must be 1-based: {loc['region']['startLine']}"

    def test_location_uris_point_at_fixture_files(self, sarif_all_fail: Any) -> None:
        """URIs should be paths inside bucket-o-slop, not slop-mop,
        not container temp paths, not percent-encoded nonsense.  The
        fixture repo is a Python + JS project so .py / .js / .ts
        extensions should dominate."""
        uris = {
            r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
            for r in _results_with_location(sarif_all_fail)
        }
        assert uris, "no URIs to check (covered by earlier test)"

        # None should leak container paths
        leaked = [u for u in uris if "/tmp/" in u or "/slopmop-src/" in u]
        assert not leaked, (
            f"URIs leak container-internal paths — the --output-file "
            f"remapping or _normalise_uri is wrong: {leaked}"
        )

        # Most should look like source files.  A handful of
        # config-file findings (.json, .toml) is fine; all-config
        # would mean the source-scanning gates aren't emitting.
        source_like = [u for u in uris if u.endswith((".py", ".js", ".ts", ".tsx"))]
        assert source_like, (
            f"No source-file URIs in SARIF — expected .py/.js from the "
            f"fixture codebase.  Got: {sorted(uris)}"
        )


# ------------------------------------------------------------------
# Coverage — every failed gate surfaces in SARIF
# ------------------------------------------------------------------


class TestGateCoverage:
    """Every gate that fails shows up as a rule.

    Guards against the quiet failure mode: a gate forgets to pass
    ``findings=`` to ``_create_result`` (or emits findings with no
    ``file=``), the UserWarning fires but gets swallowed by subprocess
    capture, the reporter drops the file-less findings, and nobody
    notices until a user asks why Code Scanning shows nothing for a
    gate that's clearly failing in the console log.

    We can't enumerate the exact expected gate set because it drifts
    with ``bucket-o-slop`` (pinned SHA notwithstanding — the pin
    moves when fixtures are updated).  Instead: assert the gate count
    is above a floor that would only be violated if the findings
    pipeline is systemically broken.
    """

    def test_multiple_gates_represented(self, sarif_all_fail: Any) -> None:
        # all-fail trips ~6-8 gates depending on which deps the
        # container has.  3 is a very conservative floor — if we're
        # below that, something structural is wrong.
        gate_prefixes = {r.split("/", 1)[0] for r in _rule_ids(sarif_all_fail)}
        assert len(gate_prefixes) >= 3, (
            f"Only {len(gate_prefixes)} gate(s) in SARIF rules: "
            f"{sorted(gate_prefixes)}.  bucket-o-slop:all-fail breaks "
            f"~6+ gates; fewer than 3 surfacing means findings aren't "
            f"flowing through the pipeline."
        )

    def test_every_result_has_locations(self, sarif_all_fail: Any) -> None:
        """The GitHub invariant, verified on real gate output.

        GitHub's ``upload-sarif`` action rejects results without
        ``locations[]`` — ``locationFromSarifResult: expected at
        least one location``.  The reporter filters these out at
        source (``_collect`` drops findings with no ``file``).  This
        test is the real-world confirmation: nothing slipped through.

        If this fails, some gate produced a Finding with a file path
        that survived the filter but then ``_build_result`` failed to
        turn it into a ``physicalLocation``.  Look at the reporter,
        not the gate.
        """
        missing = [r for r in _results(sarif_all_fail) if not r.get("locations")]
        if missing:
            rule_ids = sorted({r["ruleId"] for r in missing})
            pytest.fail(
                f"{len(missing)} result(s) without locations[] — GitHub's "
                f"upload-sarif would reject the whole file.  Rules: {rule_ids}"
            )


# ------------------------------------------------------------------
# Fingerprints — dedup keys on real content
# ------------------------------------------------------------------


class TestFingerprints:
    """``partialFingerprints`` on real findings with real source lines.

    Unit tests prove the hash is stable across line shifts using temp
    files.  This proves it's computed at all on real output — the
    reporter reads the SOURCE FILE to get line content, and if the
    path resolution is off (container workdir vs project root vs
    temp-copy remapping) the file-open fails silently and the
    fingerprint is omitted.
    """

    def test_located_results_have_fingerprints(self, sarif_all_fail: Any) -> None:
        located = _results_with_location(sarif_all_fail)
        fingerprinted = [
            r
            for r in located
            if r.get("partialFingerprints", {}).get("primaryLocationLineHash")
        ]
        # Not every located result MUST have a fingerprint — if the
        # file genuinely can't be read (permissions, race) we drop it
        # rather than crash.  But MOST should.  A zero here means the
        # reporter's path resolution is broken inside the container.
        assert fingerprinted, (
            f"{len(located)} results have physicalLocation but NONE "
            f"have partialFingerprints.  SarifReporter._fingerprint "
            f"reads the source file to hash line content — this "
            f"failing for every result means path resolution between "
            f"project_root and the container workdir is wrong."
        )

    def test_fingerprints_are_distinct(self, sarif_all_fail: Any) -> None:
        """Different findings → different fingerprints.  Collision
        means the hash inputs are too coarse (e.g., only hashing the
        gate name, not the file or line content)."""
        prints = [
            r["partialFingerprints"]["primaryLocationLineHash"]
            for r in _results(sarif_all_fail)
            if "partialFingerprints" in r
        ]
        if len(prints) < 2:
            pytest.skip(f"only {len(prints)} fingerprint(s) — need ≥2 to compare")
        # Some duplication is fine (same line flagged by two gates,
        # or genuine same-content-different-file).  But ALL-identical
        # means the occurrence suffix isn't working.
        assert len(set(prints)) > 1, (
            f"All {len(prints)} fingerprints are identical: "
            f"{prints[0]!r}.  The hash is collapsing distinct findings."
        )
