"""Jinja2 template syntax validation.

Compiles all templates in the project to catch syntax errors early.
Far faster than discovering them at runtime.
"""

import os
import sys
import time
from typing import List, Optional

from slopmop.checks.base import BaseCheck, ConfigField, GateCategory
from slopmop.core.result import CheckResult, CheckStatus


class TemplateValidationCheck(BaseCheck):
    """Jinja2 template syntax validation.

    Uses 'templates_dir' from .sb_config.json config.
    """

    @property
    def name(self) -> str:
        return "templates"

    @property
    def display_name(self) -> str:
        return "📄 Template Validation (Jinja2)"

    @property
    def category(self) -> GateCategory:
        return GateCategory.GENERAL

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="templates_dir",
                field_type="string",
                default=None,
                description="Directory containing Jinja2 templates",
                required=True,
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        # Applicable if templates_dir is configured and exists
        return self._get_templates_dir(project_root) is not None

    def _get_templates_dir(self, project_root: str) -> Optional[str]:
        """Get templates directory from config."""
        configured = self.config.get("templates_dir")
        if configured and os.path.isdir(os.path.join(project_root, configured)):
            return configured
        return None

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()

        # Check for dedicated template smoke test first
        template_test = os.path.join(
            project_root, "tests", "integration", "test_template_smoke.py"
        )
        if os.path.exists(template_test):
            return self._run_template_test(project_root, template_test, start_time)

        # Use configured templates directory
        templates_dir = self._get_templates_dir(project_root)
        if not templates_dir:
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=time.time() - start_time,
                output="No templates_dir configured in .sb_config.json.",
                fix_suggestion='Add "templates_dir": "templates" to .sb_config.json',
            )

        return self._validate_templates(project_root, templates_dir, start_time)

    def _run_template_test(
        self, project_root: str, test_path: str, start_time: float
    ) -> CheckResult:
        """Run existing template smoke test."""
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            test_path,
            "-v",
            "--tb=short",
            "-x",
        ]
        result = self._run_command(cmd, cwd=project_root, timeout=60)
        duration = time.time() - start_time

        if result.success:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output="All templates compile successfully",
            )

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=result.output,
            error="Template compilation failed",
            fix_suggestion="Fix Jinja2 syntax errors in the templates shown above.",
        )

    def _validate_templates(
        self, project_root: str, templates_dir: str, start_time: float
    ) -> CheckResult:
        """Compile templates using Jinja2 directly."""
        templates_path = os.path.join(project_root, templates_dir)

        try:
            from jinja2 import Environment, FileSystemLoader, select_autoescape
        except ImportError:
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=time.time() - start_time,
                output="Jinja2 not installed.",
                fix_suggestion="Install: pip install jinja2",
            )

        env = Environment(
            loader=FileSystemLoader(templates_path),
            autoescape=select_autoescape(
                ["html", "htm", "xml", "j2", "jinja", "jinja2"]
            ),
        )
        errors = []
        count = 0

        for root, _, files in os.walk(templates_path):
            for f in files:
                if f.endswith((".html", ".j2", ".jinja", ".jinja2")):
                    rel_path = os.path.relpath(os.path.join(root, f), templates_path)
                    count += 1
                    try:
                        env.get_template(rel_path)
                    except Exception as e:
                        errors.append(f"  {rel_path}: {e}")

        duration = time.time() - start_time

        if errors:
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output="\n".join(errors),
                error=f"{len(errors)} template(s) failed to compile",
                fix_suggestion="Fix Jinja2 syntax errors shown above.",
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output=f"All {count} templates in {templates_dir}/ compile successfully",
        )
