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
    CheckRole,
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
      sm swab -g laziness:complexity-creep.py --verbose
    """

    tool_context = ToolContext.SM_TOOL
    role = CheckRole.FOUNDATION

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
        limit = self.config.get("max_complexity", MAX_COMPLEXITY)
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=detail,
            error=f"{len(violations)} function(s) exceed limit",
            fix_suggestion=(
                "Each function above has a complexity delta to shed. "
                "Extract the longest conditional branch (if/elif chain "
                "or try/except cascade) into a named helper. Verify "
                "with: " + self.verify_command
            ),
            findings=[_to_finding(v, limit) for v in violations],
        )

    def _parse_violations(self, output: str) -> List[str]:
        violations: List[str] = []
        for line in output.splitlines():
            if re.search(r"\b[DEF]\b", line) and "(" in line:
                violations.append(line.strip())
        return violations


# ─── radon output parsing ────────────────────────────────────────────────
#
# radon --md lines embed file:line inside markdown — try to recover
# them, but fall back to a message-only finding when the format
# doesn't match (still a separate SARIF result per function).
#
# Line also carries the function name and (score) — extracting both
# lets the fix_strategy name the exact function and its complexity
# count.  "Extract helpers from foo() (complexity 24)" is actionable;
# "break complex functions" is a platitude.

_LOC_RE = re.compile(r"(\S+\.py)[:\s*]+(\d+)")

# radon -s annotates rank with the numeric score in parens, e.g.
# "... foo - D (24)" — capture the name token before the dash and
# the number in parens.  [\w.]+ (not \w+) so "MyClass.complex_method
# - D (24)" keeps the class qualifier; "Extract helpers from
# complex_method()" is ambiguous when three classes share the name.
# Either group may miss on odd output; strategy stays None in that
# case (no guessing).
_META_RE = re.compile(r"`?([\w.]+)`?\s*-\s*[A-F]\s*\((\d+)\)")


def _to_finding(violation_line: str, limit: int = MAX_COMPLEXITY) -> Finding:
    """Convert one radon violation line into a structured Finding."""
    loc = _LOC_RE.search(violation_line)
    meta = _META_RE.search(violation_line)

    strategy: Optional[str] = None
    if meta:
        name, score_s = meta.group(1), meta.group(2)
        score = int(score_s)
        delta = score - limit
        if delta > 0:
            strategy = (
                f"Complexity is {score}, limit is {limit} \u2014 "
                f"shed at least {delta}. Each "
                f"if/for/while/except/and/or adds 1. Extract "
                f"the longest branch into a helper function."
            )
        else:
            strategy = (
                f"Extract helpers from {name}() \u2014 complexity {score} "
                f"exceeds rank threshold. Identify the largest "
                f"branch or loop and move it to a named function."
            )

    if loc:
        return Finding(
            message=violation_line,
            file=loc.group(1),
            line=int(loc.group(2)),
            fix_strategy=strategy,
        )
    return Finding(message=violation_line, fix_strategy=strategy)
