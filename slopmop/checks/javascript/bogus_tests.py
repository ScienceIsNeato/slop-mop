"""JavaScript/TypeScript bogus test detection via regex analysis.

Catches test functions that exist structurally but don't test anything:
- Empty bodies (empty arrow functions or just comments)
- Tautological assertions (expect(true).toBe(true), expect(1).toEqual(1))
- Test functions with no expect() calls

These patterns are a common reward-hacking vector for AI agents:
the agent creates tests to satisfy coverage requirements without
actually exercising any behavior.
"""

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Pattern, Tuple

from slopmop.checks.base import (
    BaseCheck,
    ConfigField,
    Flaw,
    GateCategory,
    JavaScriptCheckMixin,
)
from slopmop.core.result import CheckResult, CheckStatus

# File patterns to scan
TEST_FILE_PATTERNS = [
    "*.test.ts",
    "*.test.tsx",
    "*.test.js",
    "*.test.jsx",
    "*.spec.ts",
    "*.spec.tsx",
    "*.spec.js",
    "*.spec.jsx",
]

# Directories to skip
SKIP_DIRS = {"node_modules", ".git", "dist", "build", "coverage", "__mocks__"}


@dataclass
class BogusTestFinding:
    """A single bogus test finding."""

    file: str
    test_name: str
    line: int
    reason: str

    def __str__(self) -> str:
        return f"  {self.file}:{self.line} {self.test_name} — {self.reason}"


# Regex patterns for test detection
# Matches: test('name', () => { ... }) or it('name', () => { ... })
# Also matches: test('name', async () => { ... })
TEST_DEFINITION_PATTERN: Pattern[str] = re.compile(
    r"(?:test|it)\s*\(\s*['\"`]([^'\"`]+)['\"`]\s*,\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{",
    re.MULTILINE,
)

# Alternative pattern for function() syntax
TEST_FUNCTION_PATTERN: Pattern[str] = re.compile(
    r"(?:test|it)\s*\(\s*['\"`]([^'\"`]+)['\"`]\s*,\s*(?:async\s*)?function\s*\([^)]*\)\s*\{",
    re.MULTILINE,
)

# Tautological assertion patterns
TAUTOLOGY_PATTERNS: List[Tuple[Pattern[str], str]] = [
    # expect(true).toBe(true)
    (
        re.compile(r"expect\s*\(\s*true\s*\)\s*\.toBe\s*\(\s*true\s*\)"),
        "expect(true).toBe(true)",
    ),
    (
        re.compile(r"expect\s*\(\s*false\s*\)\s*\.toBe\s*\(\s*false\s*\)"),
        "expect(false).toBe(false)",
    ),
    # expect(true).toEqual(true)
    (
        re.compile(r"expect\s*\(\s*true\s*\)\s*\.toEqual\s*\(\s*true\s*\)"),
        "expect(true).toEqual(true)",
    ),
    (
        re.compile(r"expect\s*\(\s*false\s*\)\s*\.toEqual\s*\(\s*false\s*\)"),
        "expect(false).toEqual(false)",
    ),
    # expect(1).toBe(1) or any single digit
    (
        re.compile(r"expect\s*\(\s*(\d+)\s*\)\s*\.toBe\s*\(\s*\1\s*\)"),
        "expect(N).toBe(N)",
    ),
    (
        re.compile(r"expect\s*\(\s*(\d+)\s*\)\s*\.toEqual\s*\(\s*\1\s*\)"),
        "expect(N).toEqual(N)",
    ),
    # expect('string').toBe('string')
    (
        re.compile(
            r"expect\s*\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\.toBe\s*\(\s*['\"](\1)['\"]\s*\)"
        ),
        "expect('x').toBe('x')",
    ),
    # expect().toBeTruthy() on literal true
    (
        re.compile(r"expect\s*\(\s*true\s*\)\s*\.toBeTruthy\s*\(\s*\)"),
        "expect(true).toBeTruthy()",
    ),
    # expect().toBeFalsy() on literal false
    (
        re.compile(r"expect\s*\(\s*false\s*\)\s*\.toBeFalsy\s*\(\s*\)"),
        "expect(false).toBeFalsy()",
    ),
]

# Pattern to detect any expect() call
EXPECT_PATTERN: Pattern[str] = re.compile(r"expect\s*\(", re.MULTILINE)

