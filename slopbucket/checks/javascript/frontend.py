"""Quick frontend validation check.

Runs ESLint in errors-only mode for rapid feedback (~5s) on
frontend JavaScript sources in static/, frontend/, public/ directories.
"""

import os
import time
from typing import List

from slopbucket.checks.base import BaseCheck, JavaScriptCheckMixin
from slopbucket.core.result import CheckResult, CheckStatus


class FrontendCheck(BaseCheck, JavaScriptCheckMixin):
    """Quick frontend JS validation (ESLint errors-only)."""

    @property
    def name(self) -> str:
        return "frontend-check"

    @property
    def display_name(self) -> str:
        return "⚡ Frontend Check (quick ESLint)"

    def is_applicable(self, project_root: str) -> bool:
        if not self.is_javascript_project(project_root):
            return False
        return bool(self._find_js_dirs(project_root))

    def _find_js_dirs(self, project_root: str) -> List[str]:
        """Locate directories containing JS source files."""
        candidates = ["static", "frontend", "src/static", "public"]
        found = []
        for c in candidates:
            path = os.path.join(project_root, c)
            if os.path.isdir(path):
                for root, _, files in os.walk(path):
                    if any(f.endswith(".js") for f in files):
                        found.append(c)
                        break
        return found

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()

        js_dirs = self._find_js_dirs(project_root)
        if not js_dirs:
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=time.time() - start_time,
                output="No frontend JavaScript directories found.",
            )

        # Run ESLint in errors-only mode (fast path)
        cmd = [
            "npx", "eslint",
            "--ext", ".js",
            "--rule", '{"no-undef": "error", "no-unused-vars": "warn"}',
            "--quiet",  # errors only
        ] + js_dirs

        result = self._run_command(cmd, cwd=project_root, timeout=30)
        duration = time.time() - start_time

        if result.success:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"Frontend check passed ({', '.join(js_dirs)})",
            )

        if result.returncode == 2:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                error="ESLint configuration error",
                output=result.output,
                fix_suggestion="Check .eslintrc or eslint.config.js for syntax errors.",
            )

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=result.output,
            error="ESLint errors found",
            fix_suggestion="Fix ESLint errors above. Run: npx eslint --fix <file>",
        )
