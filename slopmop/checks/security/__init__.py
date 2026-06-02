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
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, cast

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    GateLevel,
    ToolContext,
)
from slopmop.checks.mixins import PythonCheckMixin
from slopmop.checks.security._detect_secrets import DetectSecretsMixin
from slopmop.constants import NO_ISSUES_FOUND
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel

_SCANNER_NOT_INSTALLED = "{name} (not installed)"

# A scanner that fails to even start (its Python module isn't importable in the
# interpreter we shell out to) is a tooling/environment problem, NOT a security
# finding. Reporting "No module named detect_secrets" as SLOP DETECTED tells a
# user they have a leaked secret when they have a broken install. These markers
# identify a process that never ran a scan.
_SCANNER_STARTUP_FAILURE_MARKERS = (
    "No module named",
    "ModuleNotFoundError",
)


def _scanner_failed_to_start(output: str) -> bool:
    """Return True when scanner output shows it never ran (import/startup error)."""
    return any(marker in output for marker in _SCANNER_STARTUP_FAILURE_MARKERS)


# Canonical remediations for common bandit test IDs.  These are the fixes
# bandit's own docs prescribe — we're not guessing, we're relaying the
# tool's documented resolution.  Rules not in this map get no
# fix_strategy (agent decides, same as today).  Ordered by real-world
# frequency: YAML/subprocess/pickle issues dominate bandit findings in
# practice.
_BANDIT_FIX_STRATEGIES: dict[str, str] = {
    "B506": "Replace yaml.load() with yaml.safe_load() — the unsafe "
    "loader executes arbitrary Python from YAML input.",
    "B301": "Replace pickle.loads() with json.loads() if the payload is "
    "structured data. If pickle is required, validate the input "
    "source is trusted before deserialising.",
    "B602": "Remove shell=True. Pass the command as a list "
    "(['prog', 'arg']) so subprocess invokes the binary "
    "directly without a shell.",
    "B603": "Ensure the command list contains no user-controlled "
    "elements. If arguments come from user input, validate "
    "or escape them before the subprocess call.",
    "B605": "Replace os.system() with subprocess.run([...]) using a "
    "list argument, not a shell string.",
    "B608": "Parameterise the SQL query. Use the DB driver's "
    "placeholder syntax (? or %s) with a params tuple — "
    "never build query strings by concatenation.",
    "B104": "Bind to a specific interface (127.0.0.1 for local-only) "
    "instead of 0.0.0.0, unless public exposure is intended.",
    "B108": "Use tempfile.mkstemp() or a TemporaryDirectory context "
    "manager instead of a hardcoded /tmp path.",
    "B501": "Remove verify=False. If the certificate is self-signed, "
    "pass a CA bundle path to verify= instead.",
    "B105": "Move the hardcoded credential into an environment "
    "variable or secrets manager. Read it at runtime.",
    "B106": "Move the hardcoded password into an environment "
    "variable. Read it at runtime via os.environ.",
}

EXCLUDED_DIRS = [
    "node_modules",
    "venv",
    ".venv",
    "cursor-rules",
    "archives",
    "logs",
    "tests",  # Test files often have intentional security "violations"
    "*/.venv",  # Nested venvs
    "*/venv",  # Nested venvs
    ".*",  # all dot-directories
    "*/.*",  # dot-directories at any depth
]


@dataclass
class SecuritySubResult:
    """Result from a single security scanner."""

    name: str
    passed: bool
    findings: str
    sarif_findings: List[Finding] = field(
        default_factory=lambda: cast(List[Finding], [])
    )
    warned: bool = False