# Pattern to detect assertion methods that don't use expect (rare but valid)
ALTERNATIVE_ASSERTIONS: List[Pattern[str]] = [
    re.compile(r"\.toHaveBeenCalled"),
    re.compile(r"\.toThrow"),
    re.compile(r"assert[\.\(]"),
    # Node.js test runner assertions (node:assert)
    re.compile(r"\bdeepEqual\s*\("),
    re.compile(r"\bstrictEqual\s*\("),
    re.compile(r"\bequal\s*\("),
    re.compile(r"\bnotEqual\s*\("),
    re.compile(r"\bnotDeepEqual\s*\("),
    re.compile(r"\bnotStrictEqual\s*\("),
    re.compile(r"\bok\s*\("),
    re.compile(r"\bfail\s*\("),
    re.compile(r"\bthrows\s*\("),
    re.compile(r"\bdoesNotThrow\s*\("),
    re.compile(r"\brejects\s*\("),
    re.compile(r"\bdoesNotReject\s*\("),
    re.compile(r"\bmatch\s*\("),
    re.compile(r"\bdoesNotMatch\s*\("),
    # React Testing Library async utilities (often contain assertions in callbacks)
    re.compile(r"\bwaitFor\s*\("),
    re.compile(r"\bwaitForElementToBeRemoved\s*\("),
    re.compile(
        r"\bfindBy"
    ),  # findByText, findByTestId, etc. - async queries that throw
    re.compile(r"\bfindAllBy"),  # findAllByText, etc.
    # Custom waitFor* helpers (common pattern for encapsulated assertions)
    re.compile(r"\bwaitFor[A-Z]"),  # waitForLocationButton, waitForNullLocation, etc.
]


def _find_test_files(project_root: str, exclude_dirs: List[str]) -> Iterator[Path]:
    """Find all test files in the project with a single directory walk."""
    root = Path(project_root)
    skip = SKIP_DIRS | set(exclude_dirs)

    # Build suffix set from patterns (e.g. '.test.ts', '.spec.jsx')
    test_suffixes = {p.lstrip("*") for p in TEST_FILE_PATTERNS}

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune excluded directories in-place
        dirnames[:] = [d for d in dirnames if d not in skip]

        for filename in filenames:
            if any(filename.endswith(suffix) for suffix in test_suffixes):
                yield Path(dirpath) / filename


def _strip_comments(body: str) -> str:
    """Remove single-line and multi-line comments from body."""
    body = re.sub(r"//.*$", "", body, flags=re.MULTILINE)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    return body


def _extract_test_body(content: str, start_pos: int) -> Tuple[str, int]:
    """Extract the body of a test function from content starting at brace position.

    Handles braces inside string literals and comments correctly.
    Returns (body_content, end_position).
    """
    brace_count = 1
    pos = start_pos + 1  # Start after opening brace
    length = len(content)

    while pos < length and brace_count > 0:
        char = content[pos]

        # Skip string literals (single/double/backtick quoted)
        if char in ("'", '"', "`"):
            quote = char
            pos += 1
            while pos < length:
                if content[pos] == "\\" and pos + 1 < length:
                    pos += 2  # Skip escaped character
                    continue
                if content[pos] == quote:
                    pos += 1
                    break
                pos += 1
            continue

        # Skip single-line comments
        if char == "/" and pos + 1 < length and content[pos + 1] == "/":
            pos += 2
            while pos < length and content[pos] != "\n":
                pos += 1
            continue

        # Skip multi-line comments
        if char == "/" and pos + 1 < length and content[pos + 1] == "*":
            pos += 2
            while pos + 1 < length:
                if content[pos] == "*" and content[pos + 1] == "/":
                    pos += 2
                    break
                pos += 1
            continue

        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
        pos += 1

    body = content[start_pos + 1 : pos - 1]
    return body, pos


def _is_empty_body(body: str) -> bool:
    """Check if test body is effectively empty."""
    stripped = _strip_comments(body).strip()
    return len(stripped) == 0


def _check_tautology(body: str) -> Optional[str]:
    """Check if body contains tautological assertions. Returns reason if found."""
    stripped = _strip_comments(body)
    for pattern, reason in TAUTOLOGY_PATTERNS:
        if pattern.search(stripped):
            return reason
    return None


def _has_assertions(body: str) -> bool:
    """Check if body has any assertion calls."""
    stripped = _strip_comments(body)
    if EXPECT_PATTERN.search(stripped):
        return True
    for pattern in ALTERNATIVE_ASSERTIONS:
        if pattern.search(stripped):
            return True
    return False


