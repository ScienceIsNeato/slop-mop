"""ESLint expect-expect check for JavaScript/TypeScript tests.

Uses eslint-plugin-jest's `expect-expect` rule to enforce that every
test body contains at least one assertion. This is a mature, AST-based
alternative to regex heuristics — it understands scope, closures, and
helper functions, catching cases that simple pattern matching misses.

Complements the regex-based JavaScriptBogusTestsCheck:
  - Regex check catches tautologies (expect(true).toBe(true)) and empty bodies
  - This check catches assertion-free tests via full AST analysis

The rule auto-installs `eslint-plugin-jest` as a one-shot npx invocation,
so no permanent devDependency is required in the target project.
"""

import json
import os
import shutil
import tempfile
import time
from typing import Any, Dict, List, Optional

from slopmop.checks.base import (
    BaseCheck,
    ConfigField,
    Flaw,
    GateCategory,
    JavaScriptCheckMixin,
    ToolContext,
)
from slopmop.core.result import CheckResult, CheckStatus

# Shared constants for test file discovery — single source of truth so
# is_applicable() and _find_test_files() can never silently diverge.
TEST_SUFFIXES = (
    ".test.js",
    ".test.jsx",
    ".test.ts",
    ".test.tsx",
    ".spec.js",
    ".spec.jsx",
    ".spec.ts",
    ".spec.tsx",
)
EXCLUDED_DIRS = {"node_modules", "dist", "build", "coverage", ".git"}
from slopmop.subprocess.runner import SubprocessResult


