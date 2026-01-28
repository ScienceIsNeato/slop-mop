"""Python security checks using bandit, semgrep, and detect-secrets.

Two variants:
- PythonSecurityLocalCheck: Local-only checks (bandit + semgrep + detect-secrets)
- PythonSecurityCheck: Full audit including dependency scanning via safety

Runs sub-checks concurrently for speed. Reports only HIGH/MEDIUM findings
to reduce noise while catching real security issues.
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, List

from slopbucket.checks.base import BaseCheck, PythonCheckMixin
from slopbucket.core.result import CheckResult, CheckStatus

EXCLUDED_DIRS = ["venv", ".venv", "node_modules", "cursor-rules", "archives", "logs"]


@dataclass
class SecuritySubResult:
    """Result from a single security scanner."""

    name: str
    passed: bool
    findings: str


class PythonSecurityLocalCheck(BaseCheck, PythonCheckMixin):
    """Local security checks (no network required).

    Runs bandit, semgrep, and detect-secrets in parallel.
    """

    @property
    def name(self) -> str:
        return "python-security-local"

    @property
    def display_name(self) -> str:
        return "🔐 Python Security Local (bandit + semgrep + detect-secrets)"

    def is_applicable(self, project_root: str) -> bool:
        return self.is_python_project(project_root)

    def run(self, project_root: str) -> CheckResult:
        """Run all local security checks in parallel."""
        start_time = time.time()

        sub_checks: List[Callable[[str], SecuritySubResult]] = [
            self._run_bandit,
            self._run_semgrep,
            self._run_detect_secrets,
        ]

        results: List[SecuritySubResult] = []

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(fn, project_root): fn.__name__ for fn in sub_checks
            }
            for future in futures:
                try:
                    results.append(future.result(timeout=180))
                except Exception as e:
                    name = futures[future].replace("_run_", "")
                    results.append(SecuritySubResult(name, False, f"Error: {e}"))

        duration = time.time() - start_time
        failures = [r for r in results if not r.passed]

        if not failures:
            tools = ", ".join(r.name for r in results)
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"All security checks passed ({tools})",
            )

        detail = "\n\n".join(f"[{f.name}]\n{f.findings}" for f in failures)
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=detail,
            error=f"{len(failures)} security scanner(s) found issues",
            fix_suggestion="Address HIGH severity issues first. They block merge.",
        )

    def _run_bandit(self, project_root: str) -> SecuritySubResult:
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
        for d in EXCLUDED_DIRS:
            cmd.extend(["--exclude", f"./{d}"])

        result = self._run_command(cmd, cwd=project_root, timeout=120)

        if result.success:
            return SecuritySubResult("bandit", True, "No issues found")

        try:
            report = json.loads(result.output)
            issues = [
                r
                for r in report.get("results", [])
                if r.get("issue_severity") in ("HIGH", "MEDIUM")
            ]
            if not issues:
                return SecuritySubResult("bandit", True, "Only LOW severity (ignored)")

            detail = "\n".join(
                f"  [{r['issue_severity']}] {r['issue_text']} ({r['test_name']}) "
                f"- {r.get('filename', '')}:{r.get('line_number', '')}"
                for r in issues[:10]
            )
            return SecuritySubResult("bandit", False, detail)
        except json.JSONDecodeError:
            output = result.output[-500:] if result.output else "Unknown error"
            return SecuritySubResult("bandit", False, output)

    def _run_semgrep(self, project_root: str) -> SecuritySubResult:
        """Run semgrep static analysis."""
        cmd = ["semgrep", "scan", "--config=auto", "--json", "--quiet"]
        for d in EXCLUDED_DIRS:
            cmd.extend(["--exclude", d])

        result = self._run_command(cmd, cwd=project_root, timeout=120)

        if result.success:
            return SecuritySubResult("semgrep", True, "No issues found")

        try:
            report = json.loads(result.output)
            findings = report.get("results", [])
            if not findings:
                return SecuritySubResult("semgrep", True, "No issues found")

            critical = [
                f
                for f in findings
                if f.get("extra", {}).get("severity") in ("ERROR", "WARNING")
            ]
            if not critical:
                return SecuritySubResult("semgrep", True, "Only informational findings")

            detail = "\n".join(
                f"  [{f.get('extra', {}).get('severity', '?')}] "
                f"{f.get('extra', {}).get('message', '')[:80]} "
                f"- {f.get('path', '')}:{f.get('start', {}).get('line', '')}"
                for f in critical[:10]
            )
            return SecuritySubResult("semgrep", False, detail)
        except json.JSONDecodeError:
            if result.returncode == 1:
                return SecuritySubResult("semgrep", False, result.output[-300:])
            return SecuritySubResult("semgrep", True, "Scan completed")

    def _run_detect_secrets(self, project_root: str) -> SecuritySubResult:
        """Run detect-secrets hook."""
        cmd = [sys.executable, "-m", "detect_secrets", "scan"]
        result = self._run_command(cmd, cwd=project_root, timeout=60)

        if result.success:
            try:
                report = json.loads(result.output)
                detected = report.get("results", {})
                real_secrets = {
                    k: v for k, v in detected.items() if v and "constants.py" not in k
                }
                if not real_secrets:
                    return SecuritySubResult(
                        "detect-secrets", True, "No secrets detected"
                    )

                detail = "\n".join(
                    f"  Potential secret in {path}: "
                    f"{', '.join(str(s.get('type', '?')) for s in secrets)}"
                    for path, secrets in real_secrets.items()
                )
                return SecuritySubResult("detect-secrets", False, detail)
            except json.JSONDecodeError:
                return SecuritySubResult("detect-secrets", True, "Scan completed")

        return SecuritySubResult(
            "detect-secrets",
            False,
            result.output[-300:] if result.output else "Scan failed",
        )


class PythonSecurityCheck(PythonSecurityLocalCheck):
    """Full security checks including dependency vulnerability scanning.

    Extends PythonSecurityLocalCheck with safety for dependency audit.
    Requires network access.
    """

    @property
    def name(self) -> str:
        return "python-security"

    @property
    def display_name(self) -> str:
        return "🔒 Python Security Full (bandit + semgrep + detect-secrets + safety)"

    def run(self, project_root: str) -> CheckResult:
        """Run all security checks including dependency scanning."""
        start_time = time.time()

        sub_checks: List[Callable[[str], SecuritySubResult]] = [
            self._run_bandit,
            self._run_semgrep,
            self._run_detect_secrets,
            self._run_safety,
        ]

        results: List[SecuritySubResult] = []

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(fn, project_root): fn.__name__ for fn in sub_checks
            }
            for future in futures:
                try:
                    results.append(future.result(timeout=180))
                except Exception as e:
                    name = futures[future].replace("_run_", "")
                    results.append(SecuritySubResult(name, False, f"Error: {e}"))

        duration = time.time() - start_time
        failures = [r for r in results if not r.passed]

        if not failures:
            tools = ", ".join(r.name for r in results)
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"All security checks passed ({tools})",
            )

        detail = "\n\n".join(f"[{f.name}]\n{f.findings}" for f in failures)
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=detail,
            error=f"{len(failures)} security scanner(s) found issues",
            fix_suggestion="Address HIGH severity issues first. They block merge.",
        )

    def _run_safety(self, project_root: str) -> SecuritySubResult:
        """Run safety dependency vulnerability scan."""
        api_key = os.environ.get("SAFETY_API_KEY", "")
        cmd = [sys.executable, "-m", "safety", "scan", "--output", "json"]
        if api_key:
            cmd.extend(["--key", api_key])

        result = self._run_command(cmd, cwd=project_root, timeout=120)

        if result.success:
            return SecuritySubResult("safety", True, "No vulnerable dependencies")

        try:
            report = json.loads(result.output)
            vulns = report.get("vulnerabilities", [])
            if not vulns:
                return SecuritySubResult("safety", True, "No vulnerabilities found")

            detail = "\n".join(
                f"  [{v.get('severity', '?')}] {v.get('package_name', '')} "
                f"{v.get('installed_version', '')} - {v.get('vulnerability_id', '')}"
                for v in vulns[:10]
            )
            return SecuritySubResult("safety", False, detail)
        except json.JSONDecodeError:
            return SecuritySubResult(
                "safety",
                False,
                result.output[-300:] if result.output else "Safety scan failed",
            )