def _analyze_file(filepath: Path, project_root: str) -> List[BogusTestFinding]:
    """Analyze a single test file for bogus patterns."""
    findings: List[BogusTestFinding] = []
    rel_path = str(filepath.relative_to(project_root))

    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return findings  # Skip files we can't read

    # Find all test definitions
    for pattern in [TEST_DEFINITION_PATTERN, TEST_FUNCTION_PATTERN]:
        for match in pattern.finditer(content):
            test_name = match.group(1)
            # Find the line number
            line_num = content[: match.start()].count("\n") + 1

            # Find opening brace position
            brace_start = match.end() - 1  # Pattern ends with {

            # Extract body
            body, _ = _extract_test_body(content, brace_start)

            # Check for empty body
            if _is_empty_body(body):
                findings.append(
                    BogusTestFinding(
                        file=rel_path,
                        test_name=test_name,
                        line=line_num,
                        reason="empty test body",
                    )
                )
                continue

            # Check for tautology
            tautology = _check_tautology(body)
            if tautology:
                findings.append(
                    BogusTestFinding(
                        file=rel_path,
                        test_name=test_name,
                        line=line_num,
                        reason=f"tautological assertion: {tautology}",
                    )
                )
                continue

            # Check for no assertions
            if not _has_assertions(body):
                findings.append(
                    BogusTestFinding(
                        file=rel_path,
                        test_name=test_name,
                        line=line_num,
                        reason="no expect() or assertion calls found",
                    )
                )

    return findings


class JavaScriptBogusTestsCheck(BaseCheck, JavaScriptCheckMixin):
    """Detect bogus JavaScript/TypeScript tests via regex analysis.

    Scans test files for patterns that indicate fake or meaningless tests:
    - Empty test bodies (no code)
    - Tautological assertions (expect(true).toBe(true))
    - Tests with no expect() calls

    These patterns are common when AI agents try to satisfy coverage
    requirements without actually testing anything.

    Profiles: commit, pr

    Configuration:
      max_allowed: 0 — Maximum bogus tests before failure (default: 0)
      exclude_dirs: [] — Additional directories to skip

    Common failures:
      Empty test body: The test function has no code. Either add real
          assertions or delete the test.
      Tautological assertion: The test asserts a literal value equals
          itself. Replace with a real value from your code.
      No assertions: The test runs code but never checks results. Add
          expect() calls to verify behavior.

    Re-validate:
      ./sm validate deceptiveness:js-bogus-tests --verbose
    """

    @property
    def name(self) -> str:
        return "js-bogus-tests"

    @property
    def display_name(self) -> str:
        return "🎭 Bogus Tests (JS/TS)"

    @property
    def category(self) -> GateCategory:
        return GateCategory.DECEPTIVENESS

    @property
    def flaw(self) -> Flaw:
        return Flaw.DECEPTIVENESS

    @property
    def depends_on(self) -> List[str]:
        return []

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="max_allowed",
                field_type="integer",
                default=0,
                description="Maximum bogus tests allowed (0 = none)",
            ),
            ConfigField(
                name="exclude_dirs",
                field_type="string[]",
                default=[],
                description="Additional directories to exclude from scanning",
            ),
        ]

    def skip_reason(self, project_root: str) -> str:
        """Return reason for skipping — delegate to JavaScriptCheckMixin."""
        return JavaScriptCheckMixin.skip_reason(self, project_root)

    def is_applicable(self, project_root: str) -> bool:
        """Check if this is a JavaScript project with test files."""
        if not self.is_javascript_project(project_root):
            return False

        # Check for test files
        root = Path(project_root)
        for pattern in TEST_FILE_PATTERNS:
            if any(root.rglob(pattern)):
                return True
        return False

    def run(self, project_root: str) -> CheckResult:
        """Scan test files for bogus patterns."""
        start_time = time.time()

        max_allowed = self.config.get("max_allowed", 0)
        exclude_dirs = self.config.get("exclude_dirs", [])

        findings: List[BogusTestFinding] = []
        files_scanned = 0

        for filepath in _find_test_files(project_root, exclude_dirs):
            files_scanned += 1
            file_findings = _analyze_file(filepath, project_root)
            findings.extend(file_findings)

        duration = time.time() - start_time

        if not findings:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"✅ No bogus tests found ({files_scanned} files scanned)",
            )

        # Build output
        output_lines = [
            f"Found {len(findings)} bogus test(s):",
            "",
        ]
        for finding in findings:
            output_lines.append(str(finding))

        if len(findings) <= max_allowed:
            output_lines.insert(
                0, f"⚠️ {len(findings)} bogus tests found (max allowed: {max_allowed})"
            )
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output="\n".join(output_lines),
            )

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output="\n".join(output_lines),
            error=f"Found {len(findings)} bogus test(s) (max allowed: {max_allowed})",
        )
