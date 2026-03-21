"""Code duplication detection using jscpd.

Detects copy-paste code across multiple languages.
Reports specific file pairs and line ranges for deduplication.

Note: This is a cross-cutting quality check that works across
all languages supported by jscpd.
"""

import ast
import json
import os
import tempfile
import textwrap
import time
from typing import Any, Dict, List, Optional

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

DEFAULT_THRESHOLD = 5.0  # Percent duplication allowed
MIN_TOKENS = 50
MIN_LINES = 5

_AMBIGUITY_MINE_FIX = (
    "Consolidate duplicate function definitions to eliminate ambiguity mines."
)

# ── Ambiguity-mine detection (supplementary AST scan) ────────────────
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

# Directories pruned during the AST walk (mirrors _DEFAULT_IGNORES
# minus glob-only patterns that don't map to dir names).
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


class SourceDuplicationCheck(BaseCheck):
    """Cross-language code duplication detection.

    Wraps jscpd to detect copy-paste code across Python, JavaScript,
    TypeScript, and other languages. Reports specific file pairs and
    line ranges so you know exactly what to deduplicate.

    Level: swab

    Configuration:
      threshold: 5 — maximum allowed duplication percentage. 5% is
          generous; tighten to 2-3% for mature codebases.
      include_dirs: ["."] — directories to scan.
      min_tokens: 50 — minimum token count to consider a block as
          duplicate. Filters trivial matches (imports, boilerplate).
      min_lines: 5 — minimum line count for a duplicate block.
      exclude_dirs: [] — extra dirs to skip (node_modules, venv,
          etc. are always excluded).

    Common failures:
      Duplication exceeds threshold: Extract the duplicated code
          into a shared function or module. The output shows the
          specific file pairs and line ranges.
      jscpd not available: npm install -g jscpd

    Re-check:
      sm swab -g myopia:source-duplication --verbose
    """

    tool_context = ToolContext.NODE
    role = CheckRole.FOUNDATION
    remediation_churn = RemediationChurn.DOWNSTREAM_CHANGES_VERY_LIKELY

    def __init__(self, config: Dict[str, Any], threshold: float = DEFAULT_THRESHOLD):
        super().__init__(config)
        self.threshold = config.get("threshold", threshold)

    @property
    def name(self) -> str:
        return "source-duplication"

    @property
    def display_name(self) -> str:
        return "📋 Source Duplication (jscpd clone detection)"

    @property
    def gate_description(self) -> str:
        return "📋 Code clone detection (jscpd)"

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
                name="threshold",
                field_type="integer",
                default=5,
                description="Maximum allowed duplication percentage",
                min_value=0,
                max_value=100,
                permissiveness="lower_is_stricter",
            ),
            ConfigField(
                name="include_dirs",
                field_type="string[]",
                default=["."],
                description="Directories to scan for duplication",
                permissiveness="more_is_stricter",
            ),
            ConfigField(
                name="min_tokens",
                field_type="integer",
                default=50,
                description="Minimum token count to consider as duplicate",
                permissiveness="lower_is_stricter",
            ),
            ConfigField(
                name="min_lines",
                field_type="integer",
                default=5,
                description="Minimum line count to consider as duplicate",
                permissiveness="lower_is_stricter",
            ),
            ConfigField(
                name="exclude_dirs",
                field_type="string[]",
                default=[],
                description="Additional directories to exclude from duplication scanning",
                permissiveness="fewer_is_stricter",
            ),
        ]

    def cache_inputs(self, project_root: str) -> Optional[str]:
        from slopmop.core.cache import hash_file_scope

        dirs = self.config.get("include_dirs", ["."])
        if not dirs:
            dirs = ["."]
        exclude = set(self.config.get("exclude_dirs", []))
        exts = {".py", ".js", ".ts", ".jsx", ".tsx"}
        return hash_file_scope(
            project_root,
            dirs,
            exts,
            self.config,
            exclude_dirs=exclude,
        )

    def is_applicable(self, project_root: str) -> bool:
        # Applicable to any project with code
        for ext in [".py", ".js", ".ts", ".jsx", ".tsx"]:
            for root, _, files in os.walk(project_root):
                if any(f.endswith(ext) for f in files):
                    return True
        return False

    def skip_reason(self, project_root: str) -> str:
        """Return skip reason when no source code is detected."""
        # Check for source files first
        has_code = False
        for ext in [".py", ".js", ".ts", ".jsx", ".tsx"]:
            for root, _, files in os.walk(project_root):
                if any(f.endswith(ext) for f in files):
                    has_code = True
                    break
            if has_code:
                break
        if not has_code:
            return "No Python or JavaScript/TypeScript source files found"
        return "Duplication check not applicable"

    # Default directories/files to ignore (build artifacts, caches, vendored)
    _DEFAULT_IGNORES = [
        "node_modules",
        "dist",
        "build",
        ".git",
        ".slopmop",
        "__pycache__",
        ".venv",
        "venv",
        "coverage",
        "coverage.xml",  # pytest-cov build artifact
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        "htmlcov",
        "*.egg-info",
        "tools",  # vendored third-party tools
        "migrations",  # DB migrations are intentionally repetitive
        "alembic",  # Alembic revisions are intentionally repetitive
        "**/migrations/**",
        "**/alembic/**",
    ]

    def _check_jscpd_availability(self, project_root: str) -> Optional[str]:
        """Check if jscpd is available. Returns error message or None."""
        result = self._run_command(
            ["npx", "jscpd", "--version"], cwd=project_root, timeout=30
        )
        if result.returncode != 0:
            return "jscpd not available"
        return None

    def _build_jscpd_command(
        self,
        report_output: str,
        include_dirs: list[str],
        min_tokens: int,
        min_lines: int,
    ) -> list[str]:
        """Build the jscpd command with all arguments."""
        config_excludes = self.config.get("exclude_dirs", [])
        all_ignores = list(dict.fromkeys(self._DEFAULT_IGNORES + config_excludes))
        ignore_str = ",".join(all_ignores)

        # Restrict formats to match cache_inputs/is_applicable — otherwise
        # jscpd scans every file type it recognises (SVG, HTML, markdown, …)
        # and flags e.g. logo assets as "code duplication".
        return [
            "npx",
            "jscpd",
            "--format",
            "python,javascript,typescript,jsx,tsx",
            "--min-tokens",
            str(min_tokens),
            "--min-lines",
            str(min_lines),
            "--threshold",
            str(self.threshold),
            "--reporters",
            "json",
            "--output",
            report_output,
            "--ignore",
            ignore_str + ",cursor-rules,**/__tests__/**,**/*.test.*,**/*.spec.*",
        ] + include_dirs

    def _parse_report(self, report_path: str) -> Optional[dict[str, Any]]:
        """Parse jscpd JSON report. Returns None on error."""
        try:
            with open(report_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def _format_result(self, report: dict[str, Any], duration: float) -> CheckResult:
        """Format the check result from parsed report."""
        duplicates = report.get("duplicates", [])
        stats = report.get("statistics", {})
        total_percentage = stats.get("total", {}).get("percentage", 0)

        if total_percentage <= self.threshold:
            if len(duplicates) == 0:
                output_msg = "No duplication detected"
            else:
                output_msg = (
                    f"Duplication at {total_percentage:.1f}% "
                    f"(threshold: {self.threshold}%). "
                    f"{len(duplicates)} clone(s) found but within limits."
                )
            return self._create_result(
                status=CheckStatus.PASSED, duration=duration, output=output_msg
            )

        # Format violation details
        violations = self._format_duplicates(duplicates)
        detail = "Code duplication exceeds acceptable levels.\n\n"
        detail += "Duplicate blocks:\n" + "\n".join(violations[:10])
        if len(violations) > 10:
            detail += f"\n... and {len(violations) - 10} more"

        # Per-clone findings anchored at the first file's start line
        findings: List[Finding] = []
        for dup in duplicates:
            first = dup.get("firstFile", {})
            second = dup.get("secondFile", {})
            start = first.get("startLoc", {}).get("line")
            end = first.get("endLoc", {}).get("line")
            fname = first.get("name")
            sname = second.get("name", "?")
            sline = second.get("startLoc", {}).get("line", "?")
            if fname:
                findings.append(
                    Finding(
                        message=f"Duplicate of {sname}:{sline} ({dup.get('lines', 0)} lines)",
                        level=FindingLevel.ERROR,
                        file=fname,
                        line=start if isinstance(start, int) else None,
                        end_line=end if isinstance(end, int) else None,
                    )
                )
        if not findings:
            findings = [
                Finding(
                    message=f"Duplication {total_percentage:.1f}% exceeds {self.threshold}%",
                    level=FindingLevel.ERROR,
                )
            ]

        # Summarise which files dominate — if 140 of 162 findings are
        # in tests/, the fix is an exclusion, not a refactor.
        file_counts: dict[str, int] = {}
        for f in findings:
            if f.file:
                file_counts[f.file] = file_counts.get(f.file, 0) + 1
        top = sorted(file_counts.items(), key=lambda kv: -kv[1])[:3]
        top_str = ", ".join(f"{fn} ({n})" for fn, n in top) if top else "?"

        fix = (
            "Extract real clones into shared helpers. "
            f"Top offenders: {top_str}. "
            "If duplication is in tests, examples, or generated code, "
            'add those paths to checks.source-duplication.exclude_dirs '
            "in .sb_config.json — don't refactor test boilerplate."
        )

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=detail,
            error="Excessive code duplication detected",
            fix_suggestion=fix,
            findings=findings,
        )

    def _merge_ast_findings(
        self,
        jscpd_result: CheckResult,
        ast_findings: list[Finding],
        start_time: float,
    ) -> CheckResult:
        """Merge AST ambiguity-mine findings into a jscpd result."""
        final_duration = time.time() - start_time
        all_findings = list(jscpd_result.findings) + ast_findings
        ast_detail = "\n".join(f"  {f.message}" for f in ast_findings)
        merged_output = (
            jscpd_result.output
            + "\n\nAmbiguity mines (function names duplicated across files):\n"
            + ast_detail
        )
        status = jscpd_result.status
        if status in (CheckStatus.PASSED, CheckStatus.WARNED):
            status = CheckStatus.FAILED
        return self._create_result(
            status=status,
            duration=final_duration,
            output=merged_output,
            error=jscpd_result.error,
            fix_suggestion=(jscpd_result.fix_suggestion or _AMBIGUITY_MINE_FIX),
            findings=all_findings,
        )

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()

        include_dirs = self.config.get("include_dirs", ["."])
        if not include_dirs:
            include_dirs = ["."]

        # AST-based function-name duplication scan.
        # Runs independently of jscpd — uses only the stdlib ast module.
        ast_findings = self._scan_duplicate_function_names(project_root, include_dirs)

        # Check jscpd availability
        jscpd_error = self._check_jscpd_availability(project_root)
        if jscpd_error:
            duration = time.time() - start_time
            if ast_findings:
                ast_detail = "\n".join(f"  {f.message}" for f in ast_findings)
                return self._create_result(
                    status=CheckStatus.FAILED,
                    duration=duration,
                    output=(
                        f"jscpd unavailable ({jscpd_error}), but AST scan found issues:\n"
                        + ast_detail
                    ),
                    error="Ambiguity mines detected (jscpd skipped)",
                    fix_suggestion=_AMBIGUITY_MINE_FIX,
                    findings=ast_findings,
                )
            return self._create_result(
                status=CheckStatus.WARNED,
                duration=duration,
                error=jscpd_error,
                fix_suggestion="Install jscpd: npm install -g jscpd",
                findings=[Finding(message=jscpd_error, level=FindingLevel.WARNING)],
            )

        # Get config values
        min_tokens = self.config.get("min_tokens", MIN_TOKENS)
        min_lines = self.config.get("min_lines", MIN_LINES)

        with tempfile.TemporaryDirectory(prefix="jscpd-") as temp_dir:
            report_output = os.path.join(temp_dir, "jscpd-report")
            cmd = self._build_jscpd_command(
                report_output, include_dirs, min_tokens, min_lines
            )

            result = self._run_command(cmd, cwd=project_root, timeout=300)
            duration = time.time() - start_time

            report_path = os.path.join(report_output, "jscpd-report.json")
            if not os.path.exists(report_path):
                if result.returncode == 0:
                    if ast_findings:
                        ast_detail = "\n".join(f"  {f.message}" for f in ast_findings)
                        return self._create_result(
                            status=CheckStatus.FAILED,
                            duration=duration,
                            output="No jscpd duplication detected, but AST scan found issues:\n"
                            + ast_detail,
                            fix_suggestion=_AMBIGUITY_MINE_FIX,
                            findings=ast_findings,
                        )
                    return self._create_result(
                        status=CheckStatus.PASSED,
                        duration=duration,
                        output="No duplication detected",
                    )
                return self._create_result(
                    status=CheckStatus.FAILED if ast_findings else CheckStatus.ERROR,
                    duration=duration,
                    error=result.stderr or "jscpd failed to produce report",
                    findings=ast_findings or None,
                    fix_suggestion=_AMBIGUITY_MINE_FIX if ast_findings else None,
                )

            report = self._parse_report(report_path)
            if report is None:
                return self._create_result(
                    status=CheckStatus.FAILED if ast_findings else CheckStatus.ERROR,
                    duration=duration,
                    error="Failed to parse jscpd report",
                    findings=ast_findings or None,
                    fix_suggestion=_AMBIGUITY_MINE_FIX if ast_findings else None,
                )

            jscpd_result = self._format_result(report, duration)

        if not ast_findings:
            return jscpd_result

        return self._merge_ast_findings(jscpd_result, ast_findings, start_time)

    def measure_scope(self, project_root: str) -> Optional[ScopeInfo]:
        """Measure scope — counts files across all supported languages."""
        include_dirs = self.config.get("include_dirs") or ["."]
        return count_source_scope(
            project_root,
            include_dirs=list(include_dirs),
            extensions={".py", ".js", ".ts", ".jsx", ".tsx"},
        )

    def _format_duplicates(self, duplicates: List[Dict[str, Any]]) -> List[str]:
        """Format duplicate entries for display."""
        violations: List[str] = []
        for dup in duplicates:
            first = dup.get("firstFile", {})
            second = dup.get("secondFile", {})
            lines = dup.get("lines", 0)
            violations.append(
                f"  {first.get('name', '?')}:{first.get('startLoc', {}).get('line', '?')}-"
                f"{first.get('endLoc', {}).get('line', '?')} ↔ "
                f"{second.get('name', '?')}:{second.get('startLoc', {}).get('line', '?')}-"
                f"{second.get('endLoc', {}).get('line', '?')} ({lines} lines)"
            )
        return violations

    # ── Ambiguity-mine detection ──────────────────────────────────────

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
        """Build a triage-oriented fix_strategy for the calling LLM.

        The strategy presents the evidence and the five classification
        options with per-category instructions.  The LLM sorts; we
        don't guess.
        """
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
        """AST scan for module-level function names defined in 2+ files.

        Catches small-function "ambiguity mines" that fall below jscpd's
        min_tokens threshold.  Only top-level (module-scope) functions
        are indexed — class methods are naturally disambiguated by their
        class.

        For each duplicate, extracts the actual function source so the
        calling LLM can classify the type of duplication and take the
        right action.
        """
        config_excludes = set(self.config.get("exclude_dirs", []))
        skip_dirs = _AST_SKIP_DIRS | config_excludes

        # func_name → [(relative_path, lineno, source_text)]
        func_index: dict[str, list[tuple[str, int, str]]] = {}

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

            # Determine if all copies are textually identical
            # (normalised via textwrap.dedent to ignore indentation)
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
