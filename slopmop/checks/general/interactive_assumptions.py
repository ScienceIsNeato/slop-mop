"""Detect commands that assume interactive TTY input.

Myopia: short-sighted commands that work fine when you're sitting at a
terminal but silently stall (or error out) in CI pipelines, Docker builds,
and headless agents that have no TTY to read from.

Pattern classes:

  npx without --yes
      npx will prompt "Need to install the following packages: …" when
      the requested package is not already in node_modules.  Without
      --yes that prompt hangs forever.  Fix: add --yes as the first
      npx argument (``npx --yes <tool>``).

  apt-get/apt install without -y
      apt will ask "Do you want to continue? [Y/n]".  Without -y (or
      DEBIAN_FRONTEND=noninteractive) that prompt hangs in any
      non-interactive context.  Fix: add -y (``apt-get install -y <pkg>``).

Files scanned: *.sh, *.bash, *.zsh, *.fish, *.yml, *.yaml,
               Dockerfile*, Makefile, GNUmakefile, makefile
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import ClassVar, List

from slopmop.checks.base import (
    SCOPE_EXCLUDED_DIRS,
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    GateLevel,
    RemediationChurn,
    ToolContext,
)
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel

# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------

# Extensions whose files may contain shell/CI commands.
_COMMAND_EXTS: frozenset[str] = frozenset(
    {".sh", ".bash", ".zsh", ".fish", ".yml", ".yaml"}
)

# Bare filenames (without extension) whose files may contain commands.
_COMMAND_FILENAMES: frozenset[str] = frozenset({"Makefile", "GNUmakefile", "makefile"})

# Directories to skip (never flag findings from here).
_DEFAULT_EXCLUDED = SCOPE_EXCLUDED_DIRS | {
    "node_modules",
    "vendor",
    ".husky",  # git hooks — dev environment is always present
    "testdata",
    "fixtures",
    "test",
    "tests",
}

# ---------------------------------------------------------------------------
# Compiled regexes
# ---------------------------------------------------------------------------

# Matches the npx command token (word boundary so "npxish" won't match).
_NPX_RE: re.Pattern[str] = re.compile(r"\bnpx\b")

# Presence of --yes anywhere on the line satisfies the npx pattern.
_NPX_YES_RE: re.Pattern[str] = re.compile(r"--yes\b")

# apt / apt-get install invocations.
_APT_RE: re.Pattern[str] = re.compile(r"\bapt(?:-get)?\s+install\b")

# Any of: -y, --yes, --assume-yes, -qq (all suppress interactivity for apt).
_APT_NONINTERACTIVE_RE: re.Pattern[str] = re.compile(
    r"-y\b|--yes\b|--assume-yes\b|-qq\b|DEBIAN_FRONTEND=noninteractive"
)

# A line that is visually a comment in sh/make/yaml/Dockerfile.
_COMMENT_LINE_RE: re.Pattern[str] = re.compile(r"^\s*#")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_scannable(path: Path) -> bool:
    """Return True when this file should be scanned for interactive patterns."""
    name = path.name
    if path.suffix.lower() in _COMMAND_EXTS:
        return True
    # Bare filenames (Makefile, GNUmakefile, …)
    if path.suffix == "" and name in _COMMAND_FILENAMES:
        return True
    # Dockerfile and its variants: Dockerfile.dev, Dockerfile.prod, …
    if name == "Dockerfile" or name.startswith("Dockerfile."):
        return True
    return False


def _scan_line(
    line: str,
    lineno: int,
    rel: Path,
    hits: List[str],
    findings: List[Finding],
) -> None:
    """Append to hits/findings for any interactive-assumption pattern in *line*."""
    # Skip comment lines — they're documentation, not executable commands.
    if _COMMENT_LINE_RE.match(line):
        return

    # -----------------------------------------------------------------------
    # Pattern 1: npx without --yes
    # -----------------------------------------------------------------------
    if _NPX_RE.search(line) and not _NPX_YES_RE.search(line):
        msg = (
            "npx invocation without --yes: will prompt to install packages "
            "interactively and hang in CI / headless environments"
        )
        hits.append(f"{rel}:{lineno}: npx-without-yes")
        findings.append(
            Finding(
                message=msg,
                level=FindingLevel.ERROR,
                file=str(rel),
                line=lineno,
                rule_id="npx-without-yes",
            )
        )

    # -----------------------------------------------------------------------
    # Pattern 2: apt-get / apt install without -y (or equivalent)
    # -----------------------------------------------------------------------
    if _APT_RE.search(line) and not _APT_NONINTERACTIVE_RE.search(line):
        msg = (
            "apt-get/apt install without -y: will prompt for confirmation "
            "and hang in Docker builds and CI containers"
        )
        hits.append(f"{rel}:{lineno}: apt-without-y")
        findings.append(
            Finding(
                message=msg,
                level=FindingLevel.ERROR,
                file=str(rel),
                line=lineno,
                rule_id="apt-without-y",
            )
        )


# ---------------------------------------------------------------------------
# Gate class
# ---------------------------------------------------------------------------


class InteractiveAssumptionsCheck(BaseCheck):
    """Flag commands that assume interactive TTY input.

    A PURE regex scan for command patterns that silently stall in CI
    pipelines and agent shells where no human is waiting at a terminal:

      npx <tool>          — prompts to install the package unless --yes
                            is passed.  Fix: ``npx --yes <tool>``.

      apt-get install     — prompts for confirmation unless -y is passed.
                            Fix: ``apt-get install -y <pkg>``.

    PURE check — no external tools, zero setup required.

    Level: scour (PR sweep, not every commit).

    Configuration:
      exclude_dirs: [] — additional directories to skip.

    Common failures:

      npx invocation missing --yes:
        Before: npx jest --coverage
        After:  npx --yes jest --coverage

      apt without -y:
        Before: apt-get install python3
        After:  apt-get install -y python3

    Re-check:
      sm scour -g myopia:interactive-assumptions --verbose
    """

    tool_context: ClassVar[ToolContext] = ToolContext.PURE
    role = CheckRole.DIAGNOSTIC
    level = GateLevel.SCOUR
    remediation_churn = RemediationChurn.DOWNSTREAM_CHANGES_VERY_UNLIKELY

    @property
    def name(self) -> str:
        return "interactive-assumptions"

    @property
    def display_name(self) -> str:
        return "🙋 Interactive Assumptions (npx, apt)"

    @property
    def gate_description(self) -> str:
        return (
            "🙋 Catches commands that hang in CI/agents: "
            "npx without --yes, apt install without -y"
        )

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
                name="exclude_dirs",
                field_type="string[]",
                default=[],
                description="Additional directories to exclude from the scan",
                permissiveness="more_is_stricter",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        """Return True when the project contains at least one scannable file."""
        root = Path(project_root)
        for path in root.rglob("*"):
            if not path.is_file() or not _is_scannable(path):
                continue
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if not (set(rel.parts) & _DEFAULT_EXCLUDED):
                return True
        return False

    def skip_reason(self, project_root: str) -> str:
        return "No shell scripts, CI configs, or Dockerfiles found"

    def run(self, project_root: str) -> CheckResult:
        start = time.perf_counter()
        root = Path(project_root)

        user_exclude: set[str] = set(self.config.get("exclude_dirs") or [])
        excluded = _DEFAULT_EXCLUDED | user_exclude

        hits: List[str] = []
        findings: List[Finding] = []
        files_scanned = 0

        for path in sorted(root.rglob("*")):
            if not path.is_file() or not _is_scannable(path):
                continue
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if set(rel.parts) & excluded:
                continue

            files_scanned += 1
            try:
                content = path.read_text(errors="replace")
            except OSError:
                continue

            for lineno, line in enumerate(content.splitlines(), 1):
                _scan_line(line, lineno, rel, hits, findings)

        elapsed = time.perf_counter() - start

        if not findings:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=elapsed,
                output=f"No interactive-assumption patterns ({files_scanned} files scanned)",
            )

        preview = "\n".join(hits[:20])
        more = f"\n… and {len(hits) - 20} more" if len(hits) > 20 else ""
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=elapsed,
            output=f"{preview}{more}",
            findings=findings,
            error=(
                f"Found {len(findings)} interactive-assumption pattern(s) "
                f"across {files_scanned} file(s) scanned."
            ),
            fix_suggestion=(
                "Add non-interactive flags to the commands above:\n"
                "  npx: add --yes as the first argument  →  npx --yes <tool>\n"
                "  apt: add -y flag                      →  apt-get install -y <pkg>\n"
                "To suppress a false positive, add the directory to\n"
                "  myopia.gates.interactive-assumptions.exclude_dirs in .sb_config.json"
            ),
        )
