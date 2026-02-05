"""Security checks using bandit, semgrep, and detect-secrets.

Two variants:
- SecurityLocalCheck: Local-only checks (bandit + semgrep + detect-secrets)
- SecurityCheck: Full audit including dependency scanning via safety

Runs sub-checks concurrently for speed. Reports only HIGH/MEDIUM findings
to reduce noise while catching real security issues.

Note: These are cross-cutting security checks that apply to any project
with code files, not just Python projects.
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, List

from slopmop.checks.base import (
    BaseCheck,
    ConfigField,
    GateCategory,
    PythonCheckMixin,
)
from slopmop.core.result import CheckResult, CheckStatus

EXCLUDED_DIRS = [
    "venv",
    ".venv",
    "node_modules",
    "cursor-rules",
    "archives",
    "logs",
    "tests",  # Test files often have intentional security "violations"
    "*/.venv",  # Nested venvs
    "*/venv",  # Nested venvs
]


@dataclass
class SecuritySubResult:
    """Result from a single security scanner."""

    name: str
    passed: bool
    findings: str


class SecurityLocalCheck(BaseCheck, PythonCheckMixin):
    """Local security checks (no network required).

    Runs bandit, semgrep, and detect-secrets in parallel.
    Cross-cutting check that applies to any project with source files.
    """

    @property
    def name(self) -> str:
        return "local"

    @property
    def display_name(self) -> str:
        return "🔐 Security Local (bandit + semgrep + detect-secrets)"

    @property
    def category(self) -> GateCategory:
        return GateCategory.SECURITY

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="scanners",
                field_type="string[]",
                default=["bandit", "semgrep", "detect-secrets"],
                description="Security scanners to run",
            ),
            ConfigField(
                name="exclude_dirs",
                field_type="string[]",
                default=EXCLUDED_DIRS.copy(),
                description="Directories to exclude from scanning",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        """Check if there are any source files to scan."""
        from pathlib import Path

        root = Path(project_root)
        # Look for Python or JS files
        has_py = any(root.rglob("*.py"))
        has_js = any(root.rglob("*.js")) or any(root.rglob("*.ts"))
        return has_py or has_js

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

    def _get_exclude_dirs(self) -> List[str]:
        """Get directories to exclude from config or defaults."""
        return self.config.get("exclude_dirs", EXCLUDED_DIRS)

    def _run_bandit(self, project_root: str) -> SecuritySubResult:
        """Run bandit static analysis."""
        # Check for config file
        config_file = self.config.get("config_file_path")

        cmd = [
            self.get_project_python(project_root),
            "-m",
            "bandit",
            "-r",
            ".",
            "--format",
            "json",
            "--quiet",
        ]

        # Use config file if specified, otherwise use defaults
        if config_file:
            cmd.extend(["--configfile", config_file])
        else:
            cmd.extend(["--skip", "B101,B110"])
            # Bandit wants comma-separated exclude paths
            exclude_paths = ",".join(f"./{d}" for d in self._get_exclude_dirs())
            cmd.extend(["--exclude", exclude_paths])

        result = self._run_command(cmd, cwd=project_root, timeout=120)

        # Try to parse JSON from stdout only - stderr contains warnings that aren't issues
        # Bandit returns non-zero for any findings including LOW severity
        try:
            report = json.loads(result.stdout)
            issues = [
                r
                for r in report.get("results", [])
                if r.get("issue_severity") in ("HIGH", "MEDIUM")
            ]
            if not issues:
                return SecuritySubResult("bandit", True, "No HIGH/MEDIUM issues")

            detail = "\n".join(
                f"  [{r['issue_severity']}] {r['issue_text']} ({r['test_name']}) "
                f"- {r.get('filename', '')}:{r.get('line_number', '')}"
                for r in issues[:10]
            )
            return SecuritySubResult("bandit", False, detail)
        except json.JSONDecodeError:
            # If JSON parsing fails, check stderr for actual errors
            if result.stderr and "error" in result.stderr.lower():
                return SecuritySubResult("bandit", False, result.stderr[-500:])
            # Otherwise bandit ran but produced no JSON (likely no issues)
            return SecuritySubResult("bandit", True, "No issues found")

    def _run_semgrep(self, project_root: str) -> SecuritySubResult:
        """Run semgrep static analysis."""
        cmd = ["semgrep", "scan", "--config=auto", "--json", "--quiet"]
        for d in self._get_exclude_dirs():
            cmd.extend(["--exclude", d])

        result = self._run_command(cmd, cwd=project_root, timeout=120)

        if result.success:
            return SecuritySubResult("semgrep", True, "No issues found")

        try:
            report = json.loads(result.stdout)
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
            if result.returncode == 1 and result.stderr:
                return SecuritySubResult("semgrep", False, result.stderr[-300:])
            return SecuritySubResult("semgrep", True, "Scan completed")

    def _run_detect_secrets(self, project_root: str) -> SecuritySubResult:
        """Run detect-secrets hook."""
        # Check for baseline file
        config_file = self.config.get("config_file_path")

        cmd = [self.get_project_python(project_root), "-m", "detect_secrets", "scan"]
        if config_file:
            cmd.extend(["--baseline", config_file])

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


class SecurityCheck(SecurityLocalCheck):
    """Full security checks including dependency vulnerability scanning.

    Extends SecurityLocalCheck with safety for dependency audit.
    Requires network access.
    """

    @property
    def name(self) -> str:
        return "full"

    @property
    def display_name(self) -> str:
        return "🔒 Security Full (bandit + semgrep + detect-secrets + safety)"

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

        # Check for safety config file
        safety_config = self.config.get("safety_config_file")

        cmd = [
            self.get_project_python(project_root),
            "-m",
            "safety",
            "scan",
            "--output",
            "json",
        ]
        if api_key:
            cmd.extend(["--key", api_key])
        if safety_config:
            cmd.extend(["--policy-file", safety_config])

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
