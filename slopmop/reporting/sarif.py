"""SARIF 2.1.0 reporter for GitHub Code Scanning.

SARIF (Static Analysis Results Interchange Format) is the ingestion
format for GitHub Code Scanning.  A SARIF file uploaded via
``github/codeql-action/upload-sarif`` becomes inline PR annotations,
a populated Security tab, and cross-commit alert tracking — all with
zero custom GitHub App code on our side.

This module implements the subset of SARIF 2.1.0 that GitHub actually
consumes.  The full OASIS spec is enormous (hundreds of object types,
most unused in practice); GitHub renders a narrow slice and silently
ignores the rest.  We target that slice deliberately.  See
https://docs.github.com/en/code-security/code-scanning/integrating-with-code-scanning/sarif-support-for-code-scanning
for the authoritative list of supported fields.

The mapping:

- One slopmop run → one SARIF ``run``
- One gate → one ``reportingDescriptor`` in ``tool.driver.rules[]``
- One :class:`Finding` → one ``result`` with ``physicalLocation``

Design notes for future maintainers:

partialFingerprints
    GitHub uses ``primaryLocationLineHash`` to deduplicate alerts
    across commits.  Without it, every push looks like a fresh set of
    problems.  The ``upload-sarif`` action WILL compute these if you
    omit them (it reads the source files from the runner workspace),
    but we generate our own so the SARIF file is self-contained and
    works via direct REST API upload too.  Our hash is simpler than
    GitHub's rolling-polynomial algorithm — we hash the stripped line
    content plus gate/rule identity — but stability-across-line-shifts
    is the property that matters, and ours has it.

artifactLocation.uri
    Relative POSIX path from repo root.  NOT ``file://`` — GitHub
    can't match absolute URIs to repo files without extra config.
    NOT backslashes — SARIF mandates forward slashes even on Windows.
    We normalise both at emission time so gates don't have to care.

Columns are 1-based
    The SARIF schema enforces ``startColumn >= 1``.  Tools like
    pyright emit 0-based columns; gates must add 1 before building
    :class:`Finding` objects.  We don't second-guess here — if a gate
    passes ``column=0`` we emit it and the schema validator catches it.
"""

import hashlib
import urllib.parse
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, cast

from slopmop.core.result import (
    CheckResult,
    CheckStatus,
    ExecutionSummary,
    Finding,
)

# The schema URL GitHub's docs use.  Both this and the raw OASIS URL
# validate identically; this one is shorter and what ruff/bandit emit.
SARIF_SCHEMA_URI = "https://json.schemastore.org/sarif-2.1.0.json"
SARIF_VERSION = "2.1.0"

# Only results from gates in these states make it into the SARIF file.
# PASSED means nothing to report.  ERROR is an infrastructure failure
# (tool missing, timeout) — that's a SARIF "toolExecutionNotification",
# not a ``result``, and GitHub doesn't render those anyway.  SKIPPED /
# NOT_APPLICABLE similarly have no code findings.
_EMITTING_STATUSES = frozenset([CheckStatus.FAILED, CheckStatus.WARNED])


