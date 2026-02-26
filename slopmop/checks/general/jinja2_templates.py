"""Jinja2 template syntax validation.

Compiles all templates in the project to catch syntax errors early.
Far faster than discovering them at runtime.
"""

import os
import time
from typing import List, Optional

from slopmop.checks.base import (
    BaseCheck,
    ConfigField,
    Flaw,
    GateCategory,
    PythonCheckMixin,
    ToolContext,
)
from slopmop.core.result import CheckResult, CheckStatus


class TemplateValidationCheck(BaseCheck, PythonCheckMixin):
    tool_context = ToolContext.PROJECT
    """Jinja2 template syntax validation.

    Compiles all templates in the configured directory to catch
    syntax errors early — far faster than discovering them at
    runtime. Uses Jinja2's own compiler or delegates to a
    dedicated template smoke test if one exists.

    Profiles: (not in commit/pr by default — add manually)

    Configuration:
      templates_dir: None (required) — directory containing
          Jinja2 templates, relative to project root. Must be
          set in .sb_config.json for the gate to activate.

    Common failures:
      Template syntax error: The output shows the template file
          and the Jinja2 error. Fix the template syntax.
      No templates_dir configured: Add "templates_dir":
          "templates" to .sb_config.json.
      Jinja2 not installed: pip install jinja2

    Re-validate:
      ./scripts/sm validate laziness:template-syntax --verbose
    """

    @property
    def name(self) -> str:
        return "template-syntax"

    @property
    def display_name(self) -> str:
        return "📄 Template Syntax Validation (Jinja2)"

    @property
    def category(self) -> GateCategory:
        return GateCategory.LAZINESS

    @property
    def flaw(self) -> Flaw:
        return Flaw.OVERCONFIDENCE

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

    def skip_reason(self, project_root: str) -> str:
        """Explain why templates check is not applicable."""
        configured = self.config.get("templates_dir")
        if not configured:
            return "No templates_dir configured in .sb_config.json"
        templates_path = os.path.join(project_root, configured)
        if not os.path.isdir(templates_path):
            return f"Configured templates_dir '{configured}' does not exist"
        return "No Jinja2 templates detected"

    def _get_templates_dir(self, project_root: str) -> Optional[str]:
        """Get templates directory from config."""
        configured = self.config.get("templates_dir")
        if configured and os.path.isdir(os.path.join(project_root, configured)):
            return configured
        return None

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()

        # PROJECT check: bail early when no project venv exists
        venv_warn = self.check_project_venv_or_warn(project_root, start_time)
        if venv_warn is not None:
            return venv_warn

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
            self.get_project_python(project_root),
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
        errors: List[str] = []
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