class SecurityLocalCheck(BaseCheck, PythonCheckMixin, DetectSecretsMixin):
    """Local security scanning (no network required).

    Wraps bandit, semgrep, and detect-secrets in parallel.
    Reports only HIGH/MEDIUM severity findings to reduce noise
    while catching real security issues.

    Level: scour

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

    Re-check:
      sm swab -g myopia:vulnerability-blindness.py --verbose
    """

    tool_context = ToolContext.SM_TOOL
    required_tools = ["bandit", "detect-secrets"]
    role = CheckRole.FOUNDATION

    @property
    def name(self) -> str:
        return "vulnerability-blindness.py"

    @property
    def display_name(self) -> str:
        return "🔐 Security Scan (bandit, semgrep, detect-secrets)"

    @property
    def gate_description(self) -> str:
        return "🔐 bandit + semgrep + detect-secrets"

    @property
    def category(self) -> GateCategory:
        return GateCategory.MYOPIA

    @property
    def flaw(self) -> Flaw:
        return Flaw.MYOPIA

    @property
    def superseded_by(self) -> Optional[str]:
        return "myopia:dependency-risk.py"

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="scanners",
                field_type="string[]",
                default=["bandit", "semgrep", "detect-secrets"],
                description="Security scanners to run",
                permissiveness="more_is_stricter",
            ),
            ConfigField(
                name="exclude_dirs",
                field_type="string[]",
                default=EXCLUDED_DIRS.copy(),
                description="Directories to exclude from scanning",
                permissiveness="fewer_is_stricter",
            ),
            ConfigField(
                name="config_file_path",
                field_type="string",
                default=None,
                description=(
                    "Path to detect-secrets baseline file (typically "
                    ".secrets.baseline)"
                ),
                required=False,
            ),
            ConfigField(
                name="bandit_config_file",
                field_type="string",
                default=None,
                description=(
                    "Path to bandit config file (e.g. .bandit, pyproject.toml). "
                    "Separate from config_file_path which is used by "
                    "detect-secrets (.secrets.baseline)"
                ),
                required=False,
            ),
            ConfigField(
                name="pip_audit_ignore_vulns",
                field_type="string[]",
                default=[],
                description=(
                    "Vulnerability IDs to ignore in pip-audit "
                    "(GHSA-xxxx, CVE-xxxx, PYSEC-xxxx). Use for "
                    "known vulns with no patched version available."
                ),
                permissiveness="fewer_is_stricter",
            ),
        ]

    def init_config(self, project_root: str) -> Dict[str, Any]:
        """Discover native config files this gate knows how to use.

        Security checks own their own lookup rules because they know which
        files are meaningful to each underlying scanner.
        """
        root = Path(project_root)
        overrides: Dict[str, Any] = {}

        baseline_path = root / ".secrets.baseline"
        if baseline_path.exists():
            overrides["config_file_path"] = baseline_path.name

        bandit_config = self._discover_bandit_config(root)
        if bandit_config is not None:
            overrides["bandit_config_file"] = bandit_config

        return overrides

    def _discover_bandit_config(self, root: Path) -> Optional[str]:
        """Return the most likely bandit config file for this repo."""
        direct_candidates = [".bandit", "bandit.yaml", "bandit.yml"]
        for name in direct_candidates:
            candidate = root / name
            if candidate.exists():
                return name

        pyproject = root / "pyproject.toml"
        if pyproject.exists() and "[tool.bandit]" in pyproject.read_text(
            encoding="utf-8", errors="ignore"
        ):
            return "pyproject.toml"

        for name, marker in [("setup.cfg", "[bandit]"), ("tox.ini", "[bandit]")]:
            candidate = root / name
            if candidate.exists() and marker in candidate.read_text(
                encoding="utf-8", errors="ignore"
            ):
                return name

        return None

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

    @staticmethod
    def _is_scanner_available(name: str, importable: dict[str, str]) -> bool:
        """Check if a scanner tool is available on this system.

        For Python-based scanners (bandit, detect-secrets), checks
        importability via ``find_spec`` (not ``import_module``).
        ``import_module("bandit")`` pulls in stevedore, which enumerates
        every entry-point plugin and logs WARNING for each failed load —
        "Could not load 'sarif'" on every run.  ``find_spec`` probes the
        import machinery without executing the target package.
        """
        if name in importable:
            try:
                import importlib.util

                return importlib.util.find_spec(importable[name]) is not None
            except (ImportError, ModuleNotFoundError, ValueError):
                return False
        # External binary (semgrep, etc.)
        return shutil.which(name) is not None

    def run(self, project_root: str) -> CheckResult:
        """Run configured security checks in parallel.

        Respects the ``scanners`` config to determine which tools to run.
        Scanners that aren't installed are skipped with a warning rather
        than counted as failures — this allows graceful degradation when
        heavy tools like semgrep aren't available locally.
        """
        start_time = time.time()

        scanner_map: dict[str, Callable[[str], SecuritySubResult]] = {
            "bandit": self._run_bandit,
            "semgrep": self._run_semgrep,
            "detect-secrets": self._run_detect_secrets,
        }

        configured = self.config.get("scanners", list(scanner_map.keys()))
        # Filter to only configured scanners that we know about
        sub_checks: List[Callable[[str], SecuritySubResult]] = []
        skipped: List[str] = []
        # Map scanner names to their Python module for importability check
        _importable = {
            "bandit": "bandit",
            "detect-secrets": "detect_secrets",  # pragma: allowlist secret
        }
        for name in configured:
            if name not in scanner_map:
                continue
            available = self._is_scanner_available(name, _importable)
            if available:
                sub_checks.append(scanner_map[name])
            else:
                skipped.append(_SCANNER_NOT_INSTALLED.format(name=name))

        if not sub_checks:
            duration = time.time() - start_time
            skip_msg = ", ".join(skipped) if skipped else "none configured"
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=duration,
                output=f"No security scanners available ({skip_msg})",
            )

        results: List[SecuritySubResult] = []

        with ThreadPoolExecutor(max_workers=len(sub_checks)) as executor:
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
            skip_note = f" [skipped: {', '.join(skipped)}]" if skipped else ""
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"All security checks passed ({tools}){skip_note}",
            )

        detail = "\n\n".join(f"[{f.name}]\n{f.findings}" for f in failures)
        # Flatten per-scanner structured findings; fall back to one
        # aggregate per scanner if it didn't produce any
        all_findings: List[Finding] = []
        for f in failures:
            if f.sarif_findings:
                all_findings.extend(f.sarif_findings)
            else:
                all_findings.append(
                    Finding(
                        message=f"{f.name} found issues",
                        level=FindingLevel.ERROR,
                    )
                )
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=detail,
            error=f"{len(failures)} security scanner(s) found issues",
            fix_suggestion=(
                "Each finding above has a rule-specific fix where known. "
                "Bandit's HIGH severity findings are real vulnerabilities "
                "\u2014 fix those first. Verify with: " + self.verify_command
            ),
            findings=all_findings,
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
            sys.executable,
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
            # bandit has full file:line — emit per-issue Findings.
            # test_id maps to a documented canonical remediation when
            # we have one; otherwise fix_strategy stays None (agent
            # already sees issue_text which names the vulnerable call).
            sarif: List[Finding] = []
            for r in issues:
                line_no = r.get("line_number")
                test_id = r.get("test_id")
                sarif.append(
                    Finding(
                        message=f"[{r['issue_severity']}] {r['issue_text']}",
                        level=FindingLevel.ERROR,
                        file=r.get("filename") or None,
                        line=line_no if isinstance(line_no, int) else None,
                        rule_id=test_id,
                        fix_strategy=_BANDIT_FIX_STRATEGIES.get(test_id or ""),
                    )
                )
            return SecuritySubResult("bandit", False, detail, sarif)
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
            # semgrep has full file:line — emit per-issue Findings
            sarif: List[Finding] = []
            for f in critical:
                line_no = f.get("start", {}).get("line")
                sarif.append(
                    Finding(
                        message=f.get("extra", {}).get("message", "semgrep finding"),
                        level=FindingLevel.ERROR,
                        file=f.get("path") or None,
                        line=line_no if isinstance(line_no, int) else None,
                        rule_id=f.get("check_id"),
                    )
                )
            return SecuritySubResult("semgrep", False, detail, sarif)
        except json.JSONDecodeError:
            if result.returncode == 1 and result.stderr:
                return SecuritySubResult("semgrep", False, result.stderr[-300:])
            return SecuritySubResult("semgrep", True, "Scan completed")


