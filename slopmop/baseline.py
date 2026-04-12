"""Baseline snapshot helpers for known-failure filtering.

v1 intentionally keeps the surface area small:

* ``sm status --generate-baseline-snapshot`` saves a local snapshot from the
  latest persisted run artifact.
* ``sm swab|scour --ignore-baseline-failures`` still executes every check, then
  downgrades failures already present in the snapshot.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, cast

from slopmop.core.result import CheckResult, CheckStatus, ExecutionSummary, Finding

_SLOPMOP_DIR = ".slopmop"
_LAST_SWAB = "last_swab.json"
_LAST_SCOUR = "last_scour.json"
_SNAPSHOT_FILE = "baseline_snapshot.json"
_SCHEMA_VERSION = "slopmop/baseline-v1"


@dataclass(frozen=True)
class BaselineFilterOutcome:
    """Filtered run result plus metadata for reporting layers."""

    filtered_summary: ExecutionSummary
    metadata: Dict[str, object]


def baseline_snapshot_path(project_root: str | Path) -> Path:
    """Return the conventional local baseline snapshot path."""
    return Path(project_root) / _SLOPMOP_DIR / _SNAPSHOT_FILE


def latest_run_artifact_path(project_root: str | Path) -> Optional[Path]:
    """Return the most comprehensive persisted run artifact, if any.

    Scour covers all gate levels (swab + scour), so it is always preferred
    when present, regardless of modification time.  If only swab has run,
    that artifact is returned as a fallback.
    """
    root = Path(project_root)
    scour_path = root / _SLOPMOP_DIR / _LAST_SCOUR
    swab_path = root / _SLOPMOP_DIR / _LAST_SWAB
    if scour_path.exists() and scour_path.is_file():
        return scour_path
    if swab_path.exists() and swab_path.is_file():
        return swab_path
    return None


def generate_baseline_snapshot(project_root: str | Path) -> Tuple[Path, Path]:
    """Capture a local baseline snapshot from the newest persisted run artifact."""
    source = latest_run_artifact_path(project_root)
    if source is None:
        raise FileNotFoundError(
            "No persisted run artifact found. Run sm swab or sm scour first."
        )
    return generate_baseline_snapshot_from_artifact(project_root, source)


def generate_baseline_snapshot_from_artifact(
    project_root: str | Path, source: str | Path
) -> Tuple[Path, Path]:
    """Capture a local baseline snapshot from an explicit artifact path."""
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(f"Artifact not found: {source}")

    try:
        source_data = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse {source.name}: {exc}") from exc

    if not isinstance(source_data, dict):
        raise ValueError(f"{source.name} does not contain a JSON object")

    source_dict = cast(Dict[str, Any], source_data)
    snapshot: Dict[str, object] = {
        "schema": _SCHEMA_VERSION,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_file": source.name,
        "source_level": source_dict.get("level"),
        "source_artifact": source_dict,
        "failure_fingerprints": sorted(_fingerprints_from_artifact(source_dict)),
    }

    path = baseline_snapshot_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return path, source


def load_baseline_snapshot(project_root: str | Path) -> Optional[Dict[str, Any]]:
    """Load the local baseline snapshot, or return ``None`` when absent/invalid."""
    path = baseline_snapshot_path(project_root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return cast(Dict[str, Any], data)


def filter_summary_against_baseline(
    summary: ExecutionSummary,
    snapshot: Dict[str, Any],
    *,
    snapshot_path: Optional[Path] = None,
) -> BaselineFilterOutcome:
    """Downgrade failures already present in the baseline snapshot."""
    baseline_fingerprints = {
        fp
        for fp in snapshot.get("failure_fingerprints", [])
        if isinstance(fp, str) and fp
    }

    raw_failed = 0
    filtered_failed = 0
    filtered_findings = 0
    preserved_results: List[CheckResult] = []

    for result in summary.results:
        if result.status != CheckStatus.FAILED:
            preserved_results.append(copy.deepcopy(result))
            continue

        raw_failed += 1
        transformed, matched_count, fully_filtered = _filter_failed_result(
            result, baseline_fingerprints
        )
        filtered_findings += matched_count
        if fully_filtered:
            filtered_failed += 1
        preserved_results.append(transformed)

    filtered_summary = ExecutionSummary(
        total_checks=summary.total_checks,
        passed=sum(1 for r in preserved_results if r.status == CheckStatus.PASSED),
        failed=sum(1 for r in preserved_results if r.status == CheckStatus.FAILED),
        warned=sum(1 for r in preserved_results if r.status == CheckStatus.WARNED),
        skipped=sum(1 for r in preserved_results if r.status == CheckStatus.SKIPPED),
        not_applicable=sum(
            1 for r in preserved_results if r.status == CheckStatus.NOT_APPLICABLE
        ),
        errors=sum(1 for r in preserved_results if r.status == CheckStatus.ERROR),
        total_duration=summary.total_duration,
        results=preserved_results,
    )

    metadata: Dict[str, object] = {
        "active": True,
        "snapshot_path": str(snapshot_path) if snapshot_path else None,
        "source_file": snapshot.get("source_file"),
        "raw_failed": raw_failed,
        "filtered_failed": filtered_failed,
        "net_new_failed": filtered_summary.failed,
        "filtered_findings": filtered_findings,
    }
    if snapshot.get("captured_at"):
        metadata["captured_at"] = snapshot["captured_at"]
    return BaselineFilterOutcome(filtered_summary=filtered_summary, metadata=metadata)


def _filter_failed_result(
    result: CheckResult,
    baseline_fingerprints: set[str],
) -> Tuple[CheckResult, int, bool]:
    """Return ``(transformed_result, matched_count, fully_filtered)``."""
    transformed = copy.deepcopy(result)
    if result.findings:
        remaining: List[Finding] = []
        matched = 0
        for finding in result.findings:
            if _finding_fingerprint(result.name, finding) in baseline_fingerprints:
                matched += 1
            else:
                remaining.append(copy.deepcopy(finding))

        if remaining:
            transformed.findings = remaining
            transformed.output = "\n".join(str(finding) for finding in remaining)
            return transformed, matched, False

        transformed.status = CheckStatus.WARNED
        transformed.findings = []
        transformed.output = (
            f"{matched} finding(s) matched the baseline snapshot; "
            "no net-new failures in this gate."
        )
        transformed.status_detail = "baseline_filtered"
        return transformed, matched, True

    if _result_fingerprint(result) in baseline_fingerprints:
        transformed.status = CheckStatus.WARNED
        transformed.output = (
            "This gate failure matched the baseline snapshot; "
            "no net-new failure detected."
        )
        transformed.status_detail = "baseline_filtered"
        return transformed, 1, True

    return transformed, 0, False


def _fingerprints_from_artifact(data: Dict[str, Any]) -> set[str]:
    """Extract failure fingerprints from a persisted run artifact."""
    results_raw: object = data.get("results", [])
    if not isinstance(results_raw, list):
        return set()

    fingerprints: set[str] = set()
    results_list = cast(List[object], results_raw)
    for item in results_list:
        if not isinstance(item, dict):
            continue
        entry = cast(Dict[str, Any], item)
        if entry.get("status") != CheckStatus.FAILED.value:
            continue

        name = str(entry.get("name", ""))
        findings: object = entry.get("findings")
        if isinstance(findings, list) and findings:
            findings_list = cast(List[object], findings)
            for raw_finding in findings_list:
                if isinstance(raw_finding, dict):
                    fp = _finding_fingerprint_from_dict(
                        name, cast(Dict[str, Any], raw_finding)
                    )
                    if fp:
                        fingerprints.add(fp)
            continue

        fp = _result_fingerprint_from_dict(entry)
        if fp:
            fingerprints.add(fp)
    return fingerprints


def _finding_fingerprint(gate_name: str, finding: Finding) -> str:
    """Stable fingerprint for one structured finding."""
    return _hash_parts(
        [
            "finding",
            gate_name,
            finding.rule_id or "",
            finding.file or "",
            str(finding.line or ""),
            str(finding.column or ""),
            _normalize_text(finding.message),
        ]
    )


def _finding_fingerprint_from_dict(
    gate_name: str, finding: Dict[str, Any]
) -> Optional[str]:
    message = finding.get("message")
    if not isinstance(message, str):
        return None
    return _hash_parts(
        [
            "finding",
            gate_name,
            str(finding.get("rule_id") or ""),
            str(finding.get("file") or ""),
            str(finding.get("line") or ""),
            str(finding.get("column") or ""),
            _normalize_text(message),
        ]
    )


def _result_fingerprint(result: CheckResult) -> str:
    """Fallback fingerprint for gates without structured findings."""
    return _hash_parts(
        [
            "result",
            result.name,
            result.category or "",
            _normalize_text(result.error or result.output or result.name),
        ]
    )


def _result_fingerprint_from_dict(entry: Dict[str, Any]) -> Optional[str]:
    name = entry.get("name")
    if not isinstance(name, str):
        return None
    return _hash_parts(
        [
            "result",
            name,
            str(entry.get("category") or ""),
            _normalize_text(str(entry.get("error") or entry.get("output") or name)),
        ]
    )


def _hash_parts(parts: Iterable[str]) -> str:
    payload = "\x1f".join(parts).encode("utf-8", errors="ignore")
    return hashlib.sha256(payload).hexdigest()


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).strip().lower()
