"""Dart/Flutter bogus test detection via lightweight parsing."""

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Pattern, Tuple

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    RemediationChurn,
    ToolContext,
    count_source_scope,
)
from slopmop.checks.constants import (
    NO_PUBSPEC_YAML_FOUND,
    tautological_assertion_reason,
)
from slopmop.checks.dart.common import find_dart_test_files, find_pubspec_dirs
from slopmop.core.result import (
    CheckResult,
    CheckStatus,
    Finding,
    FindingLevel,
    ScopeInfo,
)

TEST_PATTERN: Pattern[str] = re.compile(
    r"(?:test|testWidgets)\s*\(\s*['\"`]([^'\"`]+)['\"`]\s*,\s*\([^)]*\)\s*(?:async\s*)?\{",
    re.MULTILINE,
)
EXPECT_PATTERN: Pattern[str] = re.compile(r"\b(expect|expectLater|verify|fail)\s*\(")
TAUTOLOGY_PATTERNS: List[Tuple[Pattern[str], str]] = [
    (
        re.compile(r"expect\s*\(\s*true\s*,\s*isTrue\s*\)"),
        "expect(true, isTrue)",
    ),
    (
        re.compile(r"expect\s*\(\s*false\s*,\s*isFalse\s*\)"),
        "expect(false, isFalse)",
    ),
    (
        re.compile(r"expect\s*\(\s*(\d+)\s*,\s*equals\(\s*\1\s*\)\s*\)"),
        "expect(N, equals(N))",
    ),
    (
        re.compile(
            r"expect\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*equals\(\s*['\"]\1['\"]\s*\)\s*\)"
        ),
        "expect('x', equals('x'))",
    ),
]


@dataclass
class _BogusFinding:
    file: str
    test_name: str
    line: int
    reason: str


def _strip_comments(body: str) -> str:
    body = re.sub(r"//.*$", "", body, flags=re.MULTILINE)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    return body


def _extract_body(content: str, start_pos: int) -> Tuple[str, int]:
    brace_count = 1
    pos = start_pos + 1
    length = len(content)
    while pos < length and brace_count > 0:
        char = content[pos]
        if char in ("'", '"', "`"):
            quote = char
            pos += 1
            while pos < length:
                if content[pos] == "\\" and pos + 1 < length:
                    pos += 2
                    continue
                if content[pos] == quote:
                    pos += 1
                    break
                pos += 1
            continue
        if char == "/" and pos + 1 < length and content[pos + 1] == "/":
            pos += 2
            while pos < length and content[pos] != "\n":
                pos += 1
            continue
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
    return content[start_pos + 1 : pos - 1], pos


class DartBogusTestsCheck(BaseCheck):
    """Detect Dart tests that exist structurally but don't test behavior."""

    tool_context = ToolContext.PURE
    role = CheckRole.DIAGNOSTIC
    remediation_churn = RemediationChurn.DOWNSTREAM_CHANGES_LIKELY

    @property
    def name(self) -> str:
        return "bogus-tests.dart"

    @property
    def display_name(self) -> str:
        return "🧪 Bogus Tests (Dart/Flutter)"

    @property
    def gate_description(self) -> str:
        return "🧪 Detects empty or non-assertive Dart/Flutter tests"

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
                name="max_allowed",
                field_type="integer",
                default=0,
                description="Maximum allowed bogus test findings",
                min_value=0,
                max_value=1000,
                permissiveness="lower_is_stricter",
            )
        ]

    def is_applicable(self, project_root: str) -> bool:
        return bool(find_dart_test_files(project_root))

    def skip_reason(self, project_root: str) -> str:
        if not find_pubspec_dirs(project_root):
            return NO_PUBSPEC_YAML_FOUND
        return "No Dart test files found (*_test.dart)"

    def measure_scope(self, project_root: str) -> Optional[ScopeInfo]:
        include_dirs = [
            str(pkg.relative_to(Path(project_root)))
            for pkg in find_pubspec_dirs(project_root)
        ]
        if not include_dirs:
            include_dirs = ["."]
        return count_source_scope(
            project_root, include_dirs=include_dirs, extensions={".dart"}
        )

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()
        max_allowed = int(self.config.get("max_allowed", 0))

        findings = self._scan_tests(project_root)
        duration = time.time() - start_time

        if len(findings) <= max_allowed:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"No bogus Dart tests found ({len(findings)} issue(s))",
            )

        output_lines = [f"Found {len(findings)} suspicious Dart test(s):", ""]
        for item in findings[:20]:
            output_lines.append(
                f"  {item.file}:{item.line} {item.test_name} — {item.reason}"
            )
        if len(findings) > 20:
            output_lines.append(f"  ... and {len(findings) - 20} more")

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output="\n".join(output_lines),
            error=f"{len(findings)} bogus Dart test finding(s)",
            findings=[
                Finding(
                    message=item.reason,
                    file=item.file,
                    line=item.line,
                    level=FindingLevel.ERROR,
                )
                for item in findings
            ],
            fix_suggestion=(
                "Replace empty or tautological tests with assertions against real "
                "behavior. Verify with: " + self.verify_command
            ),
        )

    def _scan_tests(self, project_root: str) -> List[_BogusFinding]:
        root = Path(project_root).resolve()
        findings: List[_BogusFinding] = []
        for test_file in find_dart_test_files(project_root):
            rel = str(test_file.resolve().relative_to(root))
            content = test_file.read_text(encoding="utf-8", errors="ignore")
            findings.extend(self._analyze_file(rel, content))
        return findings

    @staticmethod
    def _analyze_file(rel_path: str, content: str) -> List[_BogusFinding]:
        findings: List[_BogusFinding] = []
        for match in TEST_PATTERN.finditer(content):
            test_name = match.group(1)
            line_num = content[: match.start()].count("\n") + 1
            body, _ = _extract_body(content, match.end() - 1)
            stripped = _strip_comments(body).strip()

            if not stripped:
                findings.append(
                    _BogusFinding(rel_path, test_name, line_num, "empty test body")
                )
                continue

            tautology = DartBogusTestsCheck._find_tautology(stripped)
            if tautology:
                findings.append(
                    _BogusFinding(
                        rel_path,
                        test_name,
                        line_num,
                        tautological_assertion_reason(tautology),
                    )
                )
                continue

            if not EXPECT_PATTERN.search(stripped):
                findings.append(
                    _BogusFinding(
                        rel_path,
                        test_name,
                        line_num,
                        "no assertion call found (expect/expectLater/verify/fail)",
                    )
                )
        return findings

    @staticmethod
    def _find_tautology(body: str) -> Optional[str]:
        for pattern, label in TAUTOLOGY_PATTERNS:
            if pattern.search(body):
                return label
        return None
