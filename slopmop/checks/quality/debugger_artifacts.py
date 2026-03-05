"""Detect leftover debugger artifacts across all languages.

AI agents (and humans on a deadline) routinely litter code with
temporary debugging statements and forget to remove them.  Unlike
``print()`` or ``console.log()`` — which can be legitimate logging —
these patterns are **almost always** accidental leftovers:

    Python     : breakpoint(), pdb.set_trace(), ipdb.set_trace()
    JS/TS      : debugger;
    Rust       : dbg!(…), todo!()
    Go         : runtime.Breakpoint()
    C/C++      : __builtin_trap(), raise(SIGTRAP)

This is the cross-language generalisation of the ``no-debugger-imports``
example from issue #53 — shipped built-in because every test repo in the
beta exercise would benefit regardless of stack.
"""

import re
import time
from pathlib import Path
from typing import ClassVar, List, Tuple

from slopmop.checks.base import (
    SCOPE_EXCLUDED_DIRS,
    BaseCheck,
    ConfigField,
    Flaw,
    GateCategory,
    GateLevel,
    ToolContext,
)
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel

# (extensions, compiled-regex, human-label)
_PATTERNS: List[Tuple[Tuple[str, ...], re.Pattern[str], str]] = [
    (
        (".py",),
        re.compile(r"^\s*(breakpoint\s*\(\s*\)|i?pdb\.set_trace\s*\()"),
        "Python breakpoint / pdb.set_trace",
    ),
    (
        (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"),
        re.compile(r"^\s*debugger\s*;?\s*$"),
        "JS `debugger` statement",
    ),
    (
        (".rs",),
        re.compile(r"\b(dbg!|todo!)\s*\("),
        "Rust dbg!() / todo!()",
    ),
    (
        (".go",),
        re.compile(r"\bruntime\.Breakpoint\s*\("),
        "Go runtime.Breakpoint",
    ),
    (
        (".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"),
        re.compile(r"\b(__builtin_trap\s*\(|raise\s*\(\s*SIGTRAP)"),
        "C/C++ trap",
    ),
]

_ALL_EXTS = frozenset(ext for exts, _, _ in _PATTERNS for ext in exts)

# Paths that legitimately contain debugger references (tests, examples,
# docs, third-party vendored code).
_DEFAULT_EXCLUDE = SCOPE_EXCLUDED_DIRS | {
    "test",
    "tests",
    "spec",
    "__tests__",
    "testdata",
    "examples",
    "example",
    "docs",
    "vendor",
    "third_party",
}


class DebuggerArtifactsCheck(BaseCheck):
    """Flag forgotten debugger statements in source.

    PURE check — no external tools, so it runs on every repo regardless
    of what toolchain the user has installed.
    """

    tool_context: ClassVar[ToolContext] = ToolContext.PURE
    level: ClassVar[GateLevel] = GateLevel.SWAB

    @property
    def name(self) -> str:
        return "debugger-artifacts"

    @property
    def display_name(self) -> str:
        return "🐞 Debugger Artifacts"

    @property
    def gate_description(self) -> str:
        return (
            "🐞 Catches leftover breakpoint()/debugger;/dbg!()/"
            "runtime.Breakpoint() across Python, JS, Rust, Go, C"
        )

    @property
    def category(self) -> GateCategory:
        return GateCategory.DECEPTIVENESS

    @property
    def flaw(self) -> Flaw:
        # "Look, I cleaned up before committing!" — no you didn't.
        return Flaw.DECEPTIVENESS

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="exclude_dirs",
                field_type="string[]",
                default=[],
                description="Additional directories to skip",
                permissiveness="more_is_stricter",
            ),
            ConfigField(
                name="max_files",
                field_type="integer",
                default=50000,
                description=(
                    "Bail-out ceiling for mega-monorepos. Gate warns "
                    "rather than hangs when the repo is larger than this."
                ),
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        root = Path(project_root)
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in _ALL_EXTS:
                # Don't count excluded dirs towards "has source"
                if not (set(path.relative_to(root).parts) & _DEFAULT_EXCLUDE):
                    return True
        return False

    def skip_reason(self, project_root: str) -> str:
        return "No source files in supported languages found"

    def run(self, project_root: str) -> CheckResult:
        start = time.perf_counter()
        root = Path(project_root)

        user_exclude = set(self.config.get("exclude_dirs") or [])
        excluded = _DEFAULT_EXCLUDE | user_exclude
        max_files = int(self.config.get("max_files") or 50000)

        hits: List[str] = []
        findings: List[Finding] = []
        files_scanned = 0

        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in _ALL_EXTS:
                continue
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if set(rel.parts) & excluded:
                continue

            files_scanned += 1
            if files_scanned > max_files:
                return self._create_result(
                    status=CheckStatus.WARNED,
                    duration=time.perf_counter() - start,
                    output=(
                        f"Scanned {max_files} files and stopped — repo "
                        f"exceeds max_files.  Narrow via exclude_dirs."
                    ),
                )

            patterns = [p for exts, p, _ in _PATTERNS if path.suffix in exts]
            labels = {
                p.pattern: lbl for exts, p, lbl in _PATTERNS if path.suffix in exts
            }
            if not patterns:
                continue

            try:
                for lineno, line in enumerate(
                    path.read_text(errors="replace").splitlines(), 1
                ):
                    # Cheap comment skip — not worth a full parser for
                    # a pattern this narrow.
                    stripped = line.lstrip()
                    if stripped.startswith(("#", "//", "/*", "*")):
                        continue
                    for pat in patterns:
                        if pat.search(line):
                            label = labels[pat.pattern]
                            hits.append(f"{rel}:{lineno}: {label}")
                            findings.append(
                                Finding(
                                    message=label,
                                    level=FindingLevel.ERROR,
                                    file=str(rel),
                                    line=lineno,
                                    rule_id=label,
                                )
                            )
                            break
            except (OSError, UnicodeDecodeError):
                continue

        elapsed = time.perf_counter() - start

        if not hits:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=elapsed,
                output=f"No debugger artifacts ({files_scanned} files scanned)",
            )

        preview = "\n".join(hits[:20])
        more = f"\n… and {len(hits) - 20} more" if len(hits) > 20 else ""
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=elapsed,
            output=f"{preview}{more}",
            findings=findings,
            error=(
                f"Found {len(hits)} debugger artifact(s) in "
                f"{files_scanned} file(s)."
            ),
            fix_suggestion=(
                "Remove the debugging statements above before committing. "
                "If a directory is a false positive (e.g. a debugger test "
                "suite), add it to "
                "deceptiveness.gates.debugger-artifacts.exclude_dirs in "
                ".sb_config.json."
            ),
        )