class SarifReporter:
    """Transform an :class:`ExecutionSummary` into SARIF 2.1.0 JSON.

    One instance per emission.  The reporter caches file contents for
    fingerprint generation — the same file typically yields many
    findings (one flake8 run, fifty F401s in the same module), so we
    read each file once and index by line.
    """

    def __init__(self, project_root: str) -> None:
        self._root = Path(project_root).resolve()
        # file path (relative, POSIX) → list of line contents
        self._line_cache: Dict[str, List[str]] = {}

    def generate(self, summary: ExecutionSummary) -> Dict[str, object]:
        """Build the full SARIF document.

        Returns a plain dict ready for ``json.dumps()``.  Callers own
        serialisation so they can choose indentation, output stream, etc.
        """
        from slopmop import __version__  # late import: avoids cycle risk

        rules, results = self._collect(summary)

        driver: Dict[str, object] = {
            "name": "slopmop",
            "informationUri": "https://github.com/ScienceIsNeato/slop-mop",
            "semanticVersion": __version__,
            "rules": rules,
        }

        run: Dict[str, object] = {
            "tool": {"driver": driver},
            "results": results,
        }

        return {
            "$schema": SARIF_SCHEMA_URI,
            "version": SARIF_VERSION,
            "runs": [run],
        }

    def _collect(
        self, summary: ExecutionSummary
    ) -> tuple[List[Dict[str, object]], List[Dict[str, object]]]:
        """Walk results, building (rules, results) in one pass.

        Rules are a deduplicated set — two findings with the same
        ``(gate_name, rule_id)`` share one ``reportingDescriptor``.
        Results are a flat list, one per finding.

        Only findings with a ``file`` make it in.  GitHub's
        ``upload-sarif`` action rejects location-less results with
        ``locationFromSarifResult: expected at least one location`` —
        stricter than the schema, which permits absent ``locations``.
        We learned this the hard way: an earlier version synthesised
        a location-less result for gates that hadn't migrated to
        structured findings, reasoning "a vague alert is better than
        nothing".  GitHub disagreed — it failed the whole upload.

        So: no file, no SARIF result.  A gate that fails without any
        file-anchored findings is still caught by the CI exit code
        and slopmop's own console/JSON output; it just won't get a
        PR annotation.  That's the best we can do without inventing
        a fake location, and the ``_create_result`` UserWarning rail
        in ``base.py`` already nudges gate authors to supply one.
        """
        rules_by_id: Dict[str, Dict[str, object]] = {}
        results: List[Dict[str, object]] = []

        for check in summary.results:
            if check.status not in _EMITTING_STATUSES:
                continue

            findings = [f for f in (check.findings or ()) if f.file is not None]

            for finding in findings:
                rule_id = self._compose_rule_id(check.name, finding.rule_id)
                if rule_id not in rules_by_id:
                    rules_by_id[rule_id] = self._build_rule(rule_id, check, finding)
                results.append(self._build_result(rule_id, check, finding))

        return list(rules_by_id.values()), results

    @staticmethod
    def _compose_rule_id(gate_name: str, sub_rule: Optional[str]) -> str:
        """Compose the SARIF ``ruleId`` from gate name and sub-rule.

        ``overconfidence:type-blindness.py`` + ``reportUnknownVariableType``
        → ``overconfidence:type-blindness.py/reportUnknownVariableType``

        The slash separator is a SARIF convention for hierarchical rule
        IDs.  GitHub renders the full path in alert detail but allows
        filtering on the prefix, so users can filter by gate OR by
        specific sub-rule.  When there's no sub-rule we use the gate
        name alone — every gate has at least one rule (itself).
        """
        if sub_rule:
            return f"{gate_name}/{sub_rule}"
        return gate_name

    def _build_rule(
        self, rule_id: str, check: CheckResult, finding: Finding
    ) -> Dict[str, object]:
        """Build a SARIF ``reportingDescriptor`` for ``tool.driver.rules[]``.

        GitHub uses:
        - ``id``: alert list, URL slug, filtering
        - ``shortDescription.text``: shown next to each result (1024 char cap)
        - ``fullDescription.text``: alert detail page (1024 char cap)
        - ``help.text``: expandable help section
        - ``defaultConfiguration.level``: fallback when result has no level

        We use the gate name as short description (it's designed for
        exactly this: ``laziness:dead-code.py`` reads as a complete
        sentence about what's wrong).  ``fix_suggestion`` becomes the
        help text — that's the actionable guidance users need.
        """
        rule: Dict[str, object] = {
            "id": rule_id,
            "shortDescription": {"text": check.name},
            "defaultConfiguration": {"level": finding.level.value},
        }
        # Build fullDescription from whichever detail we have.  Prefer
        # the error summary (it's the one-line verdict) and fall back
        # to the first line of output.  Empty strings are not valid
        # SARIF — omit the field entirely rather than emit "".
        desc = check.error or (check.output.splitlines()[0] if check.output else None)
        if desc:
            rule["fullDescription"] = {"text": desc}
        if check.fix_suggestion:
            rule["help"] = {"text": check.fix_suggestion}
        return rule

    def _build_result(
        self, rule_id: str, check: CheckResult, finding: Finding
    ) -> Dict[str, object]:
        """Build a SARIF ``result`` object — one per finding.

        The nesting for ``physicalLocation`` is precise and unforgiving;
        GitHub ignores results that get it wrong.  We build the region
        inside-out, only attaching fields we actually have — an empty
        region object is valid SARIF but adds noise, so we omit it when
        there's no line number.
        """
        result: Dict[str, object] = {
            "ruleId": rule_id,
            "level": finding.level.value,
            "message": {"text": finding.message},
        }

        if finding.file is not None:
            uri = self._normalise_uri(finding.file)
            physical: Dict[str, object] = {"artifactLocation": {"uri": uri}}

            region: Dict[str, int] = {}
            if finding.line is not None:
                region["startLine"] = finding.line
            if finding.column is not None:
                region["startColumn"] = finding.column
            if finding.end_line is not None:
                region["endLine"] = finding.end_line
            if finding.end_column is not None:
                region["endColumn"] = finding.end_column
            if region:
                physical["region"] = region

            result["locations"] = [{"physicalLocation": physical}]

            fingerprint = self._fingerprint(check.name, finding, uri)
            if fingerprint is not None:
                result["partialFingerprints"] = {"primaryLocationLineHash": fingerprint}

        return result

    def _normalise_uri(self, path: str) -> str:
        """Convert a gate-supplied path into a SARIF artifact URI.

        Gates might hand us anything: relative, absolute, backslashed
        on Windows, already-POSIX.  GitHub wants a relative POSIX path
        from repo root, percent-encoded.  This function is idempotent —
        calling it on an already-normalised path is a no-op.

        We resolve absolute paths against the project root and strip
        the prefix.  If the path escapes the project root (symlink,
        vendored code elsewhere) we fall back to whatever the gate
        gave us, POSIX-ified — better to emit a possibly-unmatchable
        URI than to drop the finding.  GitHub will still show it in
        the Security tab, just without a file link.
        """
        p = Path(path)
        if p.is_absolute():
            try:
                p = p.resolve().relative_to(self._root)
            except ValueError:
                # Outside project root — use as-is but strip leading sep
                # so it at least looks like a relative path.  The
                # str(PurePosixPath(...)) below handles the separator
                # normalisation uniformly.
                pass
        # PurePosixPath handles backslash → slash on Windows.  Quote
        # handles spaces and non-ASCII — SARIF URIs are RFC 3986.
        posix = str(PurePosixPath(*p.parts)).lstrip("/")
        return urllib.parse.quote(posix)

    def _fingerprint(self, gate_name: str, finding: Finding, uri: str) -> Optional[str]:
        """Compute ``primaryLocationLineHash`` for cross-commit dedup.

        GitHub's own algorithm (in ``codeql-action/src/fingerprints.ts``)
        is a rolling polynomial hash over a 100-char window starting at
        the result's line.  We don't replicate that exactly — it's
        complex, JS-specific in its wraparound behaviour, and overkill
        for our needs.  What matters is: the hash must be stable when
        unrelated code moves above the finding (shifting line numbers)
        but UNSTABLE when the finding itself changes.

        Our algorithm: sha256 of (gate, rule, file, stripped line text).
        The line number is deliberately excluded — that's the whole
        point, line numbers drift.  The stripped line text IS the
        identity: if someone fixes the issue, the line text changes,
        the hash changes, GitHub closes the old alert.

        The ``:1`` suffix is an occurrence counter — if the same hash
        appears twice in one file (identical duplicate lines, same
        gate, same rule) GitHub needs to distinguish them.  We track
        occurrences across the whole emission, not per-file — close
        enough for the pathological case, and correct for the common
        case where every finding has a unique line.

        Returns ``None`` when we can't read the file (deleted since
        the check ran, permissions, whatever) — the SARIF file is
        still valid without fingerprints, and the ``upload-sarif``
        action will compute its own.  Belt and braces.
        """
        if finding.line is None:
            return None

        lines = self._line_cache.get(uri)
        if lines is None:
            # Unquote to reverse what _normalise_uri did — we need the
            # real filesystem path to open the file.
            fs_path = self._root / urllib.parse.unquote(uri)
            try:
                lines = fs_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
            except OSError:
                # Cache the miss so we don't retry on every finding
                # in the same file.  An empty list is distinguishable
                # from "not yet read" because we set it explicitly.
                lines = []
            self._line_cache[uri] = lines

        # 1-based → 0-based index.  Guard both underflow (line 0, which
        # shouldn't happen per SARIF but defensive) and overflow (line
        # past EOF — tool output is stale, file was edited).
        idx = finding.line - 1
        if idx < 0 or idx >= len(lines):
            return None

        key = "\0".join(
            [
                gate_name,
                finding.rule_id or "",
                uri,
                lines[idx].strip(),
            ]
        )
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

        # Occurrence tracking.  We key on the digest itself — if two
        # findings produce the same digest they ARE the same finding
        # from SARIF's perspective, and the :N suffix disambiguates.
        # The counter lives on the instance because one SarifReporter
        # instance handles one SARIF emission.
        if not hasattr(self, "_occurrence"):
            self._occurrence: Dict[str, int] = cast(Dict[str, int], {})
        count = self._occurrence.get(digest, 0) + 1
        self._occurrence[digest] = count

        return f"{digest}:{count}"
