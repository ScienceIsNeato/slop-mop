"""SARIF 2.1.0 reporter for GitHub Code Scanning integration.

SARIF (Static Analysis Results Interchange Format) is the OASIS standard
that GitHub Code Scanning consumes.  Uploading a SARIF file via
``github/codeql-action/upload-sarif@v4`` renders inline PR annotations,
tracks alerts across commits, and populates the repository Security tab.

The mapping is:

* Each gate becomes a ``reportingDescriptor`` in ``tool.driver.rules[]``.
* Each :pyclass:`~slopmop.core.result.Finding` becomes a ``result`` with
  a ``physicalLocation``.
* Gates that fail without structured findings emit a single result
  anchored at the repo root (the fallback path for custom shell gates).

GitHub's SARIF ingester is stricter than the OASIS schema: every result
MUST carry at least one location or the upload is rejected with
``locationFromSarifResult: expected at least one location``.  For
project-scoped findings (config debt, custom shell gates, crashed gates)
we emit a sentinel location pointing at ``.`` — the repo root.  The
finding still appears in the Security tab; it just doesn't get an inline
file annotation.

Path normalisation happens here, at the point of URI construction, not
in each gate.  Gates emit whatever the underlying tool produced (often
OS-native separators); we canonicalise to forward-slash once.  Future
gates get this for free.

``partialFingerprints`` are computed from ``(ruleId, file, message)`` —
deliberately excluding line number so a finding is recognised as the same
alert even when the offending code shifts by a few lines.  GitHub's
``upload-sarif`` action additionally computes ``primaryLocationLineHash``
from file content; the two fingerprints together give maximum dedup signal.

Reference:
    https://docs.github.com/en/code-security/code-scanning/integrating-with-code-scanning/sarif-support-for-code-scanning
"""

import hashlib
import json
from typing import Any, Dict, List, Optional

from slopmop.core.result import CheckStatus, ExecutionSummary, Finding

SARIF_SCHEMA_URI = "https://json.schemastore.org/sarif-2.1.0.json"
SARIF_VERSION = "2.1.0"
TOOL_NAME = "slop-mop"
TOOL_URI = "https://github.com/ScienceIsNeato/slop-mop"

# Only actionable statuses produce SARIF results.  PASSED / SKIPPED /
# NOT_APPLICABLE are silent — the rule still appears in the driver
# catalog but emits no result instances.
_STATUS_TO_LEVEL: Dict[CheckStatus, str] = {
    CheckStatus.FAILED: "error",
    CheckStatus.ERROR: "error",
    CheckStatus.WARNED: "warning",
}


