"""Bogus test detection via AST analysis.

Catches test functions that exist structurally but don't test anything:

- Empty bodies (pass, ..., or docstring-only) — always fail
- Tautological assertions (assert True, assert 1 == 1) — always fail
- Suspiciously short tests with no assertion mechanism — configurable

A test body of 0 meaningful statements is the *only* definitively wrong
length.  Tautological assertions are also definitively wrong.  Everything
else is a configurable heuristic: ``min_test_statements`` controls how
short is "too short", and ``short_test_severity`` controls whether
violations block (fail) or merely report (warn).

Assertion detection recognises:

- ``assert`` statements (Python built-in)
- ``pytest.raises``, ``pytest.warns``, ``pytest.deprecated_call``
  (context managers that ARE assertions)

Tests that use any of these are never flagged as "suspiciously short".
The heuristic targets tests that have *neither* ``assert`` nor a
recognised assertion context manager — and are also very short,
which is a strong signal of reward-hack stubs.

Set ``min_test_statements`` to 0 to disable the short-test heuristic
entirely (empty/tautological checks remain active regardless).
"""

import ast
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from slopmop.checks.base import (
    BaseCheck,
    ConfigField,
    Flaw,
    GateCategory,
    count_source_scope,
)
from slopmop.checks.constants import skip_reason_no_test_files
from slopmop.core.result import CheckResult, CheckStatus, ScopeInfo

# Inline suppression comment: adding this to a test function's def line
# or anywhere in the function body tells the checker to skip it.
SUPPRESS_MARKER = "overconfidence:short-test-ok"


@dataclass
class BogusTestFinding:
    """A single bogus test finding."""

    file: str
    function: str
    line: int
    reason: str

    def __str__(self) -> str:
        return f"  {self.file}:{self.line} {self.function}() — {self.reason}"


