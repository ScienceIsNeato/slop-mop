"""String duplication check using vendored find-duplicate-strings tool."""

import json
import os
import time
from pathlib import Path
from typing import Any, List

from slopmop.checks.base import BaseCheck, ConfigField, GateCategory
from slopmop.core.result import CheckResult, CheckStatus


class StringDuplicationCheck(BaseCheck):
    """Check for duplicate string literals across source files.

    This check wraps the vendored find-duplicate-strings tool to detect
    string literals that appear multiple times across files, suggesting
    they should be extracted to a constants module.
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
                default=5,
                description="Minimum occurrences to report a duplicate",
                min_value=2,
            ),
            ConfigField(
                name="min_file_count",
                field_type="integer",
                default=3,
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
        defaults = {
            "threshold": 5,
            "min_file_count": 3,
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
            extensions = []
            for pattern in include_patterns:
                if pattern.startswith("**/*."):
                    extensions.append(pattern[5:])  # Extract extension
                else:
                    extensions.append(pattern)
            if extensions:
                glob_pattern = f"**/*.{{{','.join(extensions)}}}"
            else:
                glob_pattern = include_patterns[0]

        cmd = [
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
        min_file_count = config.get("min_file_count", 2)
        min_length = config.get("min_length", 4)
        min_words = config.get("min_words", 3)

        filtered = []
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

        # Skip very short strings (< 8 chars are almost never worth extracting)
        if len(lower) < 8:
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
            files = finding.get("files", [])

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

    def run(self, project_root: str) -> CheckResult:
        """Run the string duplication check."""
        start_time = time.time()
        effective_config = self._get_effective_config()

        # Check if tool exists
        tool_path = self._get_tool_path()
        if not tool_path.exists():
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=time.time() - start_time,
                output="",
                error=(
                    "find-duplicate-strings tool not found. "
                    "Run: cd tools/find-duplicate-strings "
                    "&& npm install && npx tsc"
                ),
            )

        # Build and run command
        cmd = self._build_command(effective_config)

        try:
            result = self._run_command(cmd, cwd=project_root)
        except Exception as e:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=time.time() - start_time,
                output="",
                error=f"Failed to run find-duplicate-strings: {e}",
            )

        # Parse JSON output
        stdout = result.stdout.strip() if result.stdout else ""
        stderr = result.stderr.strip() if result.stderr else ""

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
