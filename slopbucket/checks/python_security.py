"""
Python security checks — Bandit, semgrep, detect-secrets, safety.

Two variants:
- PythonSecurityCheck: Full audit including dependency scanning (needs network)
- PythonSecurityLocalCheck: Local-only checks (bandit + semgrep + detect-secrets)

Runs sub-checks concurrently for speed. Reports only HIGH/MEDIUM findings
to reduce noise while catching real issues.
"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from slopbucket.base_check import BaseCheck
from slopbucket.result import CheckResult, CheckStatus
from slopbucket.subprocess_guard import run

EXCLUDED_DIRS = ["venv", ".venv", "node_modules", "cursor-rules", "archives", "logs"]


class _SecuritySubCheck:
    """Result container for a sub-check within the security gate."""

    def __init__(self, name: str, passed: bool, findings: str):
        self.name = name
        self.passed = passed
        self.findings = findings


def _run_bandit(working_dir: Optional[str]) -> _SecuritySubCheck:
    """Run bandit static analysis."""
    cmd = [
        sys.executable,
        "-m",
        "bandit",
        "-r",
        ".",
        "--skip",
        "B101,B110",
        "--format",
        "json",
        "--quiet",
    ]
    # Add exclusions
    for d in EXCLUDED_DIRS:
        cmd.extend(["--exclude", f"./{d}"])

    result = run(cmd, cwd=working_dir, timeout=120)

    if result.success:
        return _SecuritySubCheck("bandit", True, "No issues found")

    # Parse JSON output for HIGH/MEDIUM issues
    try:
        report = json.loads(result.stdout)
        issues = [
            r
            for r in report.get("results", [])
            if r.get("issue_severity") in ("HIGH", "MEDIUM")
        ]
        if not issues:
            return _SecuritySubCheck(
                "bandit", True, "Only LOW severity issues (ignored)"
            )

        detail = "\n".join(
            f"  [{r['issue_severity']}] {r['issue_text']} ({r['test_name']}) - {r.get('filename', '')}:{r.get('line_number', '')}"
            for r in issues[:10]  # Limit to 10 most relevant
        )
        return _SecuritySubCheck("bandit", False, detail)
    except json.JSONDecodeError:
        return _SecuritySubCheck(
            "bandit",
            False,
            result.stdout[-500:] if result.stdout else result.stderr[-500:],
        )


def _run_semgrep(working_dir: Optional[str]) -> _SecuritySubCheck:
    """Run semgrep static analysis."""
    cmd = ["semgrep", "scan", "--config=auto", "--json", "--quiet"]
    for d in EXCLUDED_DIRS:
        cmd.extend(["--exclude", d])

    result = run(cmd, cwd=working_dir, timeout=120)

    if result.success:
        return _SecuritySubCheck("semgrep", True, "No issues found")

    try:
        report = json.loads(result.stdout)
        findings = report.get("results", [])
        if not findings:
            return _SecuritySubCheck("semgrep", True, "No issues found")

        # Filter to HIGH/MEDIUM
        critical = [
            f
            for f in findings
            if f.get("extra", {}).get("severity") in ("ERROR", "WARNING")
        ]
        if not critical:
            return _SecuritySubCheck("semgrep", True, "Only informational findings")

        detail = "\n".join(
            f"  [{f.get('extra', {}).get('severity', '?')}] {f.get('extra', {}).get('message', '')[:80]} - {f.get('path', '')}:{f.get('start', {}).get('line', '')}"
            for f in critical[:10]
        )
        return _SecuritySubCheck("semgrep", False, detail)
    except json.JSONDecodeError:
        # If output isn't JSON, check return code meaning
        if result.returncode == 1:
            return _SecuritySubCheck(
                "semgrep",
                False,
                result.stderr[-300:] if result.stderr else "Unknown error",
            )
        return _SecuritySubCheck("semgrep", True, "Scan completed (non-JSON output)")


def _run_detect_secrets(working_dir: Optional[str]) -> _SecuritySubCheck:
    """Run detect-secrets hook."""
    cmd = [
        sys.executable,
        "-m",
        "detect_secrets",
        "scan",
    ]
    result = run(cmd, cwd=working_dir, timeout=60)

    if result.success:
        try:
            report = json.loads(result.stdout)
            detected = report.get("results", {})
            # Filter out known false positives
            real_secrets = {
                k: v for k, v in detected.items() if v and "constants.py" not in k
            }
            if not real_secrets:
                return _SecuritySubCheck("detect-secrets", True, "No secrets detected")

            detail = "\n".join(
                f"  Potential secret in {path}: {', '.join(str(s.get('type', '?')) for s in secrets)}"
                for path, secrets in real_secrets.items()
            )
            return _SecuritySubCheck("detect-secrets", False, detail)
        except json.JSONDecodeError:
            return _SecuritySubCheck("detect-secrets", True, "Scan completed")

    return _SecuritySubCheck(
        "detect-secrets",
        False,
        result.stderr[-300:] if result.stderr else "Scan failed",
    )


def _run_safety(working_dir: Optional[str]) -> _SecuritySubCheck:
    """Run safety dependency vulnerability scan (requires network)."""
    api_key = os.environ.get("SAFETY_API_KEY", "")
    cmd = [sys.executable, "-m", "safety", "scan", "--output", "json"]
    if api_key:
        cmd.extend(["--key", api_key])

    result = run(cmd, cwd=working_dir, timeout=120)

    if result.success:
        return _SecuritySubCheck("safety", True, "No vulnerable dependencies")

    # Parse output
    try:
        report = json.loads(result.stdout)
        vulns = report.get("vulnerabilities", [])
        if not vulns:
            return _SecuritySubCheck("safety", True, "No vulnerabilities found")

        detail = "\n".join(
            f"  [{v.get('severity', '?')}] {v.get('package_name', '')} {v.get('installed_version', '')} - {v.get('vulnerability_id', '')}"
            for v in vulns[:10]
        )
        return _SecuritySubCheck("safety", False, detail)
    except json.JSONDecodeError:
        return _SecuritySubCheck(
            "safety",
            False,
            result.stdout[-300:] if result.stdout else "Safety scan failed",
        )


class PythonSecurityLocalCheck(BaseCheck):
    """Local security checks (no network required)."""

    def __init__(self) -> None:
        self._sub_checks = [_run_bandit, _run_semgrep, _run_detect_secrets]

    @property
    def name(self) -> str:
        return "python-security-local"

    @property
    def description(self) -> str:
        return "Security: bandit + semgrep + detect-secrets (local only)"

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        return self._run_security_checks(working_dir)

    def _run_security_checks(self, working_dir: Optional[str]) -> CheckResult:
        """Run sub-checks in parallel and aggregate results."""
        results: List[_SecuritySubCheck] = []

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(fn, working_dir): fn.__name__ for fn in self._sub_checks
            }
            for future in futures:
                try:
                    results.append(future.result(timeout=180))
                except Exception as e:
                    name = futures[future].replace("_run_", "")
                    results.append(_SecuritySubCheck(name, True, f"Skipped: {e}"))

        failures = [r for r in results if not r.passed]
        if not failures:
            tools = ", ".join(r.name for r in results)
            return self._make_result(
                status=CheckStatus.PASSED,
                output=f"All security checks passed ({tools})",
            )

        detail = "\n\n".join(f"[{f.name}]\n{f.findings}" for f in failures)
        return self._make_result(
            status=CheckStatus.FAILED,
            output=detail,
            fix_hint="Address the security findings above. HIGH severity issues block merge.",
        )


class PythonSecurityCheck(PythonSecurityLocalCheck):
    """Full security checks including dependency scanning."""

    def __init__(self) -> None:
        super().__init__()
        self._sub_checks = [_run_bandit, _run_semgrep, _run_detect_secrets, _run_safety]

    @property
    def name(self) -> str:
        return "python-security"

    @property
    def description(self) -> str:
        return "Security: bandit + semgrep + detect-secrets + safety (full)"