class _TestAnalyzer(ast.NodeVisitor):
    """AST visitor that identifies bogus test functions."""

    def __init__(
        self,
        filepath: str,
        project_root: str,
        source_lines: List[str],
        min_test_statements: int = 2,
    ) -> None:
        self.filepath = filepath
        self.rel_path = os.path.relpath(filepath, project_root)
        self.source_lines = source_lines
        self.min_test_statements = min_test_statements
        self.findings: List[BogusTestFinding] = []
        # Short-test findings are tracked separately so the caller
        # can decide whether they're failures or warnings.
        self.short_test_findings: List[BogusTestFinding] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name.startswith("test_") or (
            node.name.startswith("test")
            and (len(node.name) == 4 or node.name[4].isupper())
        ):
            self._analyze_test(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def _analyze_test(self, node: ast.FunctionDef) -> None:
        """Check a single test function for bogus patterns."""
        body = node.body

        # Check for empty body: pass, ..., or docstring-only
        # (Always a hard failure — 0 statements is the only *definitively*
        # wrong test body length.)
        if self._is_empty_body(body):
            self.findings.append(
                BogusTestFinding(
                    file=self.rel_path,
                    function=node.name,
                    line=node.lineno,
                    reason="empty test body (pass/ellipsis/docstring-only)",
                )
            )
            return

        # Check for tautological assertions (always a hard failure)
        tautology = self._find_tautology(body)
        if tautology:
            self.findings.append(
                BogusTestFinding(
                    file=self.rel_path,
                    function=node.name,
                    line=node.lineno,
                    reason=f"tautological assertion: {tautology}",
                )
            )
            return

        # Inline suppression only applies to the short-test heuristic.
        # Empty bodies and tautological assertions are always flagged.
        if self._is_suppressed(node):
            return

        # Short-test heuristic: no assertion mechanism AND few statements.
        # We recognise assert statements and pytest assertion context
        # managers (raises, warns, deprecated_call).  Tests that use
        # either are never flagged as "suspiciously short".
        if not self._has_assertion_mechanism(node):
            meaningful = self._count_meaningful_statements(body)
            if meaningful <= self.min_test_statements:
                self.short_test_findings.append(
                    BogusTestFinding(
                        file=self.rel_path,
                        function=node.name,
                        line=node.lineno,
                        reason=(
                            f"suspiciously short test ({meaningful} statement(s), "
                            f"no assertions)"
                        ),
                    )
                )

    def _is_suppressed(self, node: ast.FunctionDef) -> bool:
        """Check if a test has the inline suppression comment."""
        # Check the def line and the range of lines covered by the function.
        # end_lineno is guaranteed on Python 3.8+ after ast.parse();
        # we require 3.10+, but the type stubs declare it Optional.
        end_line: int = node.end_lineno if node.end_lineno is not None else node.lineno
        for lineno in range(node.lineno, end_line + 1):
            idx = lineno - 1  # source_lines is 0-indexed
            if 0 <= idx < len(self.source_lines):
                if SUPPRESS_MARKER in self.source_lines[idx]:
                    return True
        return False

    def _count_meaningful_statements(self, body: List[ast.stmt]) -> int:
        """Count non-trivial statements in a function body."""
        return sum(
            1
            for stmt in body
            if not isinstance(stmt, ast.Pass)
            and not self._is_ellipsis(stmt)
            and not self._is_docstring(stmt)
        )

    # Pytest context managers that act as assertions
    _PYTEST_ASSERTION_CALLS = frozenset(
        {
            "pytest.raises",
            "pytest.warns",
            "pytest.deprecated_call",
        }
    )

    def _has_assertion_mechanism(self, node: ast.AST) -> bool:
        """Check if a node contains any assertion mechanism.

        Recognises:
        - ``assert`` statements
        - ``pytest.raises``, ``pytest.warns``, ``pytest.deprecated_call``
        """
        for child in ast.walk(node):
            if isinstance(child, ast.Assert):
                return True
            # Check for pytest assertion context managers used via `with`
            if isinstance(child, ast.With):
                for item in child.items:
                    call_name = self._get_with_call_name(item.context_expr)
                    if call_name in self._PYTEST_ASSERTION_CALLS:
                        return True
        return False

    def _get_with_call_name(self, node: ast.expr) -> Optional[str]:
        """Extract dotted call name from a `with` context expression."""
        if not isinstance(node, ast.Call):
            return None
        return self._get_call_name(node)

    def _is_empty_body(self, body: List[ast.stmt]) -> bool:
        """Check if function body is effectively empty."""
        meaningful = [
            stmt
            for stmt in body
            if not isinstance(stmt, (ast.Pass,))
            and not self._is_ellipsis(stmt)
            and not self._is_docstring(stmt)
        ]
        return len(meaningful) == 0

    def _is_ellipsis(self, node: ast.stmt) -> bool:
        """Check if statement is just `...` (Ellipsis)."""
        if isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Constant) and node.value.value is ...:
                return True
        return False

    def _is_docstring(self, node: ast.stmt) -> bool:
        """Check if statement is a docstring (string expression)."""
        if isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, str
            ):
                return True
        return False

    def _find_tautology(self, body: List[ast.stmt]) -> Optional[str]:
        """Check if the ONLY assertion in the body is tautological.

        Returns the tautology string if found, None otherwise.
        Only flags when the tautology is the sole meaningful statement
        (excluding docstrings). Tests that do real work AND have a
        tautological assertion are not flagged.
        """
        meaningful = [
            stmt
            for stmt in body
            if not self._is_docstring(stmt) and not isinstance(stmt, ast.Pass)
        ]

        # Only flag if the body is just one or two tautological asserts
        if not meaningful:
            return None

        for stmt in meaningful:
            if not self._is_tautological_assert(stmt):
                return None  # Has non-tautological content, not bogus

        # All meaningful statements are tautological asserts
        return ast.dump(meaningful[0])

    def _is_tautological_assert(self, node: ast.stmt) -> bool:
        """Check if a statement is a tautological assertion."""
        if not isinstance(node, ast.Assert):
            return False

        test = node.test

        # assert True
        if isinstance(test, ast.Constant) and test.value is True:
            return True

        # assert 1 (or any truthy constant)
        if isinstance(test, ast.Constant) and test.value in (1, "nonempty"):
            return True

        # assert not False / assert not 0 / assert not None
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            if isinstance(test.operand, ast.Constant) and test.operand.value in (
                False,
                0,
                None,
            ):
                return True

        # assert 1 == 1 / assert "a" == "a" (identical constant comparisons)
        if isinstance(test, ast.Compare) and len(test.comparators) == 1:
            if len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq):
                left = test.left
                right = test.comparators[0]
                if (
                    isinstance(left, ast.Constant)
                    and isinstance(right, ast.Constant)
                    and left.value == right.value
                ):
                    return True

        return False

    def _get_call_name(self, node: ast.Call) -> Optional[str]:
        """Extract dotted name from a Call node."""
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            parts: list[str] = []
            current: ast.expr = node.func
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            return ".".join(reversed(parts))
        return None


