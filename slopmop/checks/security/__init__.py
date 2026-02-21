"""Security checks using bandit, semgrep, and detect-secrets.

Two variants:
- SecurityLocalCheck: Local-only checks (bandit + semgrep + detect-secrets)
- SecurityCheck: Full audit including dependency scanning via pip-audit

Runs sub-checks concurrently for speed. Reports only HIGH/MEDIUM findings
to reduce noise while catching real security issues.

Note: These are cross-cutting security checks that apply to any project
with code files, not just Python projects.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from slopmop.checks.base import (
    BaseCheck,
    ConfigField,
    Flaw,
    GateCategory,
    PythonCheckMixin,
)
from slopmop.constants import NO_ISSUES_FOUND
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
    """Local security scanning (no network required).

    Wraps bandit, semgrep, and detect-secrets in parallel.
    Reports only HIGH/MEDIUM severity findings to reduce noise
    while catching real security issues.

    Profiles: commit, pr, quick

    Configuration:
      scanners: ["bandit", "semgrep", "detect-secrets"] — all three
          run in parallel for speed. Each covers different classes
          of vulnerability.
      exclude_dirs: venv, node_modules, tests, etc. — test files
          often have intentional security "violations" (hardcoded
          test credentials, etc.).

    Common failures:
      bandit HIGH/MEDIUM: Fix the flagged code pattern. Common
          issues: hardcoded passwords, SQL injection, unsafe eval.
      semgrep findings: Follow the rule description in the output.
      detect-secrets: Rotate the leaked secret, then add to
          .secrets.baseline if it's a false positive.

    Re-validate:
      ./scripts/sm validate myopia:security-scan --verbose
    """

    @property
    def name(self) -> str:
        return "security-scan"

    @property
    def display_name(self) -> str:
        return "🔐 Security Scan (code analysis)"

    @property
    def category(self) -> GateCategory:
        return GateCategory.MYOPIA

    @property
    def flaw(self) -> Flaw:
        return Flaw.MYOPIA

    @property
    def superseded_by(self) -> Optional[str]:
        return "myopia:security-audit"

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
            ConfigField(
                name="bandit_config_file",
                field_type="string",
                default=None,
                description=(
                    "Path to bandit config file (e.g. .bandit, pyproject.toml). "
                    "Separate from the standard config_file_path which is used "
                    "by detect-secrets (.secrets.baseline)"
                ),
                required=False,
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

    def skip_reason(self, project_root: str) -> str:
        """Return reason for skipping - no source files to scan."""
        return "No Python, JavaScript, or TypeScript files found to scan for security issues"

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
        # Check for bandit-specific config file (e.g., .bandit, pyproject.toml with [tool.bandit])
        # Note: config_file_path in user config may be for detect-secrets (.secrets.baseline),
        # not bandit. Only use it for bandit if it's a known bandit config format.
        config_file = self.config.get("bandit_config_file")

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

        # Always apply exclude paths
        exclude_paths = ",".join(f"./{d}" for d in self._get_exclude_dirs())
        cmd.extend(["--exclude", exclude_paths])

        # Use config file if specified for bandit, otherwise use skip defaults
        if config_file and Path(project_root, config_file).exists():
            cmd.extend(["--configfile", config_file])
        else:
            # B101 = assert usage, B110 = try-except-pass (common patterns)
            cmd.extend(["--skip", "B101,B110"])

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
            return SecuritySubResult("bandit", True, NO_ISSUES_FOUND)

    def _run_semgrep(self, project_root: str) -> SecuritySubResult:
        """Run semgrep static analysis."""
        cmd = ["semgrep", "scan", "--config=auto", "--json", "--quiet"]
        for d in self._get_exclude_dirs():
            cmd.extend(["--exclude", d])

        result = self._run_command(cmd, cwd=project_root, timeout=120)

        if result.success:
            return SecuritySubResult("semgrep", True, NO_ISSUES_FOUND)

        try:
            report = json.loads(result.stdout)
            findings = report.get("results", [])
            if not findings:
                return SecuritySubResult("semgrep", True, NO_ISSUES_FOUND)

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

    @staticmethod
    def _only_timestamp_changed(old: str, new: str) -> bool:
        """Return True if the only difference is the generated_at value."""
        old_lines = old.splitlines()
        new_lines = new.splitlines()
        if len(old_lines) != len(new_lines):
            return False
        diffs = [
            (a, b) for a, b in zip(old_lines, new_lines) if a != b
        ]
        if len(diffs) != 1:
            return False
        old_line, new_line = diffs[0]
        return '"generated_at"' in old_line and '"generated_at"' in new_line

    def _run_detect_secrets(self, project_root: str) -> SecuritySubResult:
        """Run detect-secrets hook."""
        # Check for baseline file
        config_file = self.config.get("config_file_path")

        cmd = [self.get_project_python(project_root), "-m", "detect_secrets", "scan"]

        # detect-secrets scan --baseline MUTATES the file in-place (updates
        # generated_at timestamp) even when no secrets change.  Save the
        # original content so we can restore it if only the timestamp changed.
        baseline_path = None
        original_content = None
        if config_file:
            cmd.extend(["--baseline", config_file])
            baseline_path = Path(project_root) / config_file
            if baseline_path.exists():
                original_content = baseline_path.read_text()

        result = self._run_command(cmd, cwd=project_root, timeout=60)

        # Restore baseline if only the generated_at timestamp changed
        if original_content is not None and baseline_path is not None and baseline_path.exists():
            new_content = baseline_path.read_text()
            if self._only_timestamp_changed(original_content, new_content):
                baseline_path.write_text(original_content)

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
    """Full security audit including dependency scanning.

    Extends security:local with pip-audit for dependency
    vulnerability checking. Requires network access to query
    the OSV vulnerability database.

    Profiles: pr

    Configuration:
      Same as security:local, plus pip-audit runs automatically.
      pip-audit is fast (~1s) and uses the OSV database.

    Common failures:
      Vulnerable dependency: Update the package to a fixed version
          shown in the output. If no fix exists, evaluate risk and
          consider alternatives.
      pip-audit not available: pip install pip-audit

    Re-validate:
      ./scripts/sm validate myopia:security-audit --verbose
    """

    @property
    def name(self) -> str:
        return "security-audit"

    @property
    def display_name(self) -> str:
        return "🔒 Security Audit (code + dependencies)"

    def run(self, project_root: str) -> CheckResult:
        """Run all security checks including dependency scanning."""
        start_time = time.time()

        sub_checks: List[Callable[[str], SecuritySubResult]] = [
            self._run_bandit,
            self._run_semgrep,
            self._run_detect_secrets,
            self._run_pip_audit,
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

    def _run_pip_audit(self, project_root: str) -> SecuritySubResult:
        """Run pip-audit dependency vulnerability scan.

        pip-audit is fast (~1s), offline-capable, and uses the OSV database.
        Replaces safety which hangs on `safety scan` with no API key.
        """
        cmd = [
            self.get_project_python(project_root),
            "-m",
            "pip_audit",
            "--format",
            "json",
        ]

        result = self._run_command(cmd, cwd=project_root, timeout=30)

        try:
            report = json.loads(result.stdout)
            deps = report.get("dependencies", [])
            vulnerable = [d for d in deps if d.get("vulns")]
            if not vulnerable:
                return SecuritySubResult(
                    "pip-audit", True, "No vulnerable dependencies"
                )

            detail = "\n".join(
                f"  {d['name']} {d.get('version', '?')}: "
                + ", ".join(
                    f"{v.get('id', '?')} ({', '.join(map(str, v.get('fix_versions', ['no fix'])))})"
                    for v in d.get("vulns", [])[:3]
                )
                for d in vulnerable[:10]
            )
            return SecuritySubResult("pip-audit", False, detail)
        except json.JSONDecodeError:
            if result.success:
                return SecuritySubResult("pip-audit", True, "No vulnerabilities found")
            return SecuritySubResult(
                "pip-audit",
                False,
                result.output[-300:] if result.output else "pip-audit scan failed",
            )