class JavaScriptExpectCheck(BaseCheck, JavaScriptCheckMixin):
    """Enforce assertions in JS/TS tests via eslint-plugin-jest expect-expect.

    Runs ESLint with the jest/expect-expect rule on test files to catch
    tests that have no assertions. The rule uses full AST analysis, making
    it more reliable than regex matching for detecting assertion-free tests.

    This check complements the regex-based js-bogus-tests check:
    - js-bogus-tests: Catches tautologies and empty bodies (no AST needed)
    - js-expect-assert: Catches assertion-free tests via AST (more accurate)

    Profiles: commit, pr

    Configuration:
      additional_assert_functions: [] — Custom assertion function names to
          allow (e.g., ["customAssert", "expectSaga"]). These are passed
          to the expect-expect rule's assertFunctionNames option.
      exclude_dirs: [] — Additional directories to exclude from scanning.
      max_violations: 0 — Maximum violations before failure (default: 0).

    Prerequisites:
      Requires node/npx on PATH. The eslint plugin is loaded inline
      via --rulesdir or flat config — no project dependency needed.

    Common failures:
      Tests without assertions: Add expect() calls or mark the test
          name in additional_assert_functions if it uses a custom
          assertion helper.

    Re-check:
      ./sm swab -g deceptiveness:js-expect-assert --verbose
    """

    tool_context = ToolContext.NODE

    @property
    def name(self) -> str:
        return "js-expect-assert"

    @property
    def display_name(self) -> str:
        return "🔍 Expect Assertions (ESLint jest/expect-expect)"

    @property
    def category(self) -> GateCategory:
        return GateCategory.DECEPTIVENESS

    @property
    def flaw(self) -> Flaw:
        return Flaw.DECEPTIVENESS

    @property
    def depends_on(self) -> List[str]:
        return []

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="additional_assert_functions",
                field_type="string[]",
                default=[],
                description=(
                    "Custom assertion function names to allow "
                    '(e.g., ["customAssert", "expectSaga"])'
                ),
            ),
            ConfigField(
                name="exclude_dirs",
                field_type="string[]",
                default=[],
                description="Additional directories to exclude from scanning",
                permissiveness="fewer_is_stricter",
            ),
            ConfigField(
                name="max_violations",
                field_type="integer",
                default=0,
                description="Maximum violations before failure (0 = none)",
                permissiveness="lower_is_stricter",
            ),
        ]

    def skip_reason(self, project_root: str) -> str:
        """Return reason for skipping — delegate to JavaScriptCheckMixin."""
        return JavaScriptCheckMixin.skip_reason(self, project_root)

    def is_applicable(self, project_root: str) -> bool:
        """Check if this is a JavaScript project with test files."""
        if not self.is_javascript_project(project_root):
            return False

        # Check for test files matching our globs
        from pathlib import Path

        root = Path(project_root)
        for suffix in TEST_SUFFIXES:
            pattern = f"*{suffix}"
            for match in root.rglob(pattern):
                if not any(
                    part in EXCLUDED_DIRS for part in match.relative_to(root).parts
                ):
                    return True
        return False

    def _find_test_files(self, project_root: str) -> List[str]:
        """Find test files to scan, respecting exclude_dirs."""
        from pathlib import Path

        root = Path(project_root)
        exclude_dirs = set(self.config.get("exclude_dirs", []))
        skip_dirs = EXCLUDED_DIRS | exclude_dirs

        files: List[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for filename in filenames:
                if any(filename.endswith(suffix) for suffix in TEST_SUFFIXES):
                    files.append(os.path.join(dirpath, filename))

        return files

    def run(self, project_root: str) -> CheckResult:
        """Run eslint-plugin-jest expect-expect on test files."""
        start_time = time.time()

        test_files = self._find_test_files(project_root)
        if not test_files:
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=time.time() - start_time,
                output="No test files found to check.",
            )

        max_violations: int = self.config.get("max_violations", 0)
        additional: List[str] = self.config.get("additional_assert_functions", [])
        assert_fns: List[str] = ["expect", *additional]

        # Build the rule config as a JSON string for --rule
        rule_config = json.dumps(["error", {"assertFunctionNames": assert_fns}])

        # Install eslint + plugin to an isolated temp directory.
        # We can't use `npx --package=... eslint` because ESLint resolves
        # plugins relative to CWD, not the npx temp directory. In fresh
        # environments (Docker, CI), the plugin isn't in the npx cache so
        # ESLint can't find it. Installing to a known location and using
        # --resolve-plugins-relative-to is reliable everywhere.
        #
        # Pin to eslint@8 — ESLint 9.x removed the --no-eslintrc and
        # --plugin CLI flags in favour of flat config.
        tmpdir = tempfile.mkdtemp(prefix="sm-eslint-")
        try:
            install_err = self._install_eslint_deps(tmpdir, project_root, start_time)
            if install_err is not None:
                return install_err

            eslint_bin = os.path.join(tmpdir, "node_modules", ".bin", "eslint")
            node_modules = os.path.join(tmpdir, "node_modules")

            # --no-eslintrc prevents the project's own eslint config from
            # interfering. We ONLY want expect-expect.
            # --parser-options=ecmaVersion:latest is required because
            # --no-eslintrc resets ecmaVersion to ES5, which can't parse
            # arrow functions, const/let, template literals, etc.
            cmd = [
                eslint_bin,
                "--no-eslintrc",
                "--resolve-plugins-relative-to",
                node_modules,
                "--plugin",
                "jest",
                "--parser-options=ecmaVersion:latest",
                "--rule",
                f"jest/expect-expect: {rule_config}",
                "--format",
                "json",
                *test_files,
            ]

            result = self._run_command(cmd, cwd=project_root, timeout=120)
            duration = time.time() - start_time

            # Parse ESLint JSON output
            return self._parse_eslint_output(
                result, duration, len(test_files), max_violations, project_root
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _install_eslint_deps(
        self, tmpdir: str, project_root: str, start_time: float
    ) -> Optional[CheckResult]:
        """Install eslint@8 + eslint-plugin-jest to a temp directory.

        Returns None on success, or a CheckResult on failure.
        """
        install_cmd = [
            "npm",
            "install",
            "--prefix",
            tmpdir,
            "eslint@8",
            "eslint-plugin-jest",
            "--no-save",
            "--no-audit",
            "--no-fund",
            "--loglevel=error",
        ]
        result = self._run_command(install_cmd, cwd=project_root, timeout=60)
        if result.returncode != 0:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=time.time() - start_time,
                error="Failed to install eslint dependencies",
                output=result.output,
                fix_suggestion="Ensure npm is available on PATH: npm --version",
            )
        return None

    def _parse_eslint_output(
        self,
        result: SubprocessResult,
        duration: float,
        files_checked: int,
        max_violations: int,
        project_root: str,
    ) -> CheckResult:
        """Parse ESLint JSON output and create a CheckResult."""
        if result.timed_out:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                error="ESLint timed out (120s). Project may need npm install first.",
                fix_suggestion="Run: npm install && sm swab -g deceptiveness:js-expect-assert",
            )

        # ESLint returns exit code 1 for lint errors, 2 for config errors
        if result.returncode == 2:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                error="ESLint configuration error",
                output=result.output,
                fix_suggestion=(
                    "This may indicate eslint-plugin-jest couldn't be loaded. "
                    "Ensure node/npm is on PATH and try: "
                    "npm install eslint@8 eslint-plugin-jest"
                ),
            )

        # Try to parse the JSON output
        violations = self._extract_violations(result.stdout, project_root)

        if violations is None:
            # Couldn't parse — maybe eslint gave non-JSON output
            # If returncode 0, call it passed (no lint errors)
            if result.success:
                return self._create_result(
                    status=CheckStatus.PASSED,
                    duration=duration,
                    output=f"✅ All {files_checked} test file(s) have assertions.",
                )
            # Non-zero, non-parseable — report raw output
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                error="Could not parse ESLint output",
                output=result.output[:2000],
                fix_suggestion="Run the command manually to diagnose: "
                "npx eslint --plugin jest --rule 'jest/expect-expect: error' <test-file>",
            )

        violation_count = len(violations)

        if violation_count == 0:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"✅ All {files_checked} test file(s) have assertions.",
            )

        # Build human-readable output
        output_lines = [
            f"Found {violation_count} test(s) without assertions:",
            "",
        ]
        for v in violations:
            output_lines.append(f"  {v['file']}:{v['line']} — {v['message']}")

        output = "\n".join(output_lines)

        if violation_count <= max_violations:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"⚠️ {violation_count} test(s) without assertions "
                f"(max allowed: {max_violations})\n\n{output}",
            )

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=output,
            error=f"Found {violation_count} test(s) without assertions "
            f"(max allowed: {max_violations})",
            fix_suggestion=(
                "Add expect() calls to each test, or configure "
                "additional_assert_functions in .sb_config.json if "
                "tests use custom assertion helpers."
            ),
        )

    def _extract_violations(
        self, output: str, project_root: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Extract expect-expect violations from ESLint JSON output.

        Returns list of {file, line, message} dicts, or None if parsing fails.
        Fatal parse errors are included as violations to prevent silent passes
        when ESLint can't analyze the files (e.g., syntax-level issues).
        """
        try:
            data: List[Dict[str, Any]] = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return None

        violations: List[Dict[str, Any]] = []
        for file_result in data:
            filepath = file_result.get("filePath", "")
            # Make path relative to project root for readability
            if filepath.startswith(project_root):
                filepath = os.path.relpath(filepath, project_root)

            for message in file_result.get("messages", []):
                rule_id = message.get("ruleId", "")
                is_fatal = message.get("fatal", False)

                if rule_id == "jest/expect-expect":
                    violations.append(
                        {
                            "file": filepath,
                            "line": message.get("line", 0),
                            "message": message.get("message", "Test has no assertions"),
                        }
                    )
                elif is_fatal:
                    # Fatal parse errors mean the file couldn't be analyzed.
                    # Surface them so the check doesn't silently pass.
                    violations.append(
                        {
                            "file": filepath,
                            "line": message.get("line", 0),
                            "message": f"Parse error: {message.get('message', 'unknown')}",
                        }
                    )

        return violations
