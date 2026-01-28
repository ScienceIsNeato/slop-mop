"""
JavaScript formatting check — ESLint + Prettier.

Auto-fixes first, then validates. Same strategy as python_format:
only fails if the issue survives auto-fix.
"""

import sys
from typing import Optional

from slopbucket.base_check import BaseCheck
from slopbucket.result import CheckResult, CheckStatus
from slopbucket.subprocess_guard import run


class JSFormatCheck(BaseCheck):
    """ESLint + Prettier formatting for JavaScript."""

    @property
    def name(self) -> str:
        return "js-format"

    @property
    def description(self) -> str:
        return "JavaScript: ESLint + Prettier (auto-fix applied)"

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        import os

        base = working_dir or os.getcwd()

        # Check if there's JS source to validate
        if not self._has_js_source(base):
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="No JavaScript source files found.",
            )

        # Check for eslint config
        eslint_config = self._find_eslint_config(base)

        issues = []

        # 1. Prettier auto-fix
        npm_format = run(
            [sys.executable, "-m", "npm", "run", "format"], cwd=working_dir
        )
        # Try npm directly if python -m npm doesn't work
        if npm_format.returncode == 1 and "No module named npm" in npm_format.stderr:
            npm_format = run(["npm", "run", "format"], cwd=working_dir)

        # 2. ESLint with auto-fix
        eslint_cmd = ["npx", "eslint", "static/**/*.js", "--fix"]
        if eslint_config:
            eslint_cmd.extend(["-c", eslint_config])
        eslint_result = run(eslint_cmd, cwd=working_dir, timeout=60)

        # 3. Validation — check if issues remain
        eslint_check_cmd = ["npx", "eslint", "static/**/*.js", "--max-warnings", "0"]
        if eslint_config:
            eslint_check_cmd.extend(["-c", eslint_config])
        validate_result = run(eslint_check_cmd, cwd=working_dir, timeout=60)

        if not validate_result.success:
            issues.append(validate_result.stdout or validate_result.stderr)

        if issues:
            return self._make_result(
                status=CheckStatus.FAILED,
                output="\n".join(issues),
                fix_hint="Fix ESLint errors shown above. Run: npx eslint static/**/*.js --fix",
            )

        return self._make_result(
            status=CheckStatus.PASSED, output="JavaScript formatting OK"
        )

    def _has_js_source(self, base: str) -> bool:
        import os

        static_dir = os.path.join(base, "static")
        if os.path.isdir(static_dir):
            for root, _, files in os.walk(static_dir):
                if any(f.endswith(".js") for f in files):
                    return True
        return False

    def _find_eslint_config(self, base: str) -> Optional[str]:
        import os

        candidates = [
            "config/.eslintrc.json",
            ".eslintrc.json",
            ".eslintrc.js",
            ".eslintrc.yml",
        ]
        for c in candidates:
            path = os.path.join(base, c)
            if os.path.exists(path):
                return c
        return None
