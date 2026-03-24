"""Lines of code enforcement check.

Enforces maximum file length and function/method length limits.
Helps prevent bloated files and overly complex functions that are
difficult for both humans and LLMs to reason about.

This is a cross-cutting quality check that applies to all source files.
"""

import ast
import io
import logging
import re
import time
import tokenize
from pathlib import Path
from typing import List, Optional, Set, Tuple

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    RemediationChurn,
    count_source_scope,
)
from slopmop.core.result import (
    CheckResult,
    CheckStatus,
    Finding,
    FindingLevel,
    ScopeInfo,
)

logger = logging.getLogger(__name__)

# Default limits
DEFAULT_MAX_FILE_LINES = 1000
DEFAULT_MAX_FUNCTION_LINES = 100

# Whole-line comment prefixes by extension.  Used by _count_code_lines
# for everything that isn't Python.  Block comments (/* */) are NOT
# handled — a line inside a block comment will be over-counted.  That's
# the safe direction: over-counting means a sprawling file trips the
# gate slightly early, never late.  And you can't squeeze by DELETING
# block-comment lines because they were already counting.
_COMMENT_PREFIXES: dict[str, str] = {
    ".py": "#",
    ".rb": "#",
    ".sh": "#",
    ".bash": "#",
    ".js": "//",
    ".ts": "//",
    ".jsx": "//",
    ".tsx": "//",
    ".java": "//",
    ".go": "//",
    ".rs": "//",
    ".c": "//",
    ".cpp": "//",
    ".h": "//",
    ".hpp": "//",
    ".cs": "//",
    ".swift": "//",
    ".kt": "//",
    ".scala": "//",
    ".php": "//",
}


# ---------------------------------------------------------------------------
# Code-line counting — the anti-squeeze metric
# ---------------------------------------------------------------------------
#
# The original check counted raw lines.  That's gameable: at 1003/1000
# an agent will trim 3 comment lines and call it fixed.  The gate goes
# green, the sprawl stays.  We watched this happen — an LLM compressed
# an 8-line docstring to 5 lines to squeeze base.py under the limit.
# Tests passed, gate passed, file still had two unrelated 200-line
# classes squatting in it.
#
# The fix: count lines that have CODE on them.  Comments, blanks, and
# docstrings become invisible to the metric.  Trimming them achieves
# nothing.  The only way under is to move actual code out — which is
# the whole point.
#
# Python gets the precise version (tokenize) because it's the primary
# target and because docstring compression is the subtlest squeeze.
# Other languages get prefix-stripped line counting, which defeats
# blank-delete and comment-delete but not docstring-equivalents.  The
# anti-pattern warning in fix_suggestion covers the remaining gap.


def _count_code_lines(content: str, extension: str) -> int:
    """Count lines that contain actual code.

    For Python: a line counts iff it has at least one NAME, NUMBER, or
    OP token.  Docstrings are STRING tokens — invisible.  A 10-line
    docstring and a 1-line docstring contribute identically (zero).

    For everything else: a line counts iff it's non-blank and doesn't
    start with the language's line-comment prefix.  Cruder, but
    cross-language and still defeats the cheap squeezes.
    """
    if extension == ".py":
        count = _python_code_lines(content)
        if count is not None:
            return count
        # Tokenize choked (syntax error) — fall through to prefix mode.
    prefix = _COMMENT_PREFIXES.get(extension, "#")
    return sum(
        1
        for line in content.splitlines()
        if (stripped := line.strip()) and not stripped.startswith(prefix)
    )


def _python_code_lines(content: str) -> Optional[int]:
    """Tokenize-based code-line count for Python.

    Returns ``None`` if tokenization fails — the caller falls back to
    prefix-stripped counting rather than crashing on a malformed file.

    Why allowlist NAME/NUMBER/OP instead of blocklist STRING/COMMENT:
    f-string tokenization changed in 3.12 (FSTRING_START etc).  An
    allowlist of the three token types that are ALWAYS code is stable
    across versions.  Everything else — strings, comments, structural
    tokens — is either prose or scaffolding.
    """
    meaningful = {tokenize.NAME, tokenize.NUMBER, tokenize.OP}
    code_lines: Set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(content).readline):
            if tok.type in meaningful:
                code_lines.add(tok.start[0])
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    return len(code_lines)


