"""Lines of code enforcement check.

Enforces maximum file length and function/method length limits.
Helps prevent bloated files and overly complex functions that are
difficult for both humans and LLMs to reason about.

This is a cross-cutting quality check that applies to all source files.
"""

import logging
import re
import time
from pathlib import Path
from typing import List, Set, Tuple

from slopmop.checks.base import BaseCheck, ConfigField, GateCategory
from slopmop.core.result import CheckResult, CheckStatus

logger = logging.getLogger(__name__)

# Default limits
DEFAULT_MAX_FILE_LINES = 1000
DEFAULT_MAX_FUNCTION_LINES = 100

# File extensions to check (source files only)
SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".swift",
    ".kt",
    ".scala",
    ".sh",
    ".bash",
}

# Directories to always exclude
EXCLUDED_DIRS = {
    "node_modules",
    ".git",
    "venv",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    ".tox",
    "htmlcov",
    "cursor-rules",
    ".mypy_cache",
    "logs",
}


class LocLockCheck(BaseCheck):
    """Lines of code enforcement.

    Enforces:
    - Maximum file length (default: 1000 lines)
    - Maximum function/method length (default: 100 lines)

    Reports specific violations with file paths and line numbers.
    """

    @property
    def name(self) -> str:
        return "loc-lock"

    @property
    def display_name(self) -> str:
        return "📏 LOC Lock"

    @property
    def category(self) -> GateCategory:
        return GateCategory.QUALITY

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="max_file_lines",
                field_type="integer",
                default=DEFAULT_MAX_FILE_LINES,
                description="Maximum lines allowed per file",
                min_value=100,
                max_value=10000,
            ),
            ConfigField(
                name="max_function_lines",
                field_type="integer",
                default=DEFAULT_MAX_FUNCTION_LINES,
                description="Maximum lines allowed per function/method",
                min_value=10,
                max_value=1000,
            ),
            ConfigField(
                name="include_dirs",
                field_type="string[]",
                default=["."],
                description="Directories to scan (relative to project root)",
            ),
            ConfigField(
                name="exclude_dirs",
                field_type="string[]",
                default=[],
                description="Additional directories to exclude",
            ),
            ConfigField(
                name="extensions",
                field_type="string[]",
                default=[],
                description="File extensions to check (empty = all source files)",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        """Check has source files to analyze."""
        return self._has_source_files(project_root)

    def _has_source_files(self, project_root: str) -> bool:
        """Check if project has any source files."""
        root = Path(project_root)
        for ext in SOURCE_EXTENSIONS:
            if any(root.rglob(f"*{ext}")):
                return True
        return False

    def _get_excluded_dirs(self) -> Set[str]:
        """Get directories to exclude from scanning."""
        config_excludes = set(self.config.get("exclude_dirs", []))
        return EXCLUDED_DIRS | config_excludes

    def _should_skip_path(self, path: Path, excluded_dirs: Set[str]) -> bool:
        """Check if path should be skipped."""
        parts = path.parts
        return any(excluded in parts for excluded in excluded_dirs)

    def _get_extensions(self) -> Set[str]:
        """Get file extensions to check."""
        config_exts = self.config.get("extensions", [])
        if config_exts:
            return {ext if ext.startswith(".") else f".{ext}" for ext in config_exts}
        return SOURCE_EXTENSIONS

    def run(self, project_root: str) -> CheckResult:
        """Run LOC enforcement check."""
        start_time = time.time()

        max_file_lines = self.config.get("max_file_lines", DEFAULT_MAX_FILE_LINES)
        max_func_lines = self.config.get(
            "max_function_lines", DEFAULT_MAX_FUNCTION_LINES
        )
        include_dirs = self.config.get("include_dirs", ["."])
        excluded_dirs = self._get_excluded_dirs()
        extensions = self._get_extensions()

        file_violations: List[Tuple[str, int]] = []
        func_violations: List[Tuple[str, str, int, int]] = []

        root = Path(project_root)

        for include_dir in include_dirs:
            scan_path = root / include_dir
            if not scan_path.exists():
                continue

            for file_path in scan_path.rglob("*"):
                if not file_path.is_file():
                    continue
                if file_path.suffix not in extensions:
                    continue
                if self._should_skip_path(file_path, excluded_dirs):
                    continue

                rel_path = str(file_path.relative_to(root))

                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    lines = content.splitlines()
                    line_count = len(lines)

                    # Check file length
                    if line_count > max_file_lines:
                        file_violations.append((rel_path, line_count))

                    # Check function lengths
                    funcs = self._find_functions(content, file_path.suffix)
                    for func_name, start_line, func_lines in funcs:
                        if func_lines > max_func_lines:
                            func_violations.append(
                                (rel_path, func_name, start_line, func_lines)
                            )

                except (OSError, UnicodeDecodeError) as e:
                    logger.debug(f"Could not read {rel_path}: {e}")
                    continue

        duration = time.time() - start_time

        if not file_violations and not func_violations:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"All files within limits (max {max_file_lines} lines/file, "
                f"{max_func_lines} lines/function)",
            )

        # Build violation report
        output_lines = []

        if file_violations:
            output_lines.append(
                f"📁 Files exceeding {max_file_lines} lines ({len(file_violations)}):"
            )
            for path, lines in sorted(file_violations, key=lambda x: -x[1])[:10]:
                output_lines.append(f"  {path}: {lines} lines")
            if len(file_violations) > 10:
                output_lines.append(f"  ... and {len(file_violations) - 10} more")

        if func_violations:
            if output_lines:
                output_lines.append("")
            output_lines.append(
                f"🔧 Functions exceeding {max_func_lines} lines ({len(func_violations)}):"
            )
            for path, func, line, lines in sorted(func_violations, key=lambda x: -x[3])[
                :10
            ]:
                output_lines.append(f"  {path}:{line} {func}(): {lines} lines")
            if len(func_violations) > 10:
                output_lines.append(f"  ... and {len(func_violations) - 10} more")

        total = len(file_violations) + len(func_violations)

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output="\n".join(output_lines),
            error=f"{total} LOC violation(s) found",
            fix_suggestion="Break large files into modules. "
            "Extract long functions into smaller, focused functions.",
        )

    def _find_functions(
        self, content: str, extension: str
    ) -> List[Tuple[str, int, int]]:
        """Find functions/methods and their line counts.

        Returns list of (function_name, start_line, line_count).
        """
        lines = content.splitlines()
        if not lines:
            return []

        # Use language-appropriate patterns
        if extension == ".py":
            return self._find_python_functions(lines)
        elif extension in {".js", ".ts", ".jsx", ".tsx"}:
            return self._find_js_functions(lines)
        elif extension in {".java", ".cs", ".kt", ".scala"}:
            return self._find_brace_functions(
                lines, r"^\s*(public|private|protected|static|\w+)\s+\w+\s+(\w+)\s*\("
            )
        elif extension in {".go"}:
            return self._find_brace_functions(
                lines, r"^\s*func\s+(?:\([^)]*\)\s+)?(\w+)\s*\("
            )
        elif extension in {".rs"}:
            return self._find_brace_functions(lines, r"^\s*(?:pub\s+)?fn\s+(\w+)")
        elif extension in {".rb"}:
            return self._find_ruby_functions(lines)
        elif extension in {".sh", ".bash"}:
            return self._find_shell_functions(lines)
        else:
            # Generic brace-based detection for C-like languages
            return self._find_brace_functions(
                lines, r"^\s*\w+\s+(\w+)\s*\([^)]*\)\s*\{?\s*$"
            )

    def _find_python_functions(self, lines: List[str]) -> List[Tuple[str, int, int]]:
        """Find Python function definitions."""
        functions = []
        func_pattern = re.compile(r"^\s*(async\s+)?def\s+(\w+)\s*\(")
        class_pattern = re.compile(r"^\s*class\s+\w+")

        i = 0
        while i < len(lines):
            match = func_pattern.match(lines[i])
            if match:
                func_name = match.group(2)
                start_line = i + 1
                indent = len(lines[i]) - len(lines[i].lstrip())

                # Find end of function (next line at same or lower indent, not blank)
                end_line = i + 1
                for j in range(i + 1, len(lines)):
                    line = lines[j]
                    if not line.strip():
                        end_line = j + 1
                        continue
                    line_indent = len(line) - len(line.lstrip())
                    if line_indent <= indent and not line.strip().startswith("#"):
                        break
                    end_line = j + 1

                func_lines = end_line - i
                functions.append((func_name, start_line, func_lines))
                i = end_line
            else:
                i += 1

        return functions

    def _find_js_functions(self, lines: List[str]) -> List[Tuple[str, int, int]]:
        """Find JavaScript/TypeScript function definitions."""
        functions = []

        # Match: function name(), const name = () =>, async function name()
        patterns = [
            re.compile(r"^\s*(?:async\s+)?function\s+(\w+)\s*\("),
            re.compile(
                r"^\s*(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[^=])\s*=>"
            ),
            re.compile(r"^\s*(\w+)\s*(?::\s*\w+)?\s*\([^)]*\)\s*(?::\s*\w+)?\s*\{"),
        ]

        i = 0
        while i < len(lines):
            func_name = None
            for pattern in patterns:
                match = pattern.match(lines[i])
                if match:
                    func_name = match.group(1)
                    break

            if func_name:
                start_line = i + 1
                end_line = self._find_brace_end(lines, i)
                func_lines = end_line - i
                functions.append((func_name, start_line, func_lines))
                i = end_line
            else:
                i += 1

        return functions

    def _find_brace_functions(
        self, lines: List[str], pattern_str: str
    ) -> List[Tuple[str, int, int]]:
        """Find functions in brace-delimited languages."""
        functions = []
        pattern = re.compile(pattern_str)

        i = 0
        while i < len(lines):
            match = pattern.match(lines[i])
            if match:
                func_name = match.group(1) if match.lastindex else "unknown"
                start_line = i + 1
                end_line = self._find_brace_end(lines, i)
                func_lines = end_line - i
                functions.append((func_name, start_line, func_lines))
                i = end_line
            else:
                i += 1

        return functions

    def _find_brace_end(self, lines: List[str], start: int) -> int:
        """Find the closing brace for a function starting at given line."""
        brace_count = 0
        found_open = False

        for i in range(start, len(lines)):
            line = lines[i]
            # Skip strings and comments (simplified)
            for char in line:
                if char == "{":
                    brace_count += 1
                    found_open = True
                elif char == "}":
                    brace_count -= 1

            if found_open and brace_count == 0:
                return i + 1

        return len(lines)

    def _find_ruby_functions(self, lines: List[str]) -> List[Tuple[str, int, int]]:
        """Find Ruby method definitions."""
        functions = []
        def_pattern = re.compile(r"^\s*def\s+(\w+)")

        i = 0
        while i < len(lines):
            match = def_pattern.match(lines[i])
            if match:
                func_name = match.group(1)
                start_line = i + 1
                # Find matching 'end'
                depth = 1
                for j in range(i + 1, len(lines)):
                    line = lines[j].strip()
                    if re.match(
                        r"^(def|class|module|if|unless|case|while|until|for|begin|do)\b",
                        line,
                    ):
                        depth += 1
                    elif line == "end":
                        depth -= 1
                        if depth == 0:
                            functions.append((func_name, start_line, j - i + 1))
                            i = j + 1
                            break
                else:
                    i += 1
            else:
                i += 1

        return functions

    def _find_shell_functions(self, lines: List[str]) -> List[Tuple[str, int, int]]:
        """Find shell function definitions."""
        functions = []
        # Match: function_name() { or function function_name {
        pattern = re.compile(r"^\s*(?:function\s+)?(\w+)\s*\(\s*\)\s*\{?")

        i = 0
        while i < len(lines):
            match = pattern.match(lines[i])
            if match:
                func_name = match.group(1)
                start_line = i + 1
                end_line = self._find_brace_end(lines, i)
                func_lines = end_line - i
                functions.append((func_name, start_line, func_lines))
                i = end_line
            else:
                i += 1

        return functions
