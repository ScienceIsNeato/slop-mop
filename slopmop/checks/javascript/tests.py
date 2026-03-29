"""JavaScript test execution check — Jest or custom runner."""

import shlex
import time
from typing import List

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    ToolContext,
)
from slopmop.checks.constants import (
    JS_NO_TESTS_FOUND_EXPECTED,
    JS_NO_TESTS_FOUND_JEST,
    TESTS_TIMED_OUT_MSG,
    js_no_tests_fix_suggestion,
)
from slopmop.checks.mixins import JavaScriptCheckMixin
from slopmop.constants import NPM_INSTALL_FAILED
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel

_DEFAULT_JEST_COMMAND = "npx --yes jest --ci --coverage"


class JavaScriptTestsCheck(BaseCheck, JavaScriptCheckMixin):
    """JavaScript/TypeScript test execution.

    Runs the configured test command (default: Jest with coverage).
    Installs npm dependencies automatically if missing.

    Level: swab

    Configuration:
      test_command: Command string parsed with ``shlex.split`` into
          argv and executed without a shell.  Shell operators
          (``&&``, ``|``, redirects) are not supported.
          Default ``"npx --yes jest --ci --coverage"``.
          Override when the project uses a custom test script
          (e.g. ``"npm test"``).
      exclude_dirs: Directories to exclude from test-file discovery.
          Files inside these directories are invisible to the gate.
          Default ``[]``.

    Pure Deno projects (detected via deno.json/deno.jsonc without
    package.json) are skipped automatically. Hybrid Node + Deno repos
    can override the runner, and ``sm init`` auto-seeds a Supabase
    Edge Functions workflow when the repo shape strongly suggests it.

    Common failures:
      Test failures: Output shows FAIL lines. Run ``npm test`` for
          full details.
      Timeout: Suite took > 5 minutes. Look for missing mocks
          or slow async operations.
      npm install failed: Check package.json syntax.

    Re-check:
      sm swab -g overconfidence:untested-code.js --verbose
    """

    tool_context = ToolContext.NODE
    role = CheckRole.FOUNDATION

    @property
    def name(self) -> str:
        return "untested-code.js"

    @property
    def display_name(self) -> str:
        return "🧪 Tests (JS/TS)"

    @property
    def gate_description(self) -> str:
        return "🧪 JavaScript/TypeScript test execution"

    @property
    def category(self) -> GateCategory:
        return GateCategory.OVERCONFIDENCE

    @property
    def flaw(self) -> Flaw:
        return Flaw.OVERCONFIDENCE

    @property
    def depends_on(self) -> List[str]:
        return ["laziness:sloppy-formatting.js"]

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="test_command",
                field_type="string",
                default=_DEFAULT_JEST_COMMAND,
                description=(
                    "Command string (parsed via shlex, no shell operators). "
                    "Override for non-Jest setups (e.g. 'npm test')."
                ),
            ),
            ConfigField(
                name="exclude_dirs",
                field_type="string[]",
                default=[],
                description=(
                    "Directories to exclude from test-file discovery "
                    "(e.g. ['supabase/functions'] for Deno Edge Functions)."
                ),
            ),
        ]

    def skip_reason(self, project_root: str) -> str:
        """Return reason for skipping — delegate to JavaScriptCheckMixin."""
        if self.is_deno_project(project_root) and not self.has_package_json(
            project_root
        ):
            return "Pure Deno project — use a Deno test gate instead"
        return JavaScriptCheckMixin.skip_reason(self, project_root)

    def is_applicable(self, project_root: str) -> bool:
        return self.is_javascript_project(project_root)

    def _get_test_command(self) -> List[str]:
        """Build the test command from config, falling back to Jest."""
        configured = self.config.get("test_command", _DEFAULT_JEST_COMMAND)
        return shlex.split(configured)

    def init_config(self, project_root: str) -> dict[str, str]:
        """Discover a strong-evidence Deno test workflow for hybrid repos."""
        if not (
            self.has_package_json(project_root) and self.is_deno_project(project_root)
        ):
            return {}
        test_glob = self.discover_supabase_deno_test_glob(project_root)
        if test_glob is None:
            return {}
        return {
            "test_command": f"deno test --allow-all --no-check {test_glob}",
        }

    def _get_exclude_dirs(self) -> set[str]:
        """Return the set of directory names to exclude from discovery."""
        raw: list[str] = self.config.get("exclude_dirs") or []
        if isinstance(raw, str):
            raw = [raw]
        return set(raw)

    def _should_install_dependencies(self) -> bool:
        """Install node deps when the test command is npm/npx based."""
        cmd = self._get_test_command()
        return bool(cmd) and cmd[0] in ("npm", "npx")

    def run(self, project_root: str) -> CheckResult:
        """Run test command."""
        start_time = time.time()

        extra_excludes = self._get_exclude_dirs()
        if not self.has_javascript_test_files(
            project_root, extra_excludes=extra_excludes
        ):
            message = JS_NO_TESTS_FOUND_EXPECTED
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=time.time() - start_time,
                error=message,
                output=message,
                fix_suggestion=js_no_tests_fix_suggestion(self.verify_command),
                findings=[Finding(message=message, level=FindingLevel.ERROR)],
            )

        if self._should_install_dependencies() and not self.has_node_modules(
            project_root
        ):
            npm_cmd = self._get_npm_install_command(project_root)
            npm_result = self._run_command(npm_cmd, cwd=project_root, timeout=120)
            if not npm_result.success:
                return self._create_result(
                    status=CheckStatus.ERROR,
                    duration=time.time() - start_time,
                    error=NPM_INSTALL_FAILED,
                    output=npm_result.output,
                )

        test_cmd = self._get_test_command()
        result = self._run_command(test_cmd, cwd=project_root, timeout=300)

        duration = time.time() - start_time

        if result.timed_out:
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=result.output,
                error=TESTS_TIMED_OUT_MSG,
                findings=[
                    Finding(message=TESTS_TIMED_OUT_MSG, level=FindingLevel.ERROR)
                ],
            )

        if not result.success:
            if "No tests found" in result.output:
                message = JS_NO_TESTS_FOUND_JEST
                return self._create_result(
                    status=CheckStatus.FAILED,
                    duration=duration,
                    output=result.output,
                    error=message,
                    fix_suggestion=js_no_tests_fix_suggestion(self.verify_command),
                    findings=[Finding(message=message, level=FindingLevel.ERROR)],
                )
            findings: List[Finding] = []
            for line in result.output.split("\n"):
                stripped = line.strip()
                if stripped.startswith("FAIL "):
                    parts = stripped.split(None, 1)
                    if len(parts) == 2:
                        findings.append(
                            Finding(message="Test suite failed", file=parts[1])
                        )

            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=result.output,
                error=f"{len(findings)} test file(s) failed",
                fix_suggestion=(
                    "Test failures shown above. Fix the assertion "
                    "errors, then verify with: " + self.verify_command
                ),
                findings=findings,
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output=result.output,
        )
