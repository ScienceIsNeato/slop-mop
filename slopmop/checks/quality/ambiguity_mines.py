"""Ambiguity mine detection via AST scan.

Detects module-level function names that appear in multiple Python files,
which creates "ambiguity mines" — copy-paste artifacts that diverge over
time until every bug fix becomes a scavenger hunt.

This is a separate concern from repeated-code (jscpd clone detection).
Repeated code catches large duplicated blocks; ambiguity mines catch small
functions with the same name in different files, even when the bodies
differ.

Re-check:
    sm swab -g myopia:ambiguity-mines.py --verbose
"""

import ast
import os
import textwrap
import time
from typing import List, Optional

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    RemediationChurn,
    ScopeInfo,
    ToolContext,
    count_source_scope,
)
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel

_AMBIGUITY_MINE_FIX = (
    "Consolidate duplicate function definitions to eliminate ambiguity mines."
)

# Function names expected to appear in multiple files — not ambiguous.
_AMBIGUITY_MINE_SKIP_NAMES: set[str] = {
    # Entry-point / lifecycle patterns
    "main",
    "run",
    "cli",
    "setup",
    "configure",
    "register",
    # unittest lifecycle
    "setUp",
    "tearDown",
    "setUpClass",
    "tearDownClass",
    "setUpModule",
    "tearDownModule",
    # pytest lifecycle
    "setup_method",
    "teardown_method",
    "setup_module",
    "teardown_module",
    "setup_function",
    "teardown_function",
}

# Directories pruned during the AST walk.
_AST_SKIP_DIRS: set[str] = {
    "node_modules",
    "dist",
    "build",
    ".git",
    ".slopmop",
    "__pycache__",
    ".venv",
    "venv",
    "coverage",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    "htmlcov",
    "tools",
    "migrations",
    "alembic",
    "cursor-rules",
}


def _indent_source(src: str, prefix: str = "     | ") -> str:
    """Indent a block of source for embedding in fix_strategy."""
    return "\n".join(prefix + line for line in src.splitlines())