def _file_action(
    target: Optional[Tuple[str, int, int]], over: int, total_loc: int = 0
) -> str:
    """Render the per-file instruction — the '#4' ultra-specific guidance.

    This string is the payload.  It's what an agent reads at the moment
    of deciding how to fix the violation, in both the console output
    and the GitHub annotation.

    Two modes:
      1. The biggest definition clears the limit → name it, say "move this".
      2. It doesn't (or nothing was found) → the file needs a real split.
         Emit a prompt the calling agent can hand to a subagent to find
         the right seam.  We can't pick the seam programmatically — it
         requires reading the file and understanding its structure.
    """
    if target is not None:
        name, line, span = target
        if span > over:
            # Moving the biggest thing clears the limit with room to spare.
            # Tell them exactly where it is and where it goes.
            return (
                f"Move {name} ({span} lines, starts line {line}) to its own "
                f"file — that clears the limit by {span - over}."
            )
    # Either no target found, or the biggest definition doesn't clear
    # the limit.  Don't nibble at individual functions — hand the agent
    # a prompt to find a structural seam.
    mid = f" (around line {total_loc // 2})" if total_loc else ""
    return (
        f"This file needs splitting, not function extraction. "
        f"Read the file and find a logical seam near the middle{mid} "
        f"— look for describe() blocks, class boundaries, or groups of "
        f"related functions that form a natural module. Split into two "
        f"files with descriptive names."
    )


# The anti-pattern warning — '#3'.  One static string, shown once per
# failing run via fix_suggestion.  The key line is "already don't
# count": telling an agent WHY the squeeze won't work, BEFORE it
# tries, is more effective than detecting the squeeze after.  The
# specific per-violation instructions in the Finding messages do the
# heavy lifting; this is the backstop for anyone who skims past them.
_FIX_SUGGESTION = (
    "Phase 1 (oversized files) is the highest-payoff work — splitting a "
    "large file often resolves the function violations inside it too. "
    "Phase 2 (oversized functions in otherwise-OK files) needs internal "
    "extraction: break the function at a logical seam into helpers.\n"
    "\n"
    "⚠️  DO NOT trim comments, compress docstrings, or join lines to "
    "squeeze under the limit. This check counts CODE lines only — "
    "comments, blanks, and docstrings already don't count, so trimming "
    "them achieves nothing."
)

_FIX_SUGGESTION_SUFFIX = "\n\nVerify with: "