class BogusTestsCheck(BaseCheck):
    """Bogus test detection via AST analysis.

    Pure Python check (no external tool). Parses test files to find
    test functions that exist structurally but don't test anything.

    **Always fail (definitively wrong):**

    - Empty bodies (pass, ..., or docstring-only)
    - Tautological assertions (assert True, assert 1 == 1)

    **Configurable (heuristic):**

    - Suspiciously short tests with no assertion mechanism

    A test body of 0 meaningful statements is the *only* definitively
    wrong length.  The short-test heuristic is a configurable signal:
    body complexity distinguishes reward-hack stubs from real tests.

    Assertion detection recognises ``assert`` statements AND
    ``pytest.raises``, ``pytest.warns``, ``pytest.deprecated_call``
    context managers.  Tests using any of these are never flagged
    as suspiciously short.

    Profiles: commit, pr

    Configuration:
      test_dirs: ["tests"] — directories to scan for test files.
      exclude_patterns: ["conftest.py"] — conftest files contain
          fixtures, not tests, so they're excluded by default.
      min_test_statements: 2 — tests with no assertion mechanism
          and this many or fewer meaningful statements are flagged.
          Set to 0 to disable the short-test heuristic (empty and
          tautological checks remain active).
      short_test_severity: "fail" — "fail" or "warn" for short
          tests.  Empty/tautological tests always fail regardless.

    Inline suppression:
      Add ``# overconfidence:short-test-ok`` to a test function's
      def line or body to suppress short-test findings for that test.

    Common failures:
      Empty test body: Replace ``pass`` or ``...`` with actual
          assertions that exercise behavior.
      Tautological assertion: Replace ``assert True`` or
          ``assert 1 == 1`` with assertions on real return values.
      Suspiciously short test: Add assert/pytest.raises/etc., or
          if the test is intentionally assertion-free (e.g., smoke
          test), add ``# overconfidence:short-test-ok``.  If most
          tests that fail are legitimate, consider lowering
          ``min_test_statements`` or setting it to 0.

    Re-validate:
      ./sm validate deceptiveness:bogus-tests --verbose
    """

    @property
    def name(self) -> str:
        return "bogus-tests"

    @property
    def display_name(self) -> str:
        return "🧟 Bogus Tests"

    @property
    def description(self) -> str:
        return "Detect test functions that exist but don't test anything"

    @property
    def category(self) -> GateCategory:
        return GateCategory.DECEPTIVENESS

    @property
    def flaw(self) -> Flaw:
        return Flaw.DECEPTIVENESS

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="test_dirs",
                field_type="string[]",
                default=["tests"],
                description="Directories to scan for test files",
            ),
            ConfigField(
                name="exclude_patterns",
                field_type="string[]",
                default=["conftest.py"],
                description="File patterns to exclude from scanning",
            ),
            ConfigField(
                name="min_test_statements",
                field_type="integer",
                default=1,
                min_value=0,
                max_value=50,
                description=(
                    "Tests with no assertion mechanism (assert/pytest.raises"
                    "/pytest.warns) and this many or fewer meaningful "
                    "statements are flagged as suspiciously short. "
                    "Set to 0 to disable (empty/tautological still caught)."
                ),
            ),
            ConfigField(
                name="short_test_severity",
                field_type="string",
                default="fail",
                choices=["fail", "warn"],
                description=(
                    "Severity for suspiciously short tests: 'fail' blocks "
                    "the gate, 'warn' reports but does not block"
                ),
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        """Check if there are test files to scan."""
        test_dirs = self.config.get("test_dirs", ["tests"])
        root = Path(project_root)
        for test_dir in test_dirs:
            d = root / test_dir
            if d.exists() and any(d.rglob("test_*.py")):
                return True
        return False

    def skip_reason(self, project_root: str) -> str:
        """Return skip reason when no test files exist to scan."""
        test_dirs = self.config.get("test_dirs", ["tests"])
        return skip_reason_no_test_files(test_dirs)

    def measure_scope(self, project_root: str) -> Optional[ScopeInfo]:
        """Report scope as test files in configured test_dirs."""
        test_dirs = self.config.get("test_dirs", ["tests"])
        return count_source_scope(
            project_root, include_dirs=test_dirs, extensions={".py"}
        )

    def run(self, project_root: str) -> CheckResult:
        """Scan test files for bogus test patterns."""
        start_time = time.time()
        test_dirs = self.config.get("test_dirs", ["tests"])
        exclude_patterns = self.config.get("exclude_patterns", ["conftest.py"])
        min_stmts = self.config.get("min_test_statements", 1)
        short_severity = self.config.get("short_test_severity", "fail")
        root = Path(project_root)

        all_findings: List[BogusTestFinding] = []
        all_short_findings: List[BogusTestFinding] = []
        files_scanned = 0
        parse_errors: List[str] = []

        for test_dir in test_dirs:
            d = root / test_dir
            if not d.exists():
                continue

            for test_file in sorted(d.rglob("test_*.py")):
                # Skip excluded patterns
                if any(pat in test_file.name for pat in exclude_patterns):
                    continue

                files_scanned += 1
                try:
                    source = test_file.read_text(encoding="utf-8")
                    source_lines = source.splitlines()
                    tree = ast.parse(source, filename=str(test_file))
                    analyzer = _TestAnalyzer(
                        str(test_file),
                        project_root,
                        source_lines,
                        min_test_statements=min_stmts,
                    )
                    analyzer.visit(tree)
                    all_findings.extend(analyzer.findings)
                    all_short_findings.extend(analyzer.short_test_findings)
                except (SyntaxError, UnicodeDecodeError) as e:
                    parse_errors.append(
                        f"  {os.path.relpath(str(test_file), project_root)}: {e}"
                    )

        duration = time.time() - start_time

        if parse_errors:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                error=f"Failed to parse {len(parse_errors)} test file(s)",
                output="\n".join(parse_errors),
            )

        return self._build_result(
            all_findings,
            all_short_findings,
            files_scanned,
            duration,
            short_severity,
        )

    def _build_result(
        self,
        hard_findings: List[BogusTestFinding],
        short_findings: List[BogusTestFinding],
        files_scanned: int,
        duration: float,
        short_severity: str,
    ) -> CheckResult:
        """Build the final check result from collected findings.

        Separates always-fail findings (empty body, tautological) from
        configurable short-test findings, and tailors the fix suggestion
        so users aren't told to use suppression comments for findings
        that cannot be suppressed.
        """
        hard_fail = len(hard_findings) > 0
        short_fail = short_severity == "fail" and len(short_findings) > 0
        short_warn = short_severity == "warn" and len(short_findings) > 0

        total = len(hard_findings) + len(short_findings)

        if total == 0:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"No bogus tests found ({files_scanned} files scanned)",
            )

        combined = hard_findings + short_findings
        detail = "\n".join(str(f) for f in combined)

        # Tailor fix suggestions: suppression only works for short-test
        # findings, not hard failures (empty body / tautological).
        if hard_fail and not short_findings:
            fix_suggestion = (
                "Rewrite these tests to include real assertions — "
                "empty and tautological tests cannot be suppressed"
            )
        elif hard_fail and short_findings:
            fix_suggestion = (
                "Rewrite empty/tautological tests (cannot be suppressed). "
                "For short tests, add assertions or "
                '"# overconfidence:short-test-ok" to suppress'
            )
        else:
            fix_suggestion = (
                "Review and either rewrite or add "
                '"# overconfidence:short-test-ok" comment to suppress'
            )

        if hard_fail or short_fail:
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=f"Found {total} bogus test(s):\n\n{detail}",
                error=f"{total} test(s) don't actually test anything",
                fix_suggestion=fix_suggestion,
            )

        # short_warn is True here
        return self._create_result(
            status=CheckStatus.WARNED,
            duration=duration,
            output=f"Found {total} suspicious test(s):\n\n{detail}",
            error=f"{total} suspiciously short test(s) found",
            fix_suggestion=fix_suggestion,
        )
