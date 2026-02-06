"""Bogus test detection via AST analysis.

Catches test functions that exist structurally but don't test anything:
- Empty bodies (pass, ..., or docstring-only)
- Tautological assertions (assert True, assert 1 == 1, assert not False)
- Test functions with no assert statements and no assertion helpers

These patterns are a common reward-hacking vector for AI agents:
the agent creates tests to satisfy coverage requirements without
actually exercising any behavior.
"""

import ast
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set

from slopmop.checks.base import BaseCheck, ConfigField, GateCategory
from slopmop.core.result import CheckResult, CheckStatus

# Pytest assertion helpers that count as "real" assertions
ASSERTION_HELPERS: Set[str] = {
    "pytest.raises",
    "pytest.warns",
    "pytest.approx",
    "pytest.fail",
    # mock assertion methods
    "assert_called",
    "assert_called_once",
    "assert_called_with",
    "assert_called_once_with",
    "assert_any_call",
    "assert_has_calls",
    "assert_not_called",
}


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

    def __init__(self, filepath: str, project_root: str) -> None:
        self.filepath = filepath
        self.rel_path = os.path.relpath(filepath, project_root)
        self.findings: List[BogusTestFinding] = []

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

        # Check for tautological assertions
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

        # Check for no assertions at all
        if not self._has_assertions(node):
            self.findings.append(
                BogusTestFinding(
                    file=self.rel_path,
                    function=node.name,
                    line=node.lineno,
                    reason="no assertions or assertion helpers found",
                )
            )

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

    def _has_assertions(self, node: ast.AST) -> bool:
        """Recursively check if a node contains any assert or assertion helper."""
        for child in ast.walk(node):
            # Direct assert statement
            if isinstance(child, ast.Assert):
                return True

            # Assertion helper calls: pytest.raises, mock.assert_called, etc.
            if isinstance(child, ast.Call):
                call_name = self._get_call_name(child)
                if call_name and any(
                    call_name.endswith(helper) for helper in ASSERTION_HELPERS
                ):
                    return True

            # pytest.raises used as context manager
            if isinstance(child, ast.With):
                for item in child.items:
                    if isinstance(item.context_expr, ast.Call):
                        call_name = self._get_call_name(item.context_expr)
                        if call_name and call_name.endswith("pytest.raises"):
                            return True

        return False

    def _get_call_name(self, node: ast.Call) -> Optional[str]:
        """Extract dotted name from a Call node."""
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            parts = []
            current: ast.expr = node.func
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            return ".".join(reversed(parts))
        return None


class BogusTestsCheck(BaseCheck):
    """Detect test functions that exist structurally but test nothing.

    Uses AST analysis to find empty tests, tautological assertions,
    and assertion-free test functions. These are a common reward-hacking
    pattern where an agent creates tests to satisfy coverage gates
    without exercising real behavior.
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
        return GateCategory.QUALITY

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

    def run(self, project_root: str) -> CheckResult:
        """Scan test files for bogus test patterns."""
        start_time = time.time()
        test_dirs = self.config.get("test_dirs", ["tests"])
        exclude_patterns = self.config.get("exclude_patterns", ["conftest.py"])
        root = Path(project_root)

        all_findings: List[BogusTestFinding] = []
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
                    tree = ast.parse(source, filename=str(test_file))
                    analyzer = _TestAnalyzer(str(test_file), project_root)
                    analyzer.visit(tree)
                    all_findings.extend(analyzer.findings)
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

        if not all_findings:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"No bogus tests found ({files_scanned} files scanned)",
            )

        detail = "\n".join(str(f) for f in all_findings)
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=f"Found {len(all_findings)} bogus test(s):\n\n{detail}",
            error=f"{len(all_findings)} test(s) don't actually test anything",
            fix_suggestion=(
                "Replace bogus tests with real assertions that exercise behavior. "
                "If a test is intentionally empty (e.g., placeholder), "
                "add a comment: # bogus-tests: ignore"
            ),
        )