def _find_biggest_python_definition(
    content: str,
) -> Optional[Tuple[str, int, int]]:
    """Find the largest top-level class or function in a Python file.

    Returns ``(name, start_line, raw_line_span)`` or ``None`` if the
    file has no top-level definitions (or doesn't parse).

    "Top-level" means module body — we're answering "what should I
    move OUT of this file?", not "what should I break UP inside it?".
    A 300-line class is the right target even if its biggest method
    is only 40 lines.  Raw line span (not code-line count) is the
    right size here because moving the class moves its docstrings
    too — the caller's mental model is "delete these N lines from
    the file", and that N includes prose.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None
    defs = [
        node
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if not defs:
        return None
    biggest = max(defs, key=lambda n: (n.end_lineno or n.lineno) - n.lineno)
    span = (biggest.end_lineno or biggest.lineno) - biggest.lineno + 1
    return (biggest.name, biggest.lineno, span)


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
    # AI-assistant working directories — local tooling, not project
    # source.  These showed up when users ran swab with an active
    # Claude Code session: .claude/hooks/ contains long orchestration
    # scripts that tripped the function-length limit despite being
    # entirely outside the project's quality surface.
    ".claude",
    ".cursor",
    ".aider",
    # Framework-generated migration histories are intentionally verbose and
    # repetitive; file/function size limits are not useful there.
    "migrations",
    "alembic",
}


class LocLockCheck(BaseCheck):
    """File and function length enforcement.

    Pure Python check (no external tool). Scans source files for
    length violations. Large files and long functions are harder
    for both humans and LLMs to reason about.

    Level: swab

    Configuration:
      max_file_lines: 1000 — CODE lines: comments, blanks, and (for
          Python) docstrings don't count. Trimming prose won't help
          you pass — only moving code will. 1000 is generous; most
          well-structured files stay under 500.
      max_function_lines: 100 — RAW lines: a 120-line function with
          40 comment lines is still 120 lines to scroll through.
          Focus on logical separation ("what concepts does this
          handle?") not line reduction.
      include_dirs: ["."] — scan everything by default.
      exclude_dirs: [] — additional dirs to skip (node_modules,
          venv, etc. are always excluded).
      extensions: [] — empty means all known source extensions.
          Set to [".py"] to limit to Python only.

    Common failures:
      File too long: Split into modules by responsibility.
      Function too long: Extract helper functions for distinct
          concepts. Three 30-line functions > one 90-line function.

    Re-check:
      sm swab -g myopia:code-sprawl --verbose
    """

    role = CheckRole.DIAGNOSTIC
    remediation_churn = RemediationChurn.DOWNSTREAM_CHANGES_VERY_LIKELY

    @property
    def name(self) -> str:
        return "code-sprawl"

    @property
    def display_name(self) -> str:
        return "📏 Code Sprawl (file & function length)"

    @property
    def gate_description(self) -> str:
        return "📏 File and function length limits"

    @property
    def category(self) -> GateCategory:
        return GateCategory.MYOPIA

    @property
    def flaw(self) -> Flaw:
        return Flaw.MYOPIA

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
                permissiveness="lower_is_stricter",
            ),
            ConfigField(
                name="max_function_lines",
                field_type="integer",
                default=DEFAULT_MAX_FUNCTION_LINES,
                description="Maximum lines allowed per function/method",
                min_value=10,
                max_value=1000,
                permissiveness="lower_is_stricter",
            ),
            ConfigField(
                name="include_dirs",
                field_type="string[]",
                default=["."],
                description="Directories to scan (relative to project root)",
                permissiveness="more_is_stricter",
            ),
            ConfigField(
                name="exclude_dirs",
                field_type="string[]",
                default=[],
                description="Additional directories to exclude",
                permissiveness="fewer_is_stricter",
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

    def skip_reason(self, project_root: str) -> str:
        """Return skip reason when no source files match configured extensions."""
        return "No source files found matching configured extensions"

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

    def measure_scope(self, project_root: str) -> Optional[ScopeInfo]:
        """Report scope using all source extensions (not just .py)."""
        include_dirs = self.config.get("include_dirs", ["."])
        extensions = self._get_extensions()
        config_excludes = set(self.config.get("exclude_dirs", []))
        return count_source_scope(
            project_root,
            include_dirs=include_dirs,
            extensions=extensions,
            exclude_dirs=config_excludes,
        )

    def _scan_violations(
        self,
        project_root: str,
        max_file_lines: int,
        max_func_lines: int,
    ) -> Tuple[
        List[Tuple[str, int, Optional[Tuple[str, int, int]]]],
        List[Tuple[str, str, int, int]],
    ]:
        """Walk source files and collect file/function violations."""
        include_dirs = self.config.get("include_dirs", ["."])
        excluded_dirs = self._get_excluded_dirs()
        extensions = self._get_extensions()

        file_violations: List[Tuple[str, int, Optional[Tuple[str, int, int]]]] = []
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

                    line_count = _count_code_lines(content, file_path.suffix)

                    if line_count > max_file_lines:
                        target = self._pick_move_target(content, file_path.suffix)
                        file_violations.append((rel_path, line_count, target))

                    funcs = self._find_functions(content, file_path.suffix)
                    for func_name, start_line, func_lines in funcs:
                        if func_lines > max_func_lines:
                            func_violations.append(
                                (rel_path, func_name, start_line, func_lines)
                            )

                except (OSError, UnicodeDecodeError) as e:
                    logger.debug(f"Could not read {rel_path}: {e}")
                    continue

        return file_violations, func_violations

    def run(self, project_root: str) -> CheckResult:
        """Run LOC enforcement check."""
        start_time = time.time()

        max_file_lines = self.config.get("max_file_lines", DEFAULT_MAX_FILE_LINES)
        max_func_lines = self.config.get(
            "max_function_lines", DEFAULT_MAX_FUNCTION_LINES
        )

        file_violations, func_violations = self._scan_violations(
            project_root, max_file_lines, max_func_lines
        )

        duration = time.time() - start_time

        if not file_violations and not func_violations:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"All files within limits (max {max_file_lines} lines/file, "
                f"{max_func_lines} lines/function)",
            )

        total = len(file_violations) + len(func_violations)

        # Deduplicate: function violations in files that already have a
        # file-level violation are secondary context, not separate problems.
        oversized_files = {path for path, _, _ in file_violations}
        primary_func_violations = [
            fv for fv in func_violations if fv[0] not in oversized_files
        ]
        secondary_func_violations = [
            fv for fv in func_violations if fv[0] in oversized_files
        ]
        unique_problems = len(file_violations) + len(primary_func_violations)

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=self._format_violations(
                file_violations,
                primary_func_violations,
                secondary_func_violations,
                max_file_lines,
                max_func_lines,
            ),
            error=(
                f"{unique_problems} unique problem(s) " f"({total} total violation(s))"
            ),
            fix_suggestion=_FIX_SUGGESTION
            + _FIX_SUGGESTION_SUFFIX
            + self.verify_command,
            findings=self._build_findings(
                file_violations,
                primary_func_violations,
                secondary_func_violations,
                max_file_lines,
                max_func_lines,
            ),
        )

    def _pick_move_target(
        self, content: str, extension: str
    ) -> Optional[Tuple[str, int, int]]:
        """Find the thing to move OUT of an oversized file.

        For Python: biggest top-level class or function via AST.
        For everything else: biggest function via the existing regex
        machinery — not as good (misses classes) but still actionable.

        Returns ``(name, start_line, line_span)`` or ``None`` when
        nothing identifiable was found.  ``None`` degrades gracefully
        to a generic message; it doesn't hide the violation.
        """
        if extension == ".py":
            hit = _find_biggest_python_definition(content)
            if hit is not None:
                return hit
        funcs = self._find_functions(content, extension)
        if not funcs:
            return None
        name, start, span = max(funcs, key=lambda f: f[2])
        return (name, start, span)

    @staticmethod
    def _format_violations(
        file_violations: List[Tuple[str, int, Optional[Tuple[str, int, int]]]],
        primary_func_violations: List[Tuple[str, str, int, int]],
        secondary_func_violations: List[Tuple[str, str, int, int]],
        max_file_lines: int,
        max_func_lines: int,
    ) -> str:
        """Render violations in priority order for console output.

        Two-phase layout:
          Phase 1 — Oversized files (primary).  Fixing these often
            clears secondary function violations in the same file.
          Phase 2 — Oversized functions in files that are otherwise
            within the file limit.  These need internal extraction.

        Secondary function violations (inside already-oversized files)
        are shown as indented context under the file violation, not as
        separate top-level items — they'll likely resolve when the
        file is split.
        """
        out: List[str] = []

        if file_violations:
            out.append(f"📁 Phase 1 — Oversized files " f"({len(file_violations)}):")
            # Group secondary func violations by file for context display
            sec_by_file: dict[str, List[Tuple[str, str, int, int]]] = {}
            for fv in secondary_func_violations:
                sec_by_file.setdefault(fv[0], []).append(fv)

            for path, lines, target in sorted(file_violations, key=lambda x: -x[1])[
                :10
            ]:
                over = lines - max_file_lines
                out.append(f"  {path}: {lines} code lines ({over} over)")
                out.append(f"    → {_file_action(target, over, lines)}")
                # Show secondary function violations as context
                sec_funcs = sec_by_file.get(path, [])
                if sec_funcs:
                    n = len(sec_funcs)
                    out.append(
                        f"    ↳ {n} oversized function(s) in this file "
                        f"(will likely resolve when file is split)"
                    )
            if len(file_violations) > 10:
                out.append(f"  ... and {len(file_violations) - 10} more")

        if primary_func_violations:
            if out:
                out.append("")
            out.append(
                f"🔧 Phase 2 — Oversized functions in otherwise-OK files "
                f"({len(primary_func_violations)}):"
            )
            for path, func, line, lines in sorted(
                primary_func_violations, key=lambda x: -x[3]
            )[:10]:
                over = lines - max_func_lines
                out.append(
                    f"  {path}:{line} — {func}(): {lines} lines "
                    f"(limit {max_func_lines}, {over} over)"
                )
                out.append(
                    f"    → Break at least {over} lines off into a new "
                    f"function, or relocate to an existing one."
                )
            if len(primary_func_violations) > 10:
                out.append(f"  ... and {len(primary_func_violations) - 10} more")

        return "\n".join(out)

    @staticmethod
    def _build_findings(
        file_violations: List[Tuple[str, int, Optional[Tuple[str, int, int]]]],
        primary_func_violations: List[Tuple[str, str, int, int]],
        secondary_func_violations: List[Tuple[str, str, int, int]],
        max_file_lines: int,
        max_func_lines: int,
    ) -> List[Finding]:
        """Build structured findings for SARIF — one per violation.

        File violations are emitted at ERROR level with rule_id
        ``file-sprawl``.  Primary function violations (in files that
        are otherwise within the file limit) are ERROR / ``func-sprawl``.
        Secondary function violations (inside already-oversized files)
        are WARNING / ``func-sprawl-secondary`` — they'll likely resolve
        when the file is split, so they shouldn't dominate triage.
        """
        out: List[Finding] = []
        for path, loc, target in file_violations:
            over = loc - max_file_lines
            out.append(
                Finding(
                    message=(
                        f"{loc} code lines (limit {max_file_lines}, {over} over). "
                        f"{_file_action(target, over, loc)}"
                    ),
                    level=FindingLevel.ERROR,
                    file=path,
                    line=target[1] if target else None,
                    rule_id="file-sprawl",
                )
            )
        for path, func, start_line, loc in primary_func_violations:
            over = loc - max_func_lines
            out.append(
                Finding(
                    message=(
                        f"{func}(): {loc} lines (limit {max_func_lines}, {over} over). "
                        f"Break at least {over} lines off into a new function, "
                        f"or relocate to an existing one."
                    ),
                    level=FindingLevel.ERROR,
                    file=path,
                    line=start_line,
                    rule_id="func-sprawl",
                )
            )
        for path, func, start_line, loc in secondary_func_violations:
            over = loc - max_func_lines
            out.append(
                Finding(
                    message=(
                        f"{func}(): {loc} lines (limit {max_func_lines}, {over} over). "
                        f"This function is in a file that also exceeds the file "
                        f"limit — splitting the file will likely resolve this."
                    ),
                    level=FindingLevel.WARNING,
                    file=path,
                    line=start_line,
                    rule_id="func-sprawl-secondary",
                )
            )
        return out

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
        functions: List[Tuple[str, int, int]] = []
        func_pattern = re.compile(r"^\s*(async\s+)?def\s+(\w+)\s*\(")

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
        functions: List[Tuple[str, int, int]] = []

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
        functions: List[Tuple[str, int, int]] = []
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
        functions: List[Tuple[str, int, int]] = []
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
        functions: List[Tuple[str, int, int]] = []
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
