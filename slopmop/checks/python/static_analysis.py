"""Python static analysis check using mypy."""

import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

from slopmop.checks.base import BaseCheck, ConfigField, GateCategory, PythonCheckMixin
from slopmop.core.result import CheckResult, CheckStatus

# mypy error code pattern: file.py:10: error: message  [code]
_MYPY_ERROR_RE = re.compile(r"^(.+?):(\d+): error: (.+?)(?:\s+\[(\S+)\])?\s*$")


class PythonStaticAnalysisCheck(BaseCheck, PythonCheckMixin):
    """Static type checking with mypy.

    Wraps mypy to enforce type safety across Python source. In strict
    mode (default), requires type annotations on all function signatures
    and type parameters on generics (Dict[str, Any] not bare Dict).
    These catch root-cause annotations that prevent type checkers from
    cascading hundreds of "unknown type" errors downstream.

    Profiles: commit, pr

    Configuration:
      strict_typing: True — enforces --disallow-untyped-defs and
          --disallow-any-generics. Without these, bare Dict/List and
          unannotated functions silently pass, then Pylance/pyright
          lights up with hundreds of cascading errors.

    Common failures:
      type-arg: Add type parameters to generics.
          Dict → Dict[str, Any], List → List[str], etc.
      no-untyped-def: Add return type and parameter annotations.
          def foo(x) → def foo(x: str) -> None
      attr-defined: Accessing an attribute that doesn't exist on the
          inferred type. Check your class hierarchy.

    Re-validate:
      ./sm validate python:static-analysis --verbose
    """

    @property
    def name(self) -> str:
        return "static-analysis"

    @property
    def display_name(self) -> str:
        strict = self._is_strict()
        label = "strict" if strict else "basic"
        return f"🔍 Static Analysis (mypy {label})"

    @property
    def category(self) -> GateCategory:
        return GateCategory.PYTHON

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="strict_typing",
                field_type="boolean",
                default=True,
                description=(
                    "Enforce strict type annotations: require type params on "
                    "generics (Dict[str, Any] not Dict) and annotations on all "
                    "function signatures. Catches root-cause issues that would "
                    "otherwise cascade into hundreds of 'unknown type' errors "
                    "in editors like Pylance/pyright."
                ),
            ),
        ]

    @property
    def depends_on(self) -> List[str]:
        return ["python:lint-format"]

    def is_applicable(self, project_root: str) -> bool:
        """Applicable only if there are Python source directories to type-check."""
        if not self.is_python_project(project_root):
            return False

        # If user explicitly configured include_dirs, always run — they know
        # what they want, even if the value is ["."].
        cfg_dirs = self.config.get("include_dirs", [])
        if isinstance(cfg_dirs, list) and cfg_dirs:
            return True

        # Heuristic path: skip when fallback lands on ["."] (no proper source
        # dirs found — avoids running mypy on "." which causes submodule issues)
        source_dirs = self._detect_source_dirs(project_root)
        return source_dirs != ["."]

    def skip_reason(self, project_root: str) -> str:
        """Return reason for skipping."""
        if not self.is_python_project(project_root):
            return PythonCheckMixin.skip_reason(self, project_root)
        return "No Python source directories found (src/, slopmop/, lib/, or packages with __init__.py)"

    def _is_strict(self) -> bool:
        """Whether strict typing mode is enabled."""
        return self.config.get("strict_typing", True)

    def _detect_source_dirs(self, project_root: str) -> List[str]:
        """Detect source directories to type-check.

        Priority:
        1. Gate-level ``include_dirs`` from config (``self.config``)
        2. Heuristic: scan well-known directory names for ``.py`` files
        """
        # Honour explicit config — gate-level or language-level include_dirs
        # are already plumbed through self.config by SlopmopConfig, so we
        # don't re-read .sb_config.json here (avoids SB_CONFIG_FILE bypass,
        # malformed-JSON crashes, and string-vs-list issues).
        cfg_dirs: List[str] = self.config.get("include_dirs", [])
        if isinstance(cfg_dirs, list) and cfg_dirs:
            return cfg_dirs

        source_dirs: List[str] = []

        for name in ["src", "slopmop", "lib"]:
            dir_path = os.path.join(project_root, name)
            # Only include if directory exists AND contains Python files
            if os.path.isdir(dir_path):
                has_python = any(Path(dir_path).rglob("*.py"))
                if has_python:
                    source_dirs.append(name)

        if not source_dirs:
            for entry in os.listdir(project_root):
                entry_path = os.path.join(project_root, entry)
                if (
                    os.path.isdir(entry_path)
                    and os.path.exists(os.path.join(entry_path, "__init__.py"))
                    and entry not in ("tests", "test", "venv", ".venv", "build", "dist")
                ):
                    source_dirs.append(entry)

        return source_dirs or ["."]

    def _build_command(self, source_dirs: List[str]) -> List[str]:
        """Build the mypy command with configured flags."""
        cmd = ["mypy", *source_dirs, "--ignore-missing-imports", "--no-strict-optional"]

        if self._is_strict():
            cmd.extend(["--disallow-untyped-defs", "--disallow-any-generics"])

        return cmd

    @staticmethod
    def _dedup_output(raw_output: str) -> Tuple[List[str], Dict[str, int]]:
        """Filter mypy output to root-cause errors only.

        Strips 'note:' lines (hints/context) and returns:
          - error_lines: the actual error messages
          - code_counts: Counter of error codes for the summary header

        mypy doesn't cascade like Pylance — each error IS a root cause.
        The dedup here is about removing noise (notes), not collapsing
        cascades.
        """
        error_lines: List[str] = []
        code_counts: Dict[str, int] = Counter()

        for line in raw_output.splitlines():
            line = line.strip()
            if not line or ": note:" in line:
                continue
            if "Found " in line and " error" in line:
                continue  # Skip the summary line — we make our own

            match = _MYPY_ERROR_RE.match(line)
            if match:
                code = match.group(4) or "unknown"
                code_counts[code] += 1
                error_lines.append(line)

        return error_lines, dict(code_counts)

    @staticmethod
    def _format_summary(error_lines: List[str], code_counts: Dict[str, int]) -> str:
        """Build a concise, LLM-friendly error report.

        Groups errors by code for a summary header, then lists
        each unique error. Caps output to avoid token bloat.
        """
        MAX_ERRORS_TO_SHOW = 20

        parts: List[str] = []

        # Summary header — what categories of errors exist
        total = sum(code_counts.values())
        breakdown = ", ".join(
            f"{count} [{code}]" for code, count in sorted(code_counts.items())
        )
        parts.append(f"{total} type error(s): {breakdown}")
        parts.append("")

        # Individual errors (capped)
        for line in error_lines[:MAX_ERRORS_TO_SHOW]:
            parts.append(f"  {line}")

        if len(error_lines) > MAX_ERRORS_TO_SHOW:
            remaining = len(error_lines) - MAX_ERRORS_TO_SHOW
            parts.append(f"\n  ... and {remaining} more")

        return "\n".join(parts)

    def run(self, project_root: str) -> CheckResult:
        """Run mypy type checking."""
        start_time = time.time()

        source_dirs = self._detect_source_dirs(project_root)
        cmd = self._build_command(source_dirs)
        result = self._run_command(cmd, cwd=project_root, timeout=120)

        duration = time.time() - start_time

        if result.timed_out:
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=result.output,
                error="Type checking timed out after 2 minutes",
            )

        if not result.success:
            error_lines, code_counts = self._dedup_output(result.output)
            output = self._format_summary(error_lines, code_counts)
            total = sum(code_counts.values())

            fix_parts = ["Fix type annotations or add # type: ignore comments."]
            if "type-arg" in code_counts:
                fix_parts.append(
                    "type-arg: Add type parameters to generics "
                    "(Dict[str, Any] not Dict)."
                )
            if "no-untyped-def" in code_counts:
                fix_parts.append(
                    "no-untyped-def: Add return type and parameter "
                    "annotations to functions."
                )

            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=output,
                error=f"{total} type error(s) found",
                fix_suggestion=" ".join(fix_parts),
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output=result.output,
        )
