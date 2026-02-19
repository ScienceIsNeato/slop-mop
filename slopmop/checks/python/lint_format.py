"""Python lint and format check using black, isort, autoflake, and flake8.

This check:
1. Auto-removes unused imports with autoflake
2. Auto-fixes formatting with black
3. Auto-fixes import order with isort
4. Checks for critical lint errors with flake8
"""

import os
import sys
import time
from typing import List, Optional

from slopmop.checks.base import (
    BaseCheck,
    ConfigField,
    Flaw,
    GateCategory,
    PythonCheckMixin,
)
from slopmop.core.result import CheckResult, CheckStatus


class PythonLintFormatCheck(BaseCheck, PythonCheckMixin):
    """Python code formatting and lint enforcement.

    Wraps autoflake, black, isort, and flake8 to enforce consistent
    style and catch critical errors. Auto-fix runs autoflake (remove
    unused imports), black (formatting), and isort (import order)
    before checking with flake8.

    Profiles: commit, pr, quick

    Configuration:
      line_length: 88 — black's default; wide enough for modern
          screens, narrow enough to diff side-by-side.

    Common failures:
      Formatting drift: Run `sm validate laziness:py-lint` with
          auto-fix enabled. Black and isort will fix in place.
      Unused imports: autoflake removes them automatically during
          auto-fix. If you need to keep one, add `# noqa: F401`.
      Flake8 E9/F63/F7/F82: These are critical errors (syntax,
          assertion on tuples, undefined names). Fix the code.

    Re-validate:
      ./sm validate laziness:py-lint --verbose
    """

    @property
    def name(self) -> str:
        return "py-lint"

    @property
    def display_name(self) -> str:
        return "🎨 Lint & Format (autoflake, black, isort, flake8)"

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
                name="line_length",
                field_type="integer",
                default=88,
                description="Maximum line length for black",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        return self.is_python_project(project_root)

    def can_auto_fix(self) -> bool:
        return True

    def auto_fix(self, project_root: str) -> bool:
        """Auto-fix formatting issues with autoflake, black, and isort."""
        fixed = False

        # Find Python source directories to format
        targets = self._get_python_targets(project_root)
        if not targets:
            targets = ["."]

        # Run autoflake first to remove unused imports
        result = self._run_command(
            [
                sys.executable,
                "-m",
                "autoflake",
                "--in-place",
                "--remove-all-unused-imports",
                "--recursive",
                "--exclude=venv,__pycache__,.git,.venv,build,dist,node_modules",
                ".",
            ],
            cwd=project_root,
            timeout=60,
        )
        if result.success:
            fixed = True

        # Run black on each target
        # Use sys.executable -m to ensure black runs under the same Python
        # interpreter (and venv) as slop-mop, avoiding broken system installs.
        for target in targets:
            result = self._run_command(
                [sys.executable, "-m", "black", "--line-length", "88", target],
                cwd=project_root,
                timeout=60,
            )
            if result.success:
                fixed = True

        # Run isort — skip hidden directories to match _check_isort behaviour
        # Use sys.executable -m to match the black approach above.
        result = self._run_command(
            [
                sys.executable,
                "-m",
                "isort",
                "--profile",
                "black",
                "--skip=venv",
                "--skip=.venv",
                "--skip=build",
                "--skip=dist",
                "--skip-glob=.*",
                ".",
            ],
            cwd=project_root,
            timeout=60,
        )
        if result.success:
            fixed = True

        return fixed

    def _get_python_targets(self, project_root: str) -> List[str]:
        """Get Python directories to lint/format."""
        targets: List[str] = []
        exclude_dirs = {"venv", ".venv", "build", "dist", "node_modules", ".git"}

        for entry in os.listdir(project_root):
            if entry in exclude_dirs or entry.startswith("."):
                continue
            entry_path = os.path.join(project_root, entry)
            if os.path.isdir(entry_path):
                # Check if it's a Python package or has Python files
                if os.path.exists(os.path.join(entry_path, "__init__.py")):
                    targets.append(entry)
                elif entry in ("src", "tests", "test", "lib"):
                    targets.append(entry)
            elif entry.endswith(".py"):
                targets.append(entry)

        return targets

    def run(self, project_root: str) -> CheckResult:
        """Run lint and format checks."""
        start_time = time.time()
        issues: List[str] = []
        output_parts: List[str] = []

        # Check 1: Black formatting
        black_result = self._check_black(project_root)
        if black_result:
            issues.append(black_result)
            output_parts.append(f"Black: {black_result}")
        else:
            output_parts.append("Black: ✅ Formatting OK")

        # Check 2: Isort imports
        isort_result = self._check_isort(project_root)
        if isort_result:
            issues.append(isort_result)
            output_parts.append(f"Isort: {isort_result}")
        else:
            output_parts.append("Isort: ✅ Import order OK")

        # Check 3: Flake8 critical errors
        flake8_result = self._check_flake8(project_root)
        if flake8_result:
            issues.append(flake8_result)
            output_parts.append(f"Flake8: {flake8_result}")
        else:
            output_parts.append("Flake8: ✅ No critical errors")

        duration = time.time() - start_time

        if issues:
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output="\n".join(output_parts),
                error=f"{len(issues)} issue(s) found",
                fix_suggestion="Run: black . && isort . to auto-fix formatting",
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output="\n".join(output_parts),
        )

    def _check_black(self, project_root: str) -> Optional[str]:
        """Check black formatting.

        In normal operation, auto_fix() runs first, so failures here are typically:
        - Syntax errors that black can't parse
        - Files black refuses to format
        If --no-auto-fix was used, may also see "would reformat" messages.
        """
        targets = self._get_python_targets(project_root)
        if not targets:
            return None  # No Python targets found

        # Run black --check on all targets, collect any failures
        all_output: List[str] = []
        any_failed = False

        for target in targets:
            result = self._run_command(
                [sys.executable, "-m", "black", "--check", "--line-length", "88", target],
                cwd=project_root,
                timeout=60,
            )
            if not result.success:
                any_failed = True
                if result.output:
                    # Black outputs useful info like:
                    # "error: cannot format file.py: Cannot parse: 1:11: message"
                    # "would reformat file.py"
                    all_output.append(result.output.strip())

        if not any_failed:
            return None

        # Combine and return black's actual output (it includes file:line info)
        combined = "\n".join(all_output)
        if combined:
            return combined
        return "Formatting check failed"

    def _check_isort(self, project_root: str) -> Optional[str]:
        """Check isort import order."""
        result = self._run_command(
            [
                sys.executable,
                "-m",
                "isort",
                "--check-only",
                "--profile",
                "black",
                "--skip=venv",
                "--skip=.venv",
                "--skip=build",
                "--skip=dist",
                # Skip hidden directories (e.g. .claude/, .git/) that contain
                # tool infrastructure rather than project source code.
                "--skip-glob=.*",
                ".",
            ],
            cwd=project_root,
            timeout=60,
        )

        if not result.success:
            # isort outputs "ERROR: file.py ..." or "Skipped X files"
            # Extract file paths from output for actionable feedback
            output = result.output if result.output else ""
            error_lines = [
                line for line in output.split("\n") if line.startswith("ERROR:")
            ]
            if error_lines:
                # Extract file paths from "ERROR: path/to/file.py ..." lines
                file_names: List[str] = []
                for line in error_lines:
                    parts = line.split(" ")
                    if len(parts) >= 2:
                        file_names.append(str(parts[1]))
                if len(file_names) <= 5:
                    files_str = "\n  ".join(file_names)
                    return f"Import order issues:\n  {files_str}"
                else:
                    shown = "\n  ".join(file_names[:5])
                    remaining = len(file_names) - 5
                    return (
                        f"Import order issues:\n  {shown}\n  ... and {remaining} more"
                    )
            return "Import order issues found"
        return None

    def _check_flake8(self, project_root: str) -> Optional[str]:
        """Check for critical flake8 errors.

        Scans only the configured include_dirs or auto-detected Python source
        directories.  Hidden directories (e.g. .claude/, .git/) are excluded
        via --extend-exclude since they contain tool infrastructure, not
        project source code.  If include_dirs explicitly includes hidden
        directories, they will still be scanned.
        """
        # Determine targets: configured include_dirs > auto-detected Python dirs
        include_dirs = self.config.get("include_dirs")
        if include_dirs:
            targets: List[str] = (
                [include_dirs] if isinstance(include_dirs, str) else list(include_dirs)
            )
        else:
            targets = self._get_python_targets(project_root)

        if not targets:
            return None  # No Python source directories to check

        # Build exclude list: base defaults + any configured exclude_dirs
        # Use --extend-exclude to preserve flake8's built-in defaults
        # (__pycache__, .tox, .nox, etc.) while adding our custom excludes.
        base_excludes = [
            "venv",
            ".venv",
            "build",
            "dist",
            "node_modules",
            ".git",
            "cursor-rules",
            "tools",
            "__pycache__",
            ".*",  # Hidden directories
        ]
        config_excludes = self.config.get("exclude_dirs", [])
        if isinstance(config_excludes, str):
            config_excludes = [config_excludes]
        all_excludes = base_excludes + list(config_excludes)

        result = self._run_command(
            [
                sys.executable,
                "-m",
                "flake8",
                "--select=E9,F63,F7,F82,F401",
                "--max-line-length=88",
                f"--extend-exclude={','.join(all_excludes)}",
            ]
            + targets,
            cwd=project_root,
            timeout=60,
        )

        if not result.success and result.output.strip():
            lines = result.output.strip().split("\n")
            return f"{len(lines)} critical error(s):\n" + "\n".join(lines[:5])
        return None
