"""Python type-completeness checking with pyright.

Why this gate exists (beyond mypy):

Python's loose typing is a productivity feature for human developers
who carry context in their heads. AI agents don't have that luxury.
When an agent reads `results = []`, it must guess what goes in there —
wasting context-window tokens on inference that could have been free.
When it reads `results: List[Tuple[str, int, int, str]] = []`, the
schema is self-documenting.

mypy (overconfidence:py-static-analysis) enforces that function SIGNATURES are
annotated. This gate enforces that every variable, argument, and
member access resolves to a KNOWN type — not just at function
boundaries but everywhere the code touches data.

The distinction matters:
  - mypy: "Did you annotate the function?" (presence)
  - pyright: "Can every consumer reason about types?" (completeness)

Each `reportUnknownVariableType` error is a place where an AI agent
would have to guess. This gate eliminates that guessing.
"""

import json
import os
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from slopmop.checks.base import (
    BaseCheck,
    ConfigField,
    Flaw,
    GateCategory,
    PythonCheckMixin,
    ToolContext,
)
from slopmop.core.result import CheckResult, CheckStatus

# pyright rules we enforce for type completeness
TYPE_COMPLETENESS_RULES: Dict[str, str] = {
    "reportUnknownMemberType": "error",
    "reportUnknownVariableType": "error",
    "reportUnknownArgumentType": "error",
    "reportUnknownParameterType": "error",
    "reportUnknownLambdaType": "error",
}

# Maximum errors to show before truncating
MAX_ERRORS_TO_SHOW = 5
MAX_FILES_TO_SHOW = 10


def _find_pyright(project_root: str = "") -> Optional[str]:
    """Find pyright executable, checking project venv first."""
    if project_root:
        from slopmop.checks.base import find_tool

        return find_tool("pyright", project_root)
    return shutil.which("pyright")


def _detect_python_version(project_root: str) -> str:
    """Detect Python version from pyproject.toml or default to 3.11."""
    pyproject = Path(project_root) / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text()
            # Simple parse: look for python_requires or requires-python
            for line in content.splitlines():
                if "requires-python" in line or "python_requires" in line:
                    # Extract version like >=3.9 -> 3.9
                    import re

                    match = re.search(r"(\d+\.\d+)", line)
                    if match:
                        return match.group(1)
        except Exception:
            # Intentionally ignore all errors when reading/parsing pyproject.toml;
            # if anything goes wrong, we fall back to the default version below.
            pass
    return "3.11"


def _detect_venv_path(project_root: str) -> Tuple[Optional[str], Optional[str]]:
    """Detect venv path and name for pyright config.

    Returns (venvPath, venv) tuple for pyrightconfig.json.
    Priority: project-local venvs first, then VIRTUAL_ENV.
    """
    # Check project-local venvs first (highest priority)
    for venv_name in ["venv", ".venv"]:
        venv_path = Path(project_root) / venv_name
        if venv_path.exists():
            return project_root, venv_name

    # Fall back to VIRTUAL_ENV if no project venv exists
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env and Path(virtual_env).exists():
        venv_parent = str(Path(virtual_env).parent)
        venv_name = Path(virtual_env).name
        return venv_parent, venv_name

    return None, None


def _detect_source_dirs(project_root: str) -> List[str]:
    """Detect which directories contain Python source code."""
    candidates = ["src", "slopmop", "lib", "app"]
    found: List[str] = []

    for name in candidates:
        if Path(project_root, name).is_dir():
            found.append(name)

    if not found:
        # Look for any directory with __init__.py
        for entry in Path(project_root).iterdir():
            if (
                entry.is_dir()
                and (entry / "__init__.py").exists()
                and entry.name
                not in ("tests", "test", "venv", ".venv", "build", "dist")
            ):
                found.append(entry.name)

    return found or ["."]


