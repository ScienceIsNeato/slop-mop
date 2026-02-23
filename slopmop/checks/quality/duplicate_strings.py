"""String duplication check using vendored find-duplicate-strings tool."""

import glob as globmod
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, cast

from slopmop.checks.base import BaseCheck, ConfigField, Flaw, GateCategory
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
      ./sm validate quality:string-duplication --verbose
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
        return GateCategory.MYOPIA

    @property
    def flaw(self) -> Flaw:
        """Return the AI flaw this check guards against."""
        return Flaw.MYOPIA

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
                permissiveness="lower_is_stricter",
            ),
            ConfigField(
                name="min_file_count",
                field_type="integer",
                default=1,
                description="Minimum number of files a string must appear in",
                min_value=1,
                permissiveness="lower_is_stricter",
            ),
            ConfigField(
                name="min_length",
                field_type="integer",
                default=8,
                description="Minimum string length to consider",
                min_value=1,
                permissiveness="lower_is_stricter",
            ),
            ConfigField(
                name="min_words",
                field_type="integer",
                default=3,
                description="Minimum word count to consider (filters single-word identifiers)",
                min_value=1,
                permissiveness="lower_is_stricter",
            ),
            ConfigField(
                name="include_patterns",
                field_type="string[]",
                default=["**/*.py"],
                description="Glob patterns for files to scan",
                permissiveness="more_is_stricter",
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
                permissiveness="fewer_is_stricter",
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

    def _get_tool_path(self, project_root: str = "") -> Optional[Path]:
        """Find the find-duplicate-strings tool.

        Searches in order:
        1. The target project's tools/ directory (works for projects
           that vendor the tool, or when sm is pip-installed)
        2. The slopmop package source tree (works in a git checkout)
        3. Global npm installation via shutil.which

        Returns the path to index.js, or None if not found.
        """
        tool_rel = Path("tools") / "find-duplicate-strings" / "lib" / "cli" / "index.js"

        # 1. Target project's tools/ directory
        if project_root:
            candidate = Path(project_root) / tool_rel
            if candidate.exists():
                return candidate

        # 2. slopmop package source tree (development checkout)
        pkg_root = Path(__file__).parent.parent.parent.parent
        candidate = pkg_root / tool_rel
        if candidate.exists():
            return candidate

        # 3. Global npm: check if find-duplicate-strings is on PATH
        global_bin = shutil.which("find-duplicate-strings")
        if global_bin:
            return Path(global_bin)

        return None

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

    def _build_command(
        self, config: dict[str, Any], tool_path: Optional[Path] = None
    ) -> list[str]:
        """Build the find-duplicate-strings command."""
        if tool_path is None:
            tool_path = self._get_tool_path() or Path("find-duplicate-strings")
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

        cmd: list[str] = (
            # If tool_path points to a .js file, invoke via node;
            # if it's a global binary (from shutil.which), call directly
            ["node", str(tool_path)]
            if str(tool_path).endswith(".js")
            else [str(tool_path)]
        )
        cmd += [
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

    def _get_strip_docstrings_path(self, project_root: str = "") -> Optional[Path]:
        """Find the strip_docstrings.py helper script.

        Searches in the same locations as _get_tool_path:
        1. Target project's tools/ directory
        2. slopmop package source tree
        """
        script_rel = Path("tools") / "find-duplicate-strings" / "strip_docstrings.py"

        if project_root:
            candidate = Path(project_root) / script_rel
            if candidate.exists():
                return candidate

        pkg_root = Path(__file__).parent.parent.parent.parent
        candidate = pkg_root / script_rel
        if candidate.exists():
            return candidate

        return None

    def _load_strip_function(
        self, project_root: str = ""
    ) -> Optional[Callable[[str], str]]:
        """Dynamically load the strip_docstrings function.

        Returns the function, or None if the module can't be loaded.
        The script lives outside the slopmop package tree, so we
        use importlib to load it by file path.
        """
        import importlib.util

        script_path = self._get_strip_docstrings_path(project_root)
        if script_path is None or not script_path.exists():
            return None

        spec = importlib.util.spec_from_file_location(
            "strip_docstrings", str(script_path)
        )
        if not (spec and spec.loader):
            return None

        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.strip_docstrings  # type: ignore[no-any-return]

    def _preprocess_python_files(
        self, project_root: str, config: Dict[str, Any]
    ) -> Optional[str]:
        """Strip docstrings from Python files into a temp directory.

        Creates lightweight copies with docstrings blanked so the Node
        tool scans clean source.  Line numbers are preserved (multi-line
        docstrings become ``pass`` + blank lines matching the original
        span), so reported positions stay correct.

        We use a temp directory rather than modifying files in-place
        because quality checks run in parallel — an in-place approach
        would race with the lint-format check that also reads source.

        Returns the temp directory path, or None if no .py files found.
        The caller must clean up the temp dir (shutil.rmtree).
        """
        include_patterns = config.get("include_patterns", ["**/*.py"])
        ignore_patterns = config.get("ignore_patterns", [])

        # Only process Python files
        has_python = any(
            p.endswith(".py") or p.endswith(".py}") for p in include_patterns
        )
        if not has_python:
            return None

        strip_fn = self._load_strip_function(project_root)
        if strip_fn is None:
            return None

        # Find all matching .py files
        py_files: list[str] = []
        for pattern in include_patterns:
            if not pattern.endswith(".py"):
                continue
            matched = globmod.glob(os.path.join(project_root, pattern), recursive=True)
            for f in matched:
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

        # Write stripped copies into temp dir, preserving relative paths
        tmp_dir = tempfile.mkdtemp(prefix="sm-string-dup-")
        src_root = Path(project_root).resolve()

        for filepath in py_files:
            try:
                with open(filepath, encoding="utf-8", errors="replace") as fh:
                    source = fh.read()
                stripped = strip_fn(source)
            except Exception:
                continue  # can't read or tokenize — skip this file

            try:
                rel_path = Path(filepath).resolve().relative_to(src_root)
            except ValueError:
                rel_path = Path(Path(filepath).name)

            out_path = Path(tmp_dir) / rel_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(stripped, encoding="utf-8")

        return tmp_dir

    def run(self, project_root: str) -> CheckResult:
        """Run the string duplication check."""
        start_time = time.time()
        effective_config = self._get_effective_config()

        # Check if tool exists
        tool_path = self._get_tool_path(project_root)
        if tool_path is None:
            return self._create_result(
                status=CheckStatus.WARNED,
                duration=time.time() - start_time,
                output="",
                error=(
                    "find-duplicate-strings tool not installed locally. "
                    "Run: sm init (sets up tools/) or install globally: "
                    "npm install -g find-duplicate-strings"
                ),
            )

        # Strip docstrings into a temp directory so the Node tool scans
        # clean source.  Line numbers are preserved (multi-line docstrings
        # become pass + \n).  We can't modify files in-place because
        # quality checks run in parallel and lint would see modified files.
        tmp_dir = self._preprocess_python_files(project_root, effective_config)
        scan_root = tmp_dir if tmp_dir else project_root

        try:
            cmd = self._build_command(effective_config, tool_path)
            result = self._run_command(cmd, cwd=scan_root)
        except Exception as e:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=time.time() - start_time,
                output="",
                error=f"Failed to run find-duplicate-strings: {e}",
            )
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        # Parse JSON output — remap temp paths back to originals
        stdout = result.stdout.strip() if result.stdout else ""
        stderr = result.stderr.strip() if result.stderr else ""

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
