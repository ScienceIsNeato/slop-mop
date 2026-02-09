"""String duplication check using vendored find-duplicate-strings tool."""

import glob as globmod
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from slopmop.checks.base import BaseCheck, ConfigField, GateCategory
from slopmop.core.result import CheckResult, CheckStatus


class StringDuplicationCheck(BaseCheck):
    """Duplicate string literal detection.

    Wraps the vendored find-duplicate-strings tool to detect string
    literals repeated across multiple files. These are candidates
    for extraction to a constants module.

    Profiles: commit, pr

    Configuration:
      threshold: 2 — minimum occurrences to flag a string.
      min_file_count: 1 — minimum files the string must appear in.
      min_length: 8 — strings shorter than this are filtered out
          (short tokens like "id" or "name" repeat naturally).
      min_words: 3 — primary noise filter. Single-word strings
          like "store_true" or "description" are identifiers, not
          human-authored messages worth extracting.
      include_patterns: ["**/*.py"] — file globs to scan.
      ignore_patterns: test files, venv, build dirs — test
          strings naturally repeat without being a problem.

    Common failures:
      Duplicate strings found: Extract repeated strings to a
          constants.py module. The output shows each string,
          its count, and which files contain it.
      Tool not found: Requires Node.js. The tool is vendored
          in tools/find-duplicate-strings/.

    Re-validate:
      sm validate quality:string-duplication --verbose
    """

    @property
    def name(self) -> str:
        """Return check name."""
        return "string-duplication"

    @property
    def display_name(self) -> str:
        """Return human-readable display name."""
        return "🔤 String Duplication"

    @property
    def description(self) -> str:
        """Return check description."""
        return "Detect duplicate string literals that should be constants"

    @property
    def category(self) -> GateCategory:
        """Return check category."""
        return GateCategory.QUALITY

    @property
    def config_schema(self) -> List[ConfigField]:
        """Return config schema for this check."""
        return [
            ConfigField(
                name="threshold",
                field_type="integer",
                default=2,
                description="Minimum occurrences to report a duplicate",
                min_value=2,
            ),
            ConfigField(
                name="min_file_count",
                field_type="integer",
                default=1,
                description="Minimum number of files a string must appear in",
                min_value=1,
            ),
            ConfigField(
                name="min_length",
                field_type="integer",
                default=8,
                description="Minimum string length to consider",
                min_value=1,
            ),
            ConfigField(
                name="min_words",
                field_type="integer",
                default=3,
                description="Minimum word count to consider (filters single-word identifiers)",
                min_value=1,
            ),
            ConfigField(
                name="include_patterns",
                field_type="string[]",
                default=["**/*.py"],
                description="Glob patterns for files to scan",
            ),
            ConfigField(
                name="ignore_patterns",
                field_type="string[]",
                default=[
                    "**/node_modules/**",
                    "**/.venv/**",
                    "**/venv/**",
                    "**/__pycache__/**",
                    "**/.git/**",
                    "**/*.egg-info/**",
                    "**/test_*",
                    "**/tests/**",
                    "**/conftest.py",
                ],
                description="Glob patterns to ignore",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        """Check if there are source files to analyze."""
        root = Path(project_root)
        # Check for Python files by default
        return any(root.rglob("*.py"))

    def skip_reason(self, project_root: str) -> str:
        """Return reason for skipping - no Python source files."""
        return "No Python files found to scan for duplicate strings"

    def _get_tool_path(self) -> Path:
        """Get the path to the vendored find-duplicate-strings tool."""
        # Navigate from this file to tools/find-duplicate-strings
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent.parent
        return (
            project_root
            / "tools"
            / "find-duplicate-strings"
            / "lib"
            / "cli"
            / "index.js"
        )

    def _get_effective_config(self) -> dict[str, Any]:
        """Get effective configuration with defaults."""
        defaults: dict[str, Any] = {
            "threshold": 2,
            "min_file_count": 1,
            "min_length": 8,
            "min_words": 3,
            "include_patterns": ["**/*.py"],
            "ignore_patterns": [
                "**/node_modules/**",
                "**/.venv/**",
                "**/venv/**",
                "**/__pycache__/**",
                "**/.git/**",
                "**/*.egg-info/**",
                "**/test_*",
                "**/tests/**",
                "**/conftest.py",
            ],
        }
        return {**defaults, **self.config}

    def _build_command(self, config: dict[str, Any]) -> list[str]:
        """Build the find-duplicate-strings command."""
        tool_path = self._get_tool_path()
        threshold = config.get("threshold", 3)
        include_patterns = config.get("include_patterns", ["**/*.py"])
        ignore_patterns = config.get("ignore_patterns", [])

        # Build glob pattern - join multiple patterns for the tool
        # The tool accepts a single glob pattern, so we use brace expansion
        if len(include_patterns) == 1:
            glob_pattern = include_patterns[0]
        else:
            # Create brace expansion: **/*.{py,js,ts}
            extensions: list[str] = []
            for pattern in include_patterns:
                if pattern.startswith("**/*."):
                    extensions.append(pattern[5:])  # Extract extension
                else:
                    extensions.append(pattern)
            if extensions:
                glob_pattern = f"**/*.{{{','.join(extensions)}}}"
            else:
                glob_pattern = include_patterns[0]

        cmd: list[str] = [
            "node",
            str(tool_path),
            glob_pattern,
            "--threshold",
            str(threshold),
            "--json",
        ]

        if ignore_patterns:
            cmd.extend(["--ignore", ",".join(ignore_patterns)])

        return cmd

    def _filter_results(
        self, findings: list[dict[str, Any]], config: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Filter findings based on configuration."""
        min_file_count = cast(int, config.get("min_file_count", 2))
        min_length = cast(int, config.get("min_length", 4))
        min_words = cast(int, config.get("min_words", 3))

        filtered: list[dict[str, Any]] = []
        for finding in findings:
            key = finding.get("key", "")
            file_count = finding.get("fileCount", 0)

            # Skip strings that are too short
            if len(key) < min_length:
                continue

            # Skip strings with fewer words than the minimum
            # This is the primary noise filter — single-word strings like
            # "store_true", "description", "__main__" are identifiers,
            # not human-authored messages worth extracting to constants
            word_count = len(key.split())
            if word_count < min_words:
                continue

            # Skip strings that only appear in one file
            if file_count < min_file_count:
                continue

            # Skip common noise patterns
            if self._is_noise(key):
                continue

            filtered.append(finding)

        return filtered

    def _is_noise(self, value: str) -> bool:
        """Check if string is common noise that should be ignored.

        Filters out short tokens, common programming terms, file names,
        CLI flags, and other strings that naturally repeat across files
        without indicating a constants-extraction opportunity.
        """
        lower = value.lower().strip()

        # Skip very short strings — already filtered by min_length in
        # _filter_results, but _is_noise is a secondary guard.
        # Uses the config default (min_length) rather than a magic number.
        if len(lower) < self._get_effective_config().get("min_length", 8):
            return True

        # File paths / basenames that naturally repeat
        if lower.endswith((".py", ".js", ".ts", ".json", ".md", ".txt", ".cfg")):
            return True

        # CLI flags
        if lower.startswith("-"):
            return True

        # Looks like a module/package import path
        if "." in lower and all(part.isidentifier() for part in lower.split(".")):
            return True

        return False

    def _format_findings(self, findings: list[dict[str, Any]]) -> str:
        """Format findings into human-readable output."""
        if not findings:
            return "No duplicate strings found that meet the threshold."

        lines = [
            f"Found {len(findings)} duplicate string(s) "
            "that should be extracted to constants:",
            "",
        ]

        for finding in findings[:20]:  # Limit output to top 20
            key = finding.get("key", "")
            count = finding.get("count", 0)
            file_count = finding.get("fileCount", 0)
            files: list[str] = cast(list[str], finding.get("files", []))

            # Truncate long strings
            display_key = key if len(key) <= 50 else key[:47] + "..."
            lines.append(
                f'  "{display_key}": {count} occurrences in {file_count} files'
            )

            # Show first 3 files
            for file_path in files[:3]:
                # Make path relative if possible
                try:
                    rel_path = os.path.relpath(file_path)
                except ValueError:
                    rel_path = file_path
                lines.append(f"    - {rel_path}")
            if len(files) > 3:
                lines.append(f"    ... and {len(files) - 3} more files")
            lines.append("")

        if len(findings) > 20:
            remaining = len(findings) - 20
            lines.append(f"... and {remaining} more duplicate strings")

        lines.append("")
        lines.append("Consider extracting these to a constants.py module.")

        return "\n".join(lines)

    def _get_strip_docstrings_path(self) -> Path:
        """Get path to the strip_docstrings.py helper script."""
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent.parent
        return project_root / "tools" / "find-duplicate-strings" / "strip_docstrings.py"

    def _preprocess_python_files(
        self, project_root: str, config: Dict[str, Any]
    ) -> Optional[str]:
        """Pre-process Python files by stripping docstrings into a temp dir.

        Uses Python's tokenize module (via strip_docstrings.py) which
        correctly handles all edge cases that regex-based approaches
        cannot: internal quotes, escaped characters, nested patterns.

        Returns the temp directory path, or None if no .py files found.
        The caller is responsible for cleaning up the temp dir.
        """
        include_patterns = config.get("include_patterns", ["**/*.py"])
        ignore_patterns = config.get("ignore_patterns", [])

        # Only pre-process if we're scanning Python files
        has_python_patterns = any(
            p.endswith(".py") or p.endswith(".py}") for p in include_patterns
        )
        if not has_python_patterns:
            return None

        # Find all .py files that match include patterns
        py_files: list[str] = []
        for pattern in include_patterns:
            if not pattern.endswith(".py"):
                continue
            matched = globmod.glob(os.path.join(project_root, pattern), recursive=True)
            for f in matched:
                # Apply ignore patterns
                rel = os.path.relpath(f, project_root)
                skip = False
                for ign in ignore_patterns:
                    if globmod.fnmatch.fnmatch(rel, ign):  # type: ignore[attr-defined]
                        skip = True
                        break
                if not skip:
                    py_files.append(f)

        if not py_files:
            return None

        # Create temp dir and strip docstrings into it
        tmp_dir = tempfile.mkdtemp(prefix="sm-string-dup-")
        strip_script = self._get_strip_docstrings_path()

        # Use the strip_docstrings module directly (same Python process)
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "strip_docstrings", str(strip_script)
        )
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.batch_strip(py_files, project_root, tmp_dir)

        return tmp_dir

    def run(self, project_root: str) -> CheckResult:
        """Run the string duplication check."""
        start_time = time.time()
        effective_config = self._get_effective_config()

        # Check if tool exists
        tool_path = self._get_tool_path()
        if not tool_path.exists():
            return self._create_result(
                status=CheckStatus.WARNED,
                duration=time.time() - start_time,
                output="",
                error=(
                    "find-duplicate-strings tool not found. "
                    "Run: cd tools/find-duplicate-strings "
                    "&& npm install && npx tsc"
                ),
            )

        # Pre-process Python files: strip docstrings into temp dir
        # so the Node tool scans clean source without triple-quoted noise
        tmp_dir = self._preprocess_python_files(project_root, effective_config)
        scan_root = tmp_dir if tmp_dir else project_root

        try:
            # Build and run command against (possibly pre-processed) source
            cmd = self._build_command(effective_config)
            result = self._run_command(cmd, cwd=scan_root)
        except Exception as e:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=time.time() - start_time,
                output="",
                error=f"Failed to run find-duplicate-strings: {e}",
            )
        finally:
            # Always clean up temp dir
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        # Parse JSON output — remap temp paths back to originals
        stdout = result.stdout.strip() if result.stdout else ""
        stderr = result.stderr.strip() if result.stderr else ""

        # If we used a temp dir, remap paths in the output back to project_root
        if tmp_dir and stdout:
            stdout = stdout.replace(tmp_dir, project_root)

        if not stdout:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=time.time() - start_time,
                output="No duplicate strings found.",
            )

        try:
            findings = json.loads(stdout)
        except json.JSONDecodeError as e:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=time.time() - start_time,
                output=stdout,
                error=f"Failed to parse tool output: {e}\nStderr: {stderr}",
            )

        # Filter and format results
        filtered = self._filter_results(findings, effective_config)
        output = self._format_findings(filtered)

        if filtered:
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=time.time() - start_time,
                output=output,
                fix_suggestion=(
                    "Extract duplicate strings to a constants.py module "
                    "to improve maintainability."
                ),
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=time.time() - start_time,
            output="No significant duplicate strings found.",
        )