class AmbiguityMinesCheck(BaseCheck):
    """Detect module-level function names duplicated across Python files.

    Catches small-function "ambiguity mines" that fall below jscpd's
    token threshold — functions with the same name in different files
    whose bodies may have silently diverged.

    For each duplicate, extracts the actual source so the calling LLM
    can classify the duplication (A–E triage) and take the right action.

    Level: swab

    Configuration:
      include_dirs: ["."] — directories to scan.
      exclude_dirs: [] — extra dirs to skip (node_modules, venv,
          etc. are always excluded).

    Common failures:
      Ambiguity mine detected: Consolidate duplicate function
          definitions. The output classifies each finding with a
          triage strategy (A–E).

    Re-check:
      sm swab -g myopia:ambiguity-mines.py --verbose
    """

    tool_context = ToolContext.PURE
    role = CheckRole.FOUNDATION
    remediation_churn = RemediationChurn.DOWNSTREAM_CHANGES_VERY_LIKELY

    @property
    def name(self) -> str:
        return "ambiguity-mines.py"

    @property
    def display_name(self) -> str:
        return "💣 Ambiguity Mines (duplicate function names)"

    @property
    def gate_description(self) -> str:
        return "💣 Function-name ambiguity detection (AST)"

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
                name="include_dirs",
                field_type="string[]",
                default=["."],
                description="Directories to scan for ambiguity mines",
                permissiveness="more_is_stricter",
            ),
            ConfigField(
                name="exclude_dirs",
                field_type="string[]",
                default=[],
                description="Extra directories to skip during ambiguity mine scanning",
                permissiveness="fewer_is_stricter",
            ),
        ]

    def cache_inputs(self, project_root: str) -> Optional[str]:
        from slopmop.core.cache import hash_file_scope

        dirs = self.config.get("include_dirs", ["."])
        if not dirs:
            dirs = ["."]
        exclude = set(self.config.get("exclude_dirs", []))
        return hash_file_scope(
            project_root,
            dirs,
            {".py"},
            self.config,
            exclude_dirs=exclude,
        )

    def is_applicable(self, project_root: str) -> bool:
        for root, _, files in os.walk(project_root):
            if any(f.endswith(".py") for f in files):
                return True
        return False

    def skip_reason(self, project_root: str) -> str:
        return "No Python source files found"

    def measure_scope(self, project_root: str) -> Optional[ScopeInfo]:
        include_dirs = self.config.get("include_dirs") or ["."]
        return count_source_scope(
            project_root,
            include_dirs=list(include_dirs),
            extensions={".py"},
        )

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()

        include_dirs = self.config.get("include_dirs", ["."])
        if not include_dirs:
            include_dirs = ["."]

        findings = self._scan_duplicate_function_names(project_root, include_dirs)
        duration = time.time() - start_time

        if not findings:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output="No ambiguity mines detected",
            )

        detail = "Ambiguity mines (function names duplicated across files):\n"
        detail += "\n".join(f"  {f.message}" for f in findings)

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=detail,
            error="Ambiguity mines detected",
            fix_suggestion=_AMBIGUITY_MINE_FIX,
            findings=findings,
        )

    # ── AST scan internals ────────────────────────────────────────────

    @staticmethod
    def _extract_function_source(
        source_lines: list[str], node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> str:
        """Extract source text for a function node (decorators through end)."""
        start_lineno = node.lineno
        if getattr(node, "decorator_list", None):
            decorator_linenos = [
                dec.lineno for dec in node.decorator_list if hasattr(dec, "lineno")
            ]
            if decorator_linenos:
                start_lineno = min(start_lineno, min(decorator_linenos))
        start = max(start_lineno - 1, 0)
        end = node.end_lineno or node.lineno
        return "".join(source_lines[start:end])

    @staticmethod
    def _is_suppressed(source_lines: list[str], lineno: int) -> bool:
        """Check if the def line has a ``# noqa: ambiguity-mine`` comment."""
        line = source_lines[lineno - 1] if lineno <= len(source_lines) else ""
        return "noqa: ambiguity-mine" in line

    @staticmethod
    def _build_mine_fix_strategy(
        name: str,
        locations: list[tuple[str, int, str]],
        identical: bool,
    ) -> str:
        """Build a triage-oriented fix_strategy for the calling LLM."""
        loc_block = "\n".join(
            f"  {i+1}. {rel}:{lineno}\n{_indent_source(src)}"
            for i, (rel, lineno, src) in enumerate(locations)
        )
        similarity = "IDENTICAL" if identical else "DIVERGED"

        return (
            f"Ambiguity mine: `{name}()` is defined in "
            f"{len(locations)} files ({similarity} bodies).\n"
            f"\n"
            f"Copies:\n{loc_block}\n"
            f"\n"
            f"Classify this as ONE of the following and take the "
            f"corresponding action:\n"
            f"\n"
            f"A) ERRANT DUPLICATION — no excuse, just a copy-paste "
            f"duplicate. Pick the canonical location, delete the "
            f"other(s), and import from the canonical module.\n"
            f"\n"
            f"B) NEEDS ABSTRACTION — both copies do the same thing "
            f"in different contexts. Extract into a shared utility "
            f"module and have both call sites import it.\n"
            f"\n"
            f"C) MISLEADING NAME — the functions aren't really "
            f"duplicates; one (or both) has a poor name that "
            f"creates false ambiguity. Rename the less-canonical "
            f"copy to reflect what it actually does.\n"
            f"\n"
            f"D) PURPOSEFUL DUPLICATION — these implement the same "
            f"interface/protocol in different contexts (e.g. "
            f"strategy pattern, test doubles). This is acceptable "
            f"if the duplication is structural, not accidental. "
            f"Add `# noqa: ambiguity-mine` to each def line to "
            f"suppress.\n"
            f"\n"
            f"E) ALLOWED EXCEPTION — a rare case that doesn't fit "
            f"A–D. Add `# noqa: ambiguity-mine` to each def line "
            f"with a comment explaining why."
        )

    def _scan_duplicate_function_names(
        self, project_root: str, include_dirs: list[str]
    ) -> list[Finding]:
        """AST scan for module-level function names defined in 2+ files."""
        config_excludes = set(self.config.get("exclude_dirs", []))
        skip_dirs = _AST_SKIP_DIRS | config_excludes

        # func_name → [(relative_path, lineno, source_text)]
        func_index: dict[str, list[tuple[str, int, str]]] = {}
        seen_files: set[str] = set()

        for scan_dir in include_dirs:
            base = (
                os.path.join(project_root, scan_dir)
                if scan_dir != "."
                else project_root
            )
            for root, dirs, files in os.walk(base):
                dirs[:] = [
                    d
                    for d in dirs
                    if d not in skip_dirs and not d.endswith(".egg-info")
                ]
                for fname in files:
                    if not fname.endswith(".py") or fname == "conftest.py":
                        continue
                    fpath = os.path.join(root, fname)
                    rel = os.path.relpath(fpath, project_root)
                    if rel in seen_files:
                        continue
                    seen_files.add(rel)
                    try:
                        with open(fpath, encoding="utf-8") as f:
                            source = f.read()
                        tree = ast.parse(source, filename=rel)
                    except (SyntaxError, UnicodeDecodeError):
                        continue
                    source_lines = source.splitlines(keepends=True)
                    for node in ast.iter_child_nodes(tree):
                        if not isinstance(
                            node, (ast.FunctionDef, ast.AsyncFunctionDef)
                        ):
                            continue
                        name = node.name
                        if name in _AMBIGUITY_MINE_SKIP_NAMES or (
                            name.startswith("__") and name.endswith("__")
                        ):
                            continue
                        if self._is_suppressed(source_lines, node.lineno):
                            continue
                        func_src = self._extract_function_source(source_lines, node)
                        func_index.setdefault(name, []).append(
                            (rel, node.lineno, func_src)
                        )

        findings: list[Finding] = []
        for name, locations in sorted(func_index.items()):
            unique_files = {loc[0] for loc in locations}
            if len(unique_files) < 2:
                continue

            normalised = [textwrap.dedent(loc[2]).strip() for loc in locations]
            identical = len(set(normalised)) == 1

            sorted_locs = sorted(locations)
            loc_strs = [f"{f}:{line}" for f, line, _ in sorted_locs]
            tag = "identical" if identical else "DIVERGED"
            strategy = self._build_mine_fix_strategy(name, sorted_locs, identical)

            findings.append(
                Finding(
                    message=(
                        f"Ambiguity mine ({tag}): `{name}()` defined in "
                        f"{len(unique_files)} files: " + ", ".join(loc_strs)
                    ),
                    level=FindingLevel.ERROR,
                    file=sorted_locs[0][0],
                    line=sorted_locs[0][1],
                    fix_strategy=strategy,
                )
            )

        return findings
