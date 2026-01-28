"""
Frontend check — quick JavaScript validation gate.

A lightweight, fast JS sanity check distinct from the full js-format
suite.  Runs ESLint (errors only, no warnings) in under 10 seconds
to give developers rapid feedback on frontend correctness without
waiting for prettier auto-fix or full lint pass.

Skips when no static/ or frontend/ JavaScript sources are found.
"""

import os
from typing import List, Optional

from slopbucket.base_check import BaseCheck
from slopbucket.result import CheckResult, CheckStatus
from slopbucket.subprocess_guard import run


class FrontendCheck(BaseCheck):
    """Quick frontend JS validation (errors-only ESLint)."""

    @property
    def name(self) -> str:
        return "frontend-check"

    @property
    def description(self) -> str:
        return "Quick frontend validation (ESLint errors-only, ~5s)"

    def _find_js_dirs(self, base: str) -> List[str]:
        """Locate directories containing JS source files."""
        candidates = ["static", "frontend", "src/static", "public"]
        found = []
        for c in candidates:
            path = os.path.join(base, c)
            if os.path.isdir(path):
                # Verify it actually contains .js files
                for root, _dirs, files in os.walk(path):
                    if any(f.endswith(".js") for f in files):
                        found.append(c)
                        break
        return found

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        base = working_dir or os.getcwd()

        # Require package.json (Node project)
        if not os.path.exists(os.path.join(base, "package.json")):
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="No package.json found — frontend check skipped.",
            )

        js_dirs = self._find_js_dirs(base)
        if not js_dirs:
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="No JavaScript source directories found — frontend check skipped.",
            )

        # Run ESLint in errors-only mode (--max-warnings 0 not set — fast path)
        eslint_targets = " ".join(js_dirs)
        cmd = [
            "npx",
            "eslint",
            "--ext",
            ".js",
            "--rule",
            '{"no-undef": "error", "no-unused-vars": "warn"}',
            "--quiet",  # errors only
        ] + js_dirs

        result = run(cmd, cwd=base, timeout=30)

        if result.success:
            return self._make_result(
                status=CheckStatus.PASSED,
                output=f"Frontend check passed ({eslint_targets})",
            )

        if result.returncode == 2:
            return self._make_result(
                status=CheckStatus.ERROR,
                output="ESLint configuration error.\n" + result.stderr,
                fix_hint="Check .eslintrc or eslint.config.js for syntax errors.",
            )

        return self._make_result(
            status=CheckStatus.FAILED,
            output=result.stdout + result.stderr,
            fix_hint="Fix ESLint errors shown above. "
            "Run: npx eslint --fix <file> for auto-fixable issues.",
        )