class PythonTypeCheckingCheck(BaseCheck, PythonCheckMixin):
    """Type-completeness enforcement with pyright.

    Wraps pyright (Pylance's engine) to verify every variable,
    argument, and member access resolves to a known type. This
    goes beyond mypy's signature checks: where mypy asks "did
    you annotate functions?", pyright asks "can every consumer of
    this code reason about types without guessing?"

    Why this matters for AI agents: Python's loose typing lets
    humans move fast, but AI agents reading `results = []` must
    waste context-window tokens guessing the element type. With
    `results: List[Tuple[str, int]] = []`, the schema is free.

    Profiles: commit, pr

    Configuration:
      strict: True — enables the reportUnknown* family
          (MemberType, VariableType, ArgumentType, ParameterType,
          LambdaType). These are the type-completeness rules that
          ensure no variable has an "unknown" type. Without these,
          pyright only catches basic errors like missing imports.

    Common failures:
      reportUnknownVariableType: Annotate the variable.
          `results = []` → `results: List[str] = []`
      reportUnknownMemberType: The object's type is partially
          unknown, so its methods are too. Fix the root variable.
      reportUnknownArgumentType: You're passing an unknown-typed
          value to a function. Annotate the source variable.

    Re-validate:
      ./sm validate overconfidence:py-types --verbose
    """

    tool_context = ToolContext.SM_TOOL

    @property
    def name(self) -> str:
        return "py-types"

    @property
    def display_name(self) -> str:
        strict = self.config.get("strict", True)
        label = "strict" if strict else "basic"
        return f"🔬 Type Checking (pyright {label})"

    @property
    def category(self) -> GateCategory:
        return GateCategory.OVERCONFIDENCE

    @property
    def flaw(self) -> Flaw:
        return Flaw.OVERCONFIDENCE

    @property
    def depends_on(self) -> List[str]:
        return ["overconfidence:py-static-analysis"]

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="strict",
                field_type="boolean",
                default=True,
                description=(
                    "Enable type-completeness rules (reportUnknown* family). "
                    "When true, every variable must resolve to a known type — "
                    "no `Unknown` anywhere. This is what makes code "
                    "self-documenting for AI agents. When false, pyright only "
                    "catches basic errors like missing imports."
                ),
                permissiveness="true_is_stricter",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        return self.is_python_project(project_root)

    def skip_reason(self, project_root: str) -> str:
        """Return reason for skipping (delegates to PythonCheckMixin)."""
        return PythonCheckMixin.skip_reason(self, project_root)

    def _build_pyright_config(self, project_root: str) -> Dict[str, Any]:
        """Build pyrightconfig.json content for this run."""
        source_dirs = _detect_source_dirs(project_root)
        python_version = _detect_python_version(project_root)
        venv_path, venv_name = _detect_venv_path(project_root)

        config: Dict[str, Any] = {
            "typeCheckingMode": "standard",
            "include": source_dirs,
            "exclude": ["**/__pycache__", "**/node_modules"],
            "pythonVersion": python_version,
        }

        if venv_path and venv_name:
            config["venvPath"] = venv_path
            config["venv"] = venv_name

        # Add type-completeness rules if strict mode
        if self.config.get("strict", True):
            config.update(TYPE_COMPLETENESS_RULES)

        return config

    def run(self, project_root: str) -> CheckResult:
        """Run pyright type checking with prescriptive output."""
        start_time = time.time()

        # Check pyright is installed
        pyright_path = _find_pyright(project_root)
        if not pyright_path:
            return self._create_result(
                status=CheckStatus.WARNED,
                duration=time.time() - start_time,
                error="pyright not found",
                fix_suggestion="Install pyright: pip install pyright",
            )

        # Generate pyrightconfig.json in project root
        # (pyright resolves paths relative to config location)
        config_path = Path(project_root) / "pyrightconfig.json"
        had_existing_config = config_path.exists()
        backup_path: Optional[Path] = None
        wrote_temp_config = False

        try:
            if had_existing_config:
                backup_path = config_path.with_suffix(".json.sm_backup")
                config_path.rename(backup_path)

            pyright_config = self._build_pyright_config(project_root)
            config_path.write_text(json.dumps(pyright_config, indent=2))
            wrote_temp_config = True

            # Run pyright with JSON output
            result = self._run_command(
                [pyright_path, "--outputjson"],
                cwd=project_root,
                timeout=120,
            )

            duration = time.time() - start_time

            if result.timed_out:
                return self._create_result(
                    status=CheckStatus.FAILED,
                    duration=duration,
                    output=result.output,
                    error="Type checking timed out after 2 minutes",
                )

            return self._process_output(result.output, duration)

        finally:
            # Cleanup: only remove the config we wrote, not a pre-existing one
            if wrote_temp_config and config_path.exists():
                config_path.unlink()
            if backup_path and backup_path.exists():
                backup_path.rename(config_path)

    def _process_output(self, raw_output: str, duration: float) -> CheckResult:
        """Parse pyright JSON output and format prescriptive results."""
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                output=raw_output[:500],
                error="Failed to parse pyright output",
                fix_suggestion=(
                    "pyright may not be installed correctly. "
                    "Try: pip install --force-reinstall pyright"
                ),
            )

        diagnostics: List[Dict[str, Any]] = data.get("generalDiagnostics", [])
        summary = data.get("summary", {})
        error_count = summary.get("errorCount", 0)

        if error_count == 0:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=(
                    f"All types fully resolved across "
                    f"{summary.get('filesAnalyzed', '?')} files. "
                    f"Every variable, argument, and member has a known type."
                ),
            )

        # Group and format errors
        output = self._format_prescriptive_output(diagnostics, summary)
        fix_suggestion = self._build_fix_suggestion(diagnostics)

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=output,
            error=f"{error_count} type-completeness error(s) found",
            fix_suggestion=fix_suggestion,
        )

    def _format_prescriptive_output(
        self,
        diagnostics: List[Dict[str, Any]],
        summary: Dict[str, Any],
    ) -> str:
        """Format pyright output for AI agents.

        Groups errors by file, then by rule, showing exactly what needs
        fixing and where. Sorted by error count per file (biggest gaps first).
        """
        # Group by file
        by_file: Dict[str, List[Dict[str, Any]]] = {}
        rule_counts: Counter[str] = Counter()

        for diag in diagnostics:
            filepath = diag.get("file", "?")
            # Strip absolute path prefix
            if "/" in filepath:
                # Try to make relative
                for prefix in [os.getcwd() + "/", ""]:
                    if filepath.startswith(prefix) and prefix:
                        filepath = filepath[len(prefix) :]
                        break

            if filepath not in by_file:
                by_file[filepath] = []
            by_file[filepath].append(diag)

            rule = diag.get("rule", "unknown")
            rule_counts[rule] += 1

        # Sort files by error count (biggest gaps first)
        sorted_files = sorted(by_file.items(), key=lambda x: len(x[1]), reverse=True)

        parts: List[str] = []

        # Summary header
        total = sum(rule_counts.values())
        breakdown = ", ".join(
            f"{count} {rule}" for rule, count in rule_counts.most_common()
        )
        parts.append(f"{total} type-completeness errors: {breakdown}")
        parts.append("")

        # Per-file details
        files_shown = 0
        for filepath, file_diags in sorted_files:
            if files_shown >= MAX_FILES_TO_SHOW:
                remaining_files = len(sorted_files) - MAX_FILES_TO_SHOW
                remaining_errors = sum(
                    len(d) for _, d in sorted_files[MAX_FILES_TO_SHOW:]
                )
                parts.append(
                    f"  ... and {remaining_files} more files "
                    f"({remaining_errors} errors)"
                )
                break

            parts.append(f"  {filepath} ({len(file_diags)} errors)")

            # Group this file's errors by rule for clarity
            file_rules: Dict[str, List[Dict[str, Any]]] = {}
            for diag in file_diags:
                rule = diag.get("rule", "unknown")
                if rule not in file_rules:
                    file_rules[rule] = []
                file_rules[rule].append(diag)

            errors_shown = 0
            for rule, rule_diags in sorted(
                file_rules.items(), key=lambda x: len(x[1]), reverse=True
            ):
                for diag in rule_diags:
                    if errors_shown >= MAX_ERRORS_TO_SHOW:
                        remaining = len(file_diags) - errors_shown
                        parts.append(f"      ... and {remaining} more in this file")
                        break

                    line = diag.get("range", {}).get("start", {}).get("line", "?")
                    # pyright lines are 0-indexed, display as 1-indexed
                    if isinstance(line, int):
                        line = line + 1
                    msg = diag.get("message", "?")
                    # Take only first line — pyright often appends verbose details
                    msg = msg.split("\n")[0]
                    parts.append(f"    L{line}: [{rule}] {msg}")
                    errors_shown += 1
                else:
                    continue
                break  # Break outer loop too if we hit the max

            parts.append("")
            files_shown += 1

        return "\n".join(parts)

    @staticmethod
    def _build_fix_suggestion(diagnostics: List[Dict[str, Any]]) -> str:
        """Build targeted fix suggestions based on which rules fired."""
        rules: Counter[str] = Counter()
        for diag in diagnostics:
            rules[diag.get("rule", "unknown")] += 1

        suggestions: List[str] = ["Add type annotations to eliminate Unknown types."]

        if "reportUnknownVariableType" in rules:
            suggestions.append(
                "reportUnknownVariableType: Annotate local variables. "
                "results = [] → results: List[str] = []"
            )

        if "reportUnknownMemberType" in rules:
            suggestions.append(
                "reportUnknownMemberType: The root variable has Unknown type, "
                "causing all its method calls to be Unknown too. "
                "Fix the variable's type annotation to fix all cascading errors."
            )

        if "reportUnknownArgumentType" in rules:
            suggestions.append(
                "reportUnknownArgumentType: A function argument has Unknown type. "
                "Trace back to where the value was created and annotate that."
            )

        if "reportUnknownParameterType" in rules:
            suggestions.append(
                "reportUnknownParameterType: Add type annotations to function "
                "parameters. def foo(x) → def foo(x: str) -> None"
            )

        return " ".join(suggestions)
