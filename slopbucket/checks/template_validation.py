"""
Template validation — Jinja2 syntax checking.

Compiles all templates in the project to catch syntax errors early.
Far faster than discovering them at runtime.
"""

import sys
from typing import Optional

from slopbucket.base_check import BaseCheck
from slopbucket.result import CheckResult, CheckStatus
from slopbucket.subprocess_guard import run


class TemplateValidationCheck(BaseCheck):
    """Jinja2 template syntax validation."""

    @property
    def name(self) -> str:
        return "template-validation"

    @property
    def description(self) -> str:
        return "Jinja2 template syntax validation"

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        import os

        base = working_dir or os.getcwd()

        # Look for a template smoke test
        template_test = os.path.join(
            base, "tests", "integration", "test_template_smoke.py"
        )
        if os.path.exists(template_test):
            cmd = [
                sys.executable,
                "-m",
                "pytest",
                "tests/integration/test_template_smoke.py",
                "-v",
                "--tb=short",
                "-x",
            ]
            result = run(cmd, cwd=working_dir, timeout=60)

            if result.success:
                return self._make_result(
                    status=CheckStatus.PASSED,
                    output="All templates compile successfully",
                )

            return self._make_result(
                status=CheckStatus.FAILED,
                output=result.stdout or result.stderr,
                fix_hint="Fix Jinja2 syntax errors in the templates shown above.",
            )

        # Fallback: look for templates directory and try to compile manually
        templates_dir = self._find_templates_dir(base)
        if not templates_dir:
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="No templates directory or template smoke test found.",
            )

        return self._validate_templates(templates_dir, working_dir)

    def _find_templates_dir(self, base: str) -> Optional[str]:
        import os

        candidates = ["templates", "src/templates", "app/templates"]
        for c in candidates:
            if os.path.isdir(os.path.join(base, c)):
                return c
        return None

    def _validate_templates(
        self, templates_dir: str, working_dir: Optional[str]
    ) -> CheckResult:
        """Compile templates using Python's Jinja2."""
        import os

        base = working_dir or os.getcwd()
        templates_path = os.path.join(base, templates_dir)

        try:
            from jinja2 import Environment, FileSystemLoader

            env = Environment(loader=FileSystemLoader(templates_path))
            errors = []

            for root, _, files in os.walk(templates_path):
                for f in files:
                    if f.endswith((".html", ".j2", ".jinja", ".jinja2")):
                        rel_path = os.path.relpath(
                            os.path.join(root, f), templates_path
                        )
                        try:
                            env.get_template(rel_path)
                        except Exception as e:
                            errors.append(f"  {rel_path}: {e}")

            if errors:
                return self._make_result(
                    status=CheckStatus.FAILED,
                    output="\n".join(errors),
                    fix_hint="Fix the Jinja2 syntax errors shown above.",
                )

            return self._make_result(
                status=CheckStatus.PASSED,
                output=f"All templates in {templates_dir}/ compile successfully",
            )
        except ImportError:
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="Jinja2 not installed — install it to enable template validation.",
            )
