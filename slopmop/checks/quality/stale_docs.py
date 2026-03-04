"""Stale documentation detection — README gate tables vs source of truth.

LLM agents routinely update check metadata (names, descriptions,
categories) without regenerating the README tables, leaving users
with documentation that silently contradicts the running code.

This gate compares the ``<!-- BEGIN GATE TABLES -->`` /
``<!-- END GATE TABLES -->`` section in README.md against what the
registry would generate, and **fails** (not just warns) when they
diverge.

Fix:
    python scripts/generate_readme_tables.py --update
"""

import logging
import time
from pathlib import Path

from slopmop.checks.base import BaseCheck, Flaw, GateCategory, ToolContext
from slopmop.core.registry import get_registry
from slopmop.core.result import CheckResult, CheckStatus

logger = logging.getLogger(__name__)


class StaleDocsCheck(BaseCheck):
    """Detect stale README gate tables.

    Generates the expected Markdown tables from registry metadata and
    compares them to the current README.  Returns FAILED when they
    don't match — stale docs should block, not merely nudge.

    Re-check:
      ./sm swab -g laziness:stale-docs
    """

    tool_context = ToolContext.PURE

    @property
    def name(self) -> str:
        return "stale-docs"

    @property
    def display_name(self) -> str:
        return "📖 Stale Docs"

    @property
    def gate_description(self) -> str:
        return "📖 Detects stale README gate tables"

    @property
    def category(self) -> GateCategory:
        return GateCategory.LAZINESS

    @property
    def flaw(self) -> Flaw:
        return Flaw.LAZINESS

    def is_applicable(self, project_root: str) -> bool:
        """Applicable when README.md exists and contains gate table markers."""
        from slopmop.utils.readme_tables import BEGIN_MARKER, END_MARKER

        readme = Path(project_root) / "README.md"
        if not readme.exists():
            return False
        text = readme.read_text()
        return BEGIN_MARKER in text and END_MARKER in text

    def skip_reason(self, project_root: str) -> str:
        readme = Path(project_root) / "README.md"
        if not readme.exists():
            return "No README.md found"
        return "README.md has no gate table markers"

    def run(self, project_root: str) -> CheckResult:
        start = time.time()
        readme_path = Path(project_root) / "README.md"

        # Late import to keep the module-level dependency graph clean
        from slopmop.utils.readme_tables import check_readme

        registry = get_registry()
        is_current, message = check_readme(readme_path, registry)
        duration = time.time() - start

        if is_current:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=message,
            )

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=message,
            error="README gate tables are stale",
            fix_suggestion=("Run:  python scripts/generate_readme_tables.py --update"),
        )