class SecurityCheck(SecurityLocalCheck):
    """Full security audit including dependency scanning.

    Extends security:local with pip-audit for dependency
    vulnerability checking. Requires network access to query
    the OSV vulnerability database.

    Level: scour (full audit with network access)

    Configuration:
      Same as security:local, plus pip-audit runs automatically.
      pip-audit is fast (~1s) and uses the OSV database.

    Common failures:
      Vulnerable dependency: Update the package to a fixed version
          shown in the output. If no fix exists, evaluate risk and
          consider alternatives.
      pip-audit not available: pip install pip-audit

    Re-check:
      sm scour -g myopia:dependency-risk.py --verbose
    """

    level = GateLevel.SCOUR
    role = CheckRole.FOUNDATION

    @property
    def name(self) -> str:
        return "dependency-risk.py"

    @property
    def display_name(self) -> str:
        return "🔒 Security Audit (full scan + pip-audit)"

    @property
    def gate_description(self) -> str:
        return "🔒 Full security audit (code + pip-audit)"

    @property
    def superseded_by(self) -> Optional[str]:
        """Full security audit is the superseding gate, not the superseded one."""
        return None

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
        warnings = [r for r in results if r.warned and r.passed]

        if not failures and not warnings:
            tools = ", ".join(r.name for r in results)
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"All security checks passed ({tools})",
            )

        if warnings and not failures:
            return self._warnings_only_result(warnings, duration)

        return self._failures_result(failures, warnings, duration)

    def _warnings_only_result(
        self,
        warnings: List["SecuritySubResult"],
        duration: float,
    ) -> CheckResult:
        """Build a WARNED result when no scanners failed outright."""
        detail = "\n\n".join(f"[{w.name}]\n{w.findings}" for w in warnings)
        warning_findings = self._collect_findings(
            warnings, fallback_level=FindingLevel.WARNING
        )
        return self._create_result(
            status=CheckStatus.WARNED,
            duration=duration,
            output=detail,
            error=(
                f"{len(warnings)} security scanner(s) reported " "non-blocking risk"
            ),
            fix_suggestion=(
                "No patched versions are currently available for the "
                "advisories above. Track upstream releases, reassess "
                "risk periodically, and only use pip_audit_ignore_vulns "
                "when you have documented acceptance criteria."
            ),
            findings=warning_findings,
        )

    def _failures_result(
        self,
        failures: List["SecuritySubResult"],
        warnings: List["SecuritySubResult"],
        duration: float,
    ) -> CheckResult:
        """Build a FAILED result, including any advisory warnings."""
        detail_parts = [f"[{f.name}]\n{f.findings}" for f in failures]
        all_findings = self._collect_findings(
            failures, fallback_level=FindingLevel.ERROR
        )
        if warnings:
            for w in warnings:
                detail_parts.append(f"[{w.name} (advisory)]\n{w.findings}")
            all_findings.extend(
                self._collect_findings(warnings, fallback_level=FindingLevel.WARNING)
            )
        detail = "\n\n".join(detail_parts)
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=detail,
            error=f"{len(failures)} security scanner(s) found issues",
            fix_suggestion=(
                "Each finding above has a rule-specific fix where known. "
                "Bandit's HIGH severity findings are real vulnerabilities "
                "\u2014 fix those first. Verify with: " + self.verify_command
            ),
            findings=all_findings,
        )

    @staticmethod
    def _collect_findings(
        sub_results: List["SecuritySubResult"],
        fallback_level: FindingLevel,
    ) -> List[Finding]:
        """Gather SARIF findings from sub-results with a fallback level."""
        findings: List[Finding] = []
        for r in sub_results:
            if r.sarif_findings:
                findings.extend(r.sarif_findings)
            else:
                findings.append(
                    Finding(
                        message=f"{r.name} found issues",
                        level=fallback_level,
                    )
                )
        return findings

    @staticmethod
    def _has_fix_versions(vulnerability: Dict[str, Any]) -> bool:
        """Return True when pip-audit reports at least one fix version."""
        fix_versions_obj = vulnerability.get("fix_versions", [])
        if not isinstance(fix_versions_obj, list):
            return False
        fix_versions = cast(List[Any], fix_versions_obj)
        for version in fix_versions:
            if isinstance(version, str) and version.strip():
                return True
            if isinstance(version, (int, float)) and str(version).strip():
                return True
        return False

    @staticmethod
    def _format_fix_versions(vulnerability: Dict[str, Any]) -> str:
        """Format fix versions defensively for pip-audit display output."""
        raw_fix_versions_obj = vulnerability.get("fix_versions", ["no fix"])
        if not isinstance(raw_fix_versions_obj, list):
            return "no fix"
        raw_fix_versions = cast(List[Any], raw_fix_versions_obj)

        formatted: List[str] = []
        for version in raw_fix_versions:
            if isinstance(version, str):
                trimmed = version.strip()
                if trimmed:
                    formatted.append(trimmed)
            elif isinstance(version, (int, float)):
                formatted.append(str(version))

        return ", ".join(formatted) if formatted else "no fix"

    @staticmethod
    def _format_pip_audit_detail(dependencies: List[Dict[str, Any]]) -> str:
        """Render a compact, human-readable summary of vulnerable deps."""
        return "\n".join(
            f"  {dependency.get('name', '?')} {dependency.get('version', '?')}: "
            + ", ".join(
                f"{vulnerability.get('id', '?')} "
                f"({SecurityCheck._format_fix_versions(vulnerability)})"
                for vulnerability in dependency.get("vulns", [])[:3]
            )
            for dependency in dependencies[:10]
        )

    def _pip_audit_remediable_result(
        self,
        remediable: List[Dict[str, Any]],
        no_fix_versions: List[Dict[str, Any]],
    ) -> "SecuritySubResult":
        """Build a FAILED pip-audit result, appending no-fix advisory."""
        detail = self._format_pip_audit_detail(remediable)
        sarif: list[Finding] = [
            Finding(
                message=(
                    f"{len(remediable)} vulnerable dependency/dependencies "
                    "with available fix versions"
                ),
                level=FindingLevel.ERROR,
            )
        ]
        if no_fix_versions:
            no_fix_detail = self._format_pip_audit_detail(no_fix_versions)
            detail += "\n\nNo fix versions available (advisory only):\n" + no_fix_detail
            sarif.append(
                Finding(
                    message=(
                        f"{len(no_fix_versions)} vulnerable "
                        "dependency/dependencies with no published fix"
                    ),
                    level=FindingLevel.WARNING,
                )
            )
        return SecuritySubResult("pip-audit", False, detail, sarif)

    def _pip_audit_no_fix_result(
        self, no_fix_versions: List[Dict[str, Any]]
    ) -> "SecuritySubResult":
        """Build a WARNED pip-audit result when vulns have no fix versions."""
        detail = self._format_pip_audit_detail(no_fix_versions)
        sarif_warn: list[Finding] = [
            Finding(
                message=(
                    f"{len(no_fix_versions)} vulnerable dependency/dependencies "
                    "with no published fix versions"
                ),
                level=FindingLevel.WARNING,
            )
        ]
        return SecuritySubResult(
            "pip-audit",
            True,
            f"No fix versions available for the vulnerable dependencies below:\n{detail}",
            warned=True,
            sarif_findings=sarif_warn,
        )

    @staticmethod
    def _project_has_python_manifest(project_root: str) -> bool:
        """Return True when the project has any Python dependency manifest."""
        root = Path(project_root)
        return (
            (root / "pyproject.toml").exists()
            or (root / "setup.py").exists()
            or bool(SecurityCheck._find_requirements_files(project_root))
        )

    def _pip_audit_resolve_req_files(
        self, project_root: str
    ) -> "tuple[list[str], SecuritySubResult | None]":
        """Return (req_files, None) when files exist; ([], skip_result) otherwise."""
        req_files = self._find_requirements_files(project_root)
        if req_files:
            return req_files, None
        if self._project_has_python_manifest(project_root):
            return [], SecuritySubResult(
                "pip-audit",
                True,
                "No requirements.txt found; activate a virtual environment "
                "for pip-audit to scan pyproject.toml/setup.py projects — "
                "pip-audit skipped",
            )
        return [], SecuritySubResult(
            "pip-audit",
            True,
            "No Python dependency manifest found — pip-audit skipped",
        )

    def _run_pip_audit(self, project_root: str) -> SecuritySubResult:
        """Run pip-audit dependency vulnerability scan.

        pip-audit is fast (~1s), offline-capable, and uses the OSV database.
        Replaces safety which hangs on `safety scan` with no API key.

        When a project venv exists, pip-audit scans the installed environment.
        When no project venv is found, pip-audit is invoked with -r <file> for
        each requirements file found in the project.  This avoids auditing
        slop-mop's own pipx environment instead of the project's dependencies.
        If neither a venv nor any requirements files exist (e.g. a JS repo),
        the sub-check is skipped with a passing result.
        """
        from slopmop.checks.mixins import (
            PYTHON_SOURCE_PROJECT_VENV,
            PYTHON_SOURCE_VIRTUAL_ENV,
            resolve_project_python,
        )

        python, source = resolve_project_python(project_root)
        venv_path = os.environ.get("VIRTUAL_ENV", "")
        venv_is_project_local = bool(venv_path) and Path(venv_path).is_relative_to(
            Path(project_root)
        )
        has_own_env = source == PYTHON_SOURCE_PROJECT_VENV or (
            source == PYTHON_SOURCE_VIRTUAL_ENV
            and venv_is_project_local
            and self._project_has_python_manifest(project_root)
        )

        cmd = [python, "-m", "pip_audit", "--format", "json"]
        ignore_ids = self.config.get("pip_audit_ignore_vulns", [])
        for vuln_id in ignore_ids:
            cmd.extend(["--ignore-vuln", vuln_id])

        if not has_own_env:
            req_files, skip = self._pip_audit_resolve_req_files(project_root)
            if skip is not None:
                return skip
            for req_file in req_files:
                cmd.extend(["-r", req_file])

        result = self._run_command(cmd, cwd=project_root, timeout=120)

        if result.timed_out:
            return SecuritySubResult(
                "pip-audit",
                True,
                "pip-audit timed out fetching vulnerability data — skipped",
                warned=True,
                sarif_findings=[
                    Finding(
                        message="pip-audit timed out; vulnerability scan skipped",
                        level=FindingLevel.WARNING,
                    )
                ],
            )

        try:
            report = json.loads(result.stdout)
            deps = report.get("dependencies", [])
            vulnerable = [d for d in deps if d.get("vulns")]
            if not vulnerable:
                return SecuritySubResult(
                    "pip-audit", True, "No vulnerable dependencies"
                )

            remediable: List[Dict[str, Any]] = []
            no_fix_versions: List[Dict[str, Any]] = []
            for dependency in vulnerable:
                vulnerabilities = cast(
                    List[Dict[str, Any]], dependency.get("vulns", [])
                )
                if any(
                    self._has_fix_versions(vulnerability)
                    for vulnerability in vulnerabilities
                ):
                    remediable.append(dependency)
                else:
                    no_fix_versions.append(dependency)

            if remediable:
                return self._pip_audit_remediable_result(remediable, no_fix_versions)

            return self._pip_audit_no_fix_result(no_fix_versions)
        except json.JSONDecodeError:
            if result.success:
                return SecuritySubResult("pip-audit", True, "No vulnerabilities found")
            return SecuritySubResult(
                "pip-audit",
                False,
                result.output[-300:] if result.output else "pip-audit scan failed",
            )

    @staticmethod
    def _find_requirements_files(project_root: str) -> List[str]:
        """Return paths of requirements files in *project_root*, if any.

        Checks requirements.txt at root and any *.txt inside a requirements/
        subdirectory — the two most common patterns in Python projects.
        """
        root = Path(project_root)
        found: List[str] = []
        top_level = root / "requirements.txt"
        if top_level.exists():
            found.append(str(top_level))
        req_dir = root / "requirements"
        if req_dir.is_dir():
            found.extend(str(p) for p in sorted(req_dir.glob("*.txt")))
        return found
