"""Dead code detection using vulture.

Identifies unused functions, classes, imports, variables, and
unreachable code via static AST analysis. Wraps vulture in the
same tool-wrapper pattern as complexity.py wraps radon.

Note: This is a cross-cutting quality check — dead code is a
universal concern regardless of project type.
"""

import os
import re
import time
from typing import List, Tuple

from slopmop.checks.base import BaseCheck, ConfigField, GateCategory, find_tool
from slopmop.core.result import CheckResult, CheckStatus

DEFAULT_MIN_CONFIDENCE = 80
MAX_FINDINGS_TO_SHOW = 15


class DeadCodeCheck(BaseCheck):
    """Dead code detection via static AST analysis.

    Wraps vulture to find unused functions, classes, imports,
    variables, and unreachable code. Uses a confidence threshold
    to filter false positives — vulture reports confidence based
    on how certain it is that code is truly unused.

    Profiles: commit, pr

    Configuration:
      min_confidence: 80 — vulture's confidence score (60-100).
          At 80% we catch genuinely dead code while ignoring
          dynamically-referenced symbols that vulture can't trace.
      exclude_patterns: test files, venv, build dirs, cursor-rules
          — these naturally contain "unused" symbols (test helpers,
          vendored code, generated files).
      src_dirs: ["."] — scan everything by default.
      whitelist_file: "" — optional vulture whitelist for known
          false positives.

    Common failures:
      Unused function/class: Delete it, or add to vulture whitelist
          if it's used dynamically (e.g., via getattr, entrypoints).
      Unused import: Remove it or mark with # noqa if needed for
          side effects.

    Re-validate:
      sm validate quality:dead-code --verbose
    """

    @property
    def name(self) -> str:
        return "dead-code"

    @property
    def display_name(self) -> str:
        return f"💀 Dead Code (≥{self._get_min_confidence()}% confidence)"

    @property
    def category(self) -> GateCategory:
        return GateCategory.QUALITY

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="min_confidence",
                field_type="integer",
                default=DEFAULT_MIN_CONFIDENCE,
                description="Minimum confidence to report (60-100)",
            ),
            ConfigField(
                name="exclude_patterns",
                field_type="string[]",
                default=[
                    "**/venv/**",
                    "**/.venv/**",
                    "**/node_modules/**",
                    "**/test_*",
                    "**/tests/**",
                    "**/conftest.py",
                    "**/*.egg-info/**",
                    "**/build/**",
                    "**/dist/**",
                    "**/cursor-rules/**",
                ],
                description="Glob patterns to exclude from scanning",
            ),
            ConfigField(
                name="src_dirs",
                field_type="string[]",
                default=["."],
                description="Directories to scan for dead code",
            ),
            ConfigField(
                name="whitelist_file",
                field_type="string",
                default="",
                description="Path to vulture whitelist file",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        """Applicable if there are Python files to scan."""
        from pathlib import Path

        root = Path(project_root)
        return any(root.rglob("*.py"))

    def _get_min_confidence(self) -> int:
        """Get configured minimum confidence threshold."""
        return self.config.get("min_confidence", DEFAULT_MIN_CONFIDENCE)

    def _get_exclude_patterns(self) -> List[str]:
        """Get configured exclude patterns."""
        return self.config.get(
            "exclude_patterns",
            [
                "**/venv/**",
                "**/.venv/**",
                "**/node_modules/**",
                "**/test_*",
                "**/tests/**",
                "**/conftest.py",
                "**/*.egg-info/**",
                "**/build/**",
                "**/dist/**",
                "**/cursor-rules/**",
            ],
        )

    def _get_src_dirs(self, project_root: str) -> List[str]:
        """Get directories to scan, validated against filesystem."""
        configured = self.config.get("src_dirs", ["."])
        return [d for d in configured if os.path.isdir(os.path.join(project_root, d))]

    def _build_command(self, project_root: str) -> List[str]:
        """Build the vulture command with all configured options."""
        src_dirs = self._get_src_dirs(project_root)
        if not src_dirs:
            src_dirs = ["."]

        vulture_path = find_tool("vulture", project_root) or "vulture"
        cmd = [vulture_path] + src_dirs
        cmd.extend(["--min-confidence", str(self._get_min_confidence())])

        exclude_patterns = self._get_exclude_patterns()
        if exclude_patterns:
            # Vulture --exclude takes comma-separated directory/file names
            # Convert glob patterns to simple names for vulture
            exclude_names = self._glob_patterns_to_vulture_excludes(exclude_patterns)
            if exclude_names:
                cmd.extend(["--exclude", ",".join(exclude_names)])

        whitelist = self.config.get("whitelist_file", "")
        if whitelist:
            whitelist_path = os.path.join(project_root, whitelist)
            if os.path.isfile(whitelist_path):
                cmd.append(whitelist_path)

        return cmd

    def _glob_patterns_to_vulture_excludes(self, patterns: List[str]) -> List[str]:
        """Convert glob patterns to vulture-compatible exclude names.

        Vulture's --exclude accepts comma-separated names that are matched
        against directory and file names using fnmatch. Extract the
        meaningful name from each pattern, preserving any filename-level
        wildcards (e.g. **/test_* → test_*).
        """
        excludes: List[str] = []
        for pattern in patterns:
            # Split on / and take the last non-** component
            parts = [p for p in pattern.split("/") if p != "**"]
            name = parts[-1] if parts else ""
            if name and name not in excludes:
                excludes.append(name)
        return excludes

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()
        cmd = self._build_command(project_root)
        result = self._run_command(cmd, cwd=project_root, timeout=120)
        duration = time.time() - start_time

        # Handle tool not installed - this indicates a broken slop-mop installation
        # since vulture is a core dependency of slop-mop
        if result.returncode == 127 or (
            result.returncode == -1 and "Command not found" in result.stderr
        ):
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                error="vulture not found (slop-mop installation issue)",
                fix_suggestion="Reinstall slop-mop: pip install -e /path/to/slop-mop\nvulture should be installed as a slop-mop dependency.",
            )

        # Handle timeout
        if result.timed_out:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                error="vulture timed out",
                fix_suggestion="Try running on a smaller scope or increase timeout.",
            )

        # Handle unexpected errors (non-zero return that isn't dead code findings)
        if result.returncode not in (0, 1, 3):  # vulture uses 1/3 for findings
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                error=f"vulture failed with exit code {result.returncode}",
                fix_suggestion="Check vulture output for errors.",
                output=result.stderr or result.output,
            )

        findings = self._parse_findings(result.output)

        if not findings:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output="No dead code detected",
            )

        output = self._format_findings(findings)
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=output,
            error=f"{len(findings)} dead code finding(s)",
            fix_suggestion="Remove unused code or add to vulture whitelist.",
        )

    def _parse_findings(self, output: str) -> List[Tuple[str, int, str, int]]:
        """Parse vulture output lines into structured findings.

        Each line: file.py:42: unused function 'foo' (80% confidence)
        Returns: [(file, line, description, confidence), ...]
        """
        findings: List[Tuple[str, int, str, int]] = []
        pattern = re.compile(r"^(.+?):(\d+): (.+?) \((\d+)% confidence\)$")
        for line in output.splitlines():
            line = line.strip()
            match = pattern.match(line)
            if match:
                filepath = match.group(1)
                lineno = int(match.group(2))
                description = match.group(3)
                confidence = int(match.group(4))
                findings.append((filepath, lineno, description, confidence))
        return findings

    def _format_findings(self, findings: List[Tuple[str, int, str, int]]) -> str:
        """Format findings into prescriptive output."""
        lines = [f"Found {len(findings)} dead code issue(s):", ""]
        for filepath, lineno, description, confidence in findings[
            :MAX_FINDINGS_TO_SHOW
        ]:
            lines.append(f"  {filepath}:{lineno}: {description} ({confidence}%)")

        if len(findings) > MAX_FINDINGS_TO_SHOW:
            remaining = len(findings) - MAX_FINDINGS_TO_SHOW
            lines.append(f"\n  ... and {remaining} more")

        return "\n".join(lines)