class SarifReporter:
    """Builds a SARIF 2.1.0 document from an :pyclass:`ExecutionSummary`."""

    def __init__(self, version: str = "unknown") -> None:
        self._version = version

    # ── public ────────────────────────────────────────────────────────

    def build(self, summary: ExecutionSummary) -> Dict[str, Any]:
        """Build the full SARIF document as a dict."""
        run: Dict[str, Any] = {
            "tool": {"driver": self._build_driver(summary)},
            "results": self._build_results(summary),
        }
        return {
            "$schema": SARIF_SCHEMA_URI,
            "version": SARIF_VERSION,
            "runs": [run],
        }

    def to_json(self, summary: ExecutionSummary) -> str:
        """Build the SARIF document and serialise it to compact JSON."""
        return json.dumps(self.build(summary), separators=(",", ":"))

    # ── driver (rule catalog) ─────────────────────────────────────────

    def _build_driver(self, summary: ExecutionSummary) -> Dict[str, Any]:
        """Build ``tool.driver`` with one rule per gate that ran.

        Rules are emitted for every gate regardless of pass/fail — this
        is the rule *catalog*, separate from result instances.  Metadata
        (display name, description, category) is pulled from the live
        registry so SARIF output stays in sync with gate definitions.
        """
        rules: List[Dict[str, Any]] = []
        seen: set[str] = set()

        # Registry lookup is best-effort: tests construct CheckResults
        # directly without registering gates, and custom shell gates
        # live outside the registry.  A minimal rule (id + default
        # level) is still valid SARIF.
        try:
            from slopmop.core.registry import get_registry

            registry = get_registry()
        except Exception:
            registry = None

        for result in summary.results:
            if result.name in seen:
                continue
            seen.add(result.name)

            rule: Dict[str, Any] = {
                "id": result.name,
                "defaultConfiguration": {"level": "error"},
            }

            check = self._lookup_check(registry, result.name)
            if check is not None:
                rule["name"] = check.display_name
                rule["shortDescription"] = {"text": check.gate_description}
                # Custom shell gates can exist in the registry with
                # category=None — the same guard _create_result uses.
                if check.category is not None:
                    rule["properties"] = {"category": check.category.key}
            elif result.category:
                rule["properties"] = {"category": result.category}

            rules.append(rule)

        return {
            "name": TOOL_NAME,
            "version": self._version,
            "informationUri": TOOL_URI,
            "rules": rules,
        }

    @staticmethod
    def _lookup_check(registry: Optional[Any], name: str) -> Optional[Any]:
        if registry is None:
            return None
        try:
            return registry.get_check(name, {})
        except Exception:
            return None

    # ── results (findings) ────────────────────────────────────────────

    def _build_results(self, summary: ExecutionSummary) -> List[Dict[str, Any]]:
        """Build the ``results`` array — one entry per Finding.

        A gate with 5 findings emits 5 SARIF results.  A gate that
        FAILED or ERRORed with zero findings (legacy text-only path,
        custom shell gates) emits one locationless result using its
        error or output text.
        """
        out: List[Dict[str, Any]] = []
        for r in summary.results:
            level = _STATUS_TO_LEVEL.get(r.status)
            if level is None:
                continue

            if r.findings:
                for f in r.findings:
                    out.append(self._build_result(r.name, level, f))
            else:
                # Locationless fallback.  Use the first non-empty text
                # source.  SARIF result messages can't be empty.
                msg = (r.error or r.output or f"{r.name} failed").strip()
                msg = msg or f"{r.name} failed"
                out.append(self._build_result(r.name, level, Finding(message=msg)))
        return out

    def _build_result(
        self, rule_id: str, level: str, finding: Finding
    ) -> Dict[str, Any]:
        """Build a single SARIF result with physicalLocation and fingerprint."""
        res: Dict[str, Any] = {
            "ruleId": rule_id,
            "level": level,
            "message": {"text": finding.message},
            "locations": [{"physicalLocation": self._build_location(finding)}],
            "partialFingerprints": {
                "slopmopFingerprint/v1": self._fingerprint(rule_id, finding),
            },
        }

        if finding.rule_id:
            res.setdefault("properties", {})["subRule"] = finding.rule_id

        return res

    @staticmethod
    def _build_location(finding: Finding) -> Dict[str, Any]:
        """Build ``physicalLocation`` — always present, even for project-scoped findings.

        GitHub's ingester rejects any result missing ``locations``.  When
        the finding has no file we anchor at ``.`` (repo root): the alert
        lands in the Security tab without an inline annotation, which is
        exactly right for config-level or crash-level issues.

        URIs require forward-slash separators.  We normalise here rather
        than asking every gate to remember — tools on Windows emit
        backslashes, and a gate author shouldn't need to know about
        SARIF URI rules.  Backslash replacement (not ``os.sep``) covers
        the cross-platform case where a Windows-produced path is
        serialised on a Linux CI runner.
        """
        if not finding.file:
            return {"artifactLocation": {"uri": "."}}

        loc: Dict[str, Any] = {
            "artifactLocation": {"uri": finding.file.replace("\\", "/")},
        }
        region = SarifReporter._build_region(finding)
        if region:
            loc["region"] = region
        return loc

    @staticmethod
    def _build_region(finding: Finding) -> Optional[Dict[str, int]]:
        """Build the ``region`` dict (1-based line/column ranges).

        SARIF mandates ≥1 for every region coordinate.  ``Finding`` says
        "1-based" in its docstring but doesn't enforce it — if a gate
        forwards a 0-based index from some tool's JSON, we drop that
        field rather than emit schema-invalid output.  The result
        degrades to file-level (still useful) instead of poisoning the
        whole upload.
        """

        def _pos(v: Optional[int]) -> Optional[int]:
            return v if v is not None and v >= 1 else None

        region: Dict[str, int] = {}
        if (n := _pos(finding.line)) is not None:
            region["startLine"] = n
        if (n := _pos(finding.end_line)) is not None:
            region["endLine"] = n
        if (n := _pos(finding.column)) is not None:
            region["startColumn"] = n
        if (n := _pos(finding.end_column)) is not None:
            region["endColumn"] = n
        return region or None

    @staticmethod
    def _fingerprint(rule_id: str, finding: Finding) -> str:
        """Compute a line-shift-stable fingerprint.

        Deliberately omits line number: a function that moves three
        lines down is still the same violation.  The message already
        encodes the specific function name / tautology / issue, so
        ``(ruleId, file, message)`` is both stable and discriminating.
        """
        raw = f"{rule_id}|{finding.file or ''}|{finding.message}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
