"""Cyclomatic complexity check using radon.

Flags functions with complexity rank D or higher (>20).
Provides specific function names and their complexity scores
so agents can immediately identify what to refactor.

Note: This is a cross-cutting quality check. While it uses radon
(a Python tool), complexity is a universal code quality concern.
"""

import os
import re
import time
from typing import List, Optional

from slopmop.checks.base import (
    BaseCheck,
    ConfigField,
    Flaw,
    GateCategory,
    ToolContext,
)
from slopmop.checks.constants import COMMAND_NOT_FOUND
from slopmop.checks.mixins import PythonCheckMixin
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel

MAX_RANK = "C"
MAX_COMPLEXITY = 20

# radon -s emits the numeric complexity in parentheses after the rank
# letter, e.g. "... - D (21)" in plain mode or "... **D** (21)" in --md
# mode.  Capture it so we can compute the delta to shed.
_SCORE_RE = re.compile(r"\((\d+)\)")


class ComplexityCheck(BaseCheck, PythonCheckMixin):
    """Cyclomatic complexity enforcement.

    Wraps radon to flag functions with complexity rank D or higher.
    Complexity rank C (score ≤20) is the threshold — anything above
    indicates a function that is too branchy for humans or LLMs to
    reason about reliably.

    Level: swab

    Configuration:
      max_rank: "C" — ranks A-C are acceptable. D+ means the function
          has > 20 independent paths and should be decomposed.
      max_complexity: 15 — numeric score threshold. Functions above
          this score appear in the violation list.
      src_dirs: [] — empty means scan project root. Set to specific
          directories to limit scope.

    Common failures:
      High complexity function: Break it into smaller helpers that
          each handle one concept. Focus on logical separation, not
          arbitrary line reduction.
      radon not available: pip install radon

    Re-check:
      ./sm swab -g laziness:complexity-creep.py --verbose
    """

    tool_context = ToolContext.SM_TOOL

    @property
    def name(self) -> str:
        return "complexity-creep.py"

    @property
    def display_name(self) -> str:
        return f"🌀 Complexity (max rank {MAX_RANK})"

    @property
    def gate_description(self) -> str:
        return "🌀 Cyclomatic complexity (max rank C)"

    @property
    def category(self) -> GateCategory:
        return GateCategory.LAZINESS

    @property
    def flaw(self) -> Flaw:
        return Flaw.LAZINESS

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="max_rank",
                field_type="string",
                default="C",
                description="Maximum complexity rank (A-F)",
                choices=["A", "B", "C", "D", "E", "F"],
                permissiveness="lower_is_stricter",
            ),
            ConfigField(
                name="max_complexity",
                field_type="integer",
                default=15,
                description="Maximum cyclomatic complexity score",
                permissiveness="lower_is_stricter",
            ),
            ConfigField(
                name="src_dirs",
                field_type="string[]",
                default=[],
                description="Directories to scan for complexity (empty = project root)",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        """Check if there are Python files to analyze."""
        from pathlib import Path

        root = Path(project_root)
        return any(root.rglob("*.py"))

    def _get_target_dirs(self, project_root: str) -> List[str]:
        """Get directories to check from config, with sensible fallbacks."""
        # Use configured src_dirs if available
        configured = self.config.get("src_dirs", [])
        if configured:
            return [
                d for d in configured if os.path.isdir(os.path.join(project_root, d))
            ]
        # Fallback: check project root for .py files
        return ["."]

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()
        dirs = self._get_target_dirs(project_root)

        if not dirs:
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=time.time() - start_time,
                output="No src_dirs configured and no Python files found.",
            )

        cmd = [
            "radon",
            "cc",
            "--min",
            "D",
            "-s",
            "-a",
            "--md",
        ] + dirs
        result = self._run_command(cmd, cwd=project_root, timeout=120)
        duration = time.time() - start_time

        # returncode 127 = shell "command not found"
        # returncode -1 = FileNotFoundError from SubprocessRunner
        if result.returncode == 127 or (
            result.returncode == -1 and COMMAND_NOT_FOUND in result.stderr
        ):
            msg = "Radon not available"
            return self._create_result(
                status=CheckStatus.WARNED,
                duration=duration,
                error=msg,
                fix_suggestion="Install radon: pip install radon",
                findings=[Finding(message=msg, level=FindingLevel.WARNING)],
            )

        violations = self._parse_violations(result.output)
        if not violations:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output="All functions within complexity limits",
            )

        detail = "Functions exceeding complexity:\n" + "\n".join(
            f"  {v}" for v in violations
        )
        # radon --md lines embed file:line inside markdown — try to recover
        # them, but fall back to a message-only finding when the format
        # doesn't match (still a separate SARIF result per function).
        loc_re = re.compile(r"(\S+\.py)[:\s*]+(\d+)")
        limit = self.config.get("max_complexity", MAX_COMPLEXITY)
        structured: List[Finding] = []
        for v in violations:
            m = loc_re.search(v)
            # Pull the numeric score that -s appended.  If radon's
            # output changed shape and we can't find one, skip the
            # fix_strategy — a wrong delta is worse than no delta.
            score_m = _SCORE_RE.search(v)
            fix: Optional[str] = None
            if score_m:
                score = int(score_m.group(1))
                delta = score - limit
                if delta > 0:
                    fix = (
                        f"Complexity is {score}, limit is {limit} — "
                        f"shed at least {delta}. Each "
                        f"if/for/while/except/and/or adds 1. Extract "
                        f"the longest branch into a helper function."
                    )
            if m:
                structured.append(
                    Finding(
                        message=v,
                        file=m.group(1),
                        line=int(m.group(2)),
                        fix_strategy=fix,
                    )
                )
            else:
                structured.append(Finding(message=v, fix_strategy=fix))
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=detail,
            error=f"{len(violations)} function(s) exceed limit",
            fix_suggestion=(
                "Each function above has a complexity delta to shed. "
                "Extract the longest conditional branch (if/elif chain "
                "or try/except cascade) into a named helper. Verify "
                f"with: sm swab -g {self.full_name}"
            ),
            findings=structured,
        )

    def _parse_violations(self, output: str) -> List[str]:
        violations: List[str] = []
        for line in output.splitlines():
            if re.search(r"\b[DEF]\b", line) and "(" in line:
                violations.append(line.strip())
        return violations
