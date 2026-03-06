"""Abstract base class for quality gate checks.

All quality checks inherit from BaseCheck and implement the required methods.
This enables the Open/Closed principle - add new checks without modifying
existing code.
"""

import logging
import os
import shutil
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional

from slopmop.core.result import (
    CheckResult,
    CheckStatus,
    Finding,
    ScopeInfo,
)
from slopmop.subprocess.runner import SubprocessResult, SubprocessRunner, get_runner

logger = logging.getLogger(__name__)


class GateLevel(Enum):
    """Gate execution level — controls which commands include this gate.

    Every gate has a level that determines when it runs:

    SWAB — Runs on every commit.  Fast, local, no network or PR context
           required.  ``sm swab`` runs all SWAB-level gates.
           This is the default for all gates.

    SCOUR — Runs during thorough validation (PR readiness, CI).
            May require network access, PR context (e.g. unresolved
            comments), or expensive dependency auditing.
            ``sm scour`` runs ALL gates (SWAB + SCOUR).

    The naming comes from cleaning: a swab is a quick daily pass,
    a scour is the deep clean before inspection.
    """

    SWAB = "swab"
    SCOUR = "scour"


class CheckRole(Enum):
    """Architectural tier — what kind of value a gate provides.

    slop-mop gates fall into two fundamentally different classes:

    FOUNDATION — Wraps standard, off-the-shelf dev tooling (black, mypy,
        pytest, eslint, radon, bandit, etc.) and answers binary structural
        questions: does it lint, do types check, do tests pass.  These
        gates are the floor everything else stands on.  Their value-add
        is *orchestration* — running the right tool at the right time with
        the right config — not novel detection.  If you ripped slop-mop
        out, you could reproduce a FOUNDATION gate with one shell command.

    DIAGNOSTIC — Novel analysis with no off-the-shelf equivalent.  AST
        walking for empty test bodies, git-diff analysis of config
        weakening, cross-file similarity detection, bespoke pattern
        matching.  These gates are *why slop-mop exists as a distinct
        tool* rather than a Makefile.  You cannot reproduce a DIAGNOSTIC
        gate with a pip install.

    Default is DIAGNOSTIC.  Gates must affirmatively declare themselves
    FOUNDATION — the burden of proof is "I wrap a standard tool and that
    tool does the real work", not the other way around.

    Role is determined by *value-add*, not mechanism.  A gate that runs
    eslint (standard tool) with a bespoke rule config that no public
    eslint preset includes is DIAGNOSTIC — the novelty is in the rule,
    not the runner.  A gate that runs radon with default thresholds is
    FOUNDATION — radon does the detection, slop-mop just picks a number.
    """

    FOUNDATION = "foundation"
    DIAGNOSTIC = "diagnostic"

    def __str__(self) -> str:
        return self.value


class ToolContext(Enum):
    """How a gate resolves the external tools it needs.

    Every gate must declare a tool_context so the framework knows how to
    locate executables and what to do when a project lacks a virtual
    environment.

    Categories:

    PURE — No external tools.  Pure Python analysis (AST, regex, file
           scanning).  Always runnable.  Examples: bogus-tests.py, code-sprawl,
           gate-dodging.

    SM_TOOL — Tool ships with slop-mop (bundled via pipx / pip dependency).
              Resolved via ``find_tool(name)`` → project venv → VIRTUAL_ENV
              → PATH.  The tool does NOT need to import the target project's
              code.  Examples: black, vulture, radon, bandit, pip-audit.

    PROJECT — Tool must run inside the target project's Python environment
              because it imports project code (pytest loads conftest.py and
              test fixtures, coverage instruments project modules, jinja2
              compiles project templates).  Resolved via
              ``get_project_python()``.  When no project venv exists the
              gate **warns and skips** instead of failing — with an
              actionable message telling the user exactly how to create one.

    NODE — Tool is resolved via npm/npx from the project's node_modules.
           Requires ``package.json`` at project root.  Examples: eslint,
           jest, prettier.
    """

    PURE = "pure"
    SM_TOOL = "sm_tool"
    PROJECT = "project"
    NODE = "node"


def find_tool(name: str, project_root: str) -> Optional[str]:
    """Find a tool executable, preferring the project's own environment.

    Resolution order:
    1. project_root/venv/bin/<name>  — local venv (highest priority)
    2. project_root/.venv/bin/<name> — local .venv
    3. $VIRTUAL_ENV/bin/<name>       — currently-activated venv
    4. shutil.which(<name>)          — system PATH (e.g. pipx-installed sm)

    When sm is installed via pipx, step 4 finds pipx's bundled tools.
    Steps 1-3 ensure the project's own tools are preferred, which matters
    for tools like pytest (plugins), bandit, or semgrep where version
    differences or missing plugins can affect results.

    Args:
        name: Executable name (e.g. "vulture", "pyright").
        project_root: Project root directory.

    Returns:
        Absolute path to the executable, or None if not found.
    """
    root = Path(project_root)
    for venv_dir in ["venv", ".venv"]:
        candidate = root / venv_dir / "bin" / name
        if candidate.exists():
            return str(candidate)
        # Windows
        candidate = root / venv_dir / "Scripts" / f"{name}.exe"
        if candidate.exists():
            return str(candidate)

    # Check the currently activated venv (e.g. user ran `source venv/bin/activate`
    # but the venv lives outside project_root, or sm is invoked via pipx)
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env:
        candidate = Path(virtual_env) / "bin" / name
        if candidate.exists():
            return str(candidate)
        candidate = Path(virtual_env) / "Scripts" / f"{name}.exe"
        if candidate.exists():
            return str(candidate)

    return shutil.which(name)


# Standard directories to exclude from scope counting
SCOPE_EXCLUDED_DIRS = {
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
    ".slopmop",
    ".egg-info",
}


def count_source_scope(
    project_root: str,
    include_dirs: Optional[List[str]] = None,
    extensions: Optional[set[str]] = None,
    exclude_dirs: Optional[set[str]] = None,
) -> ScopeInfo:
    """Count source files and lines in target directories.

    Provides a fast, lightweight scan for scope metrics — no parsing,
    just file counting and line counting.  Used by checks to report
    how many files/LOC they examined.

    Args:
        project_root: Project root directory
        include_dirs: Directories to scan (relative to root). Defaults to ["."]
        extensions: File extensions to include (e.g. {".py"}). None = all source files
        exclude_dirs: Additional directories to exclude (merged with SCOPE_EXCLUDED_DIRS)

    Returns:
        ScopeInfo with file and line counts
    """
    root = Path(project_root)
    dirs = include_dirs or ["."]
    excluded = SCOPE_EXCLUDED_DIRS | (exclude_dirs or set())

    total_files = 0
    total_lines = 0

    for dir_name in dirs:
        scan_path = root / dir_name
        if not scan_path.exists():
            continue

        for file_path in scan_path.rglob("*"):
            if not file_path.is_file():
                continue

            # Skip excluded directories
            parts = set(file_path.relative_to(root).parts)
            if parts & excluded:
                continue

            # Skip .egg-info directories (not exact match, contains pattern)
            rel_str = str(file_path.relative_to(root))
            if ".egg-info" in rel_str:
                continue

            # Filter by extension if specified
            if extensions and file_path.suffix not in extensions:
                continue

            total_files += 1
            try:
                content = file_path.read_text(errors="replace")
                total_lines += content.count("\n") + (
                    1 if content and not content.endswith("\n") else 0
                )
            except (OSError, UnicodeDecodeError):
                pass  # Skip unreadable files

    return ScopeInfo(files=total_files, lines=total_lines)


class Flaw(Enum):
    """AI character flaws that checks are designed to catch.

    These represent the fundamental weaknesses in LLM-generated code:
    - OVERCONFIDENCE: "Trust me, it works" - untested assumptions
    - DECEPTIVENESS: "Look, I wrote tests!" - theater over substance
    - LAZINESS: "I'll clean that up later" - mess left behind
    - MYOPIA: "But I fixed the bug!" - tunnel vision, missing big picture
    """

    OVERCONFIDENCE = ("overconfidence", "💯", "Overconfidence")
    DECEPTIVENESS = ("deceptiveness", "🎭", "Deceptiveness")
    LAZINESS = ("laziness", "🦥", "Laziness")
    MYOPIA = ("myopia", "👓", "Myopia")

    def __init__(self, key: str, emoji: str, display_name: str):
        self.key = key
        self.emoji = emoji
        self._display_name = display_name

    @property
    def display(self) -> str:
        return f"{self.emoji} {self._display_name}"

    @property
    def display_name(self) -> str:
        return self._display_name


class GateCategory(Enum):
    """Categories for organizing quality gates.

    All checks are categorized by the AI character flaw they detect.
    Language is an implementation detail, not an organizing principle.
    """

    # Flaw-based categories
    OVERCONFIDENCE = ("overconfidence", "💯", "Overconfidence")
    DECEPTIVENESS = ("deceptiveness", "🎭", "Deceptiveness")
    LAZINESS = ("laziness", "🦥", "Laziness")
    MYOPIA = ("myopia", "👓", "Myopia")

    # Other categories
    GENERAL = ("general", "🔧", "General")

    def __init__(self, key: str, emoji: str, display_name: str):
        self.key = key
        self.emoji = emoji
        self._display_name = display_name

    @property
    def display(self) -> str:
        return f"{self.emoji} {self._display_name}"

    @property
    def display_name(self) -> str:
        """Human-readable category name."""
        return self._display_name

    @classmethod
    def from_key(cls, key: str) -> Optional["GateCategory"]:
        """Get category by key string (e.g. 'laziness' -> LAZINESS)."""
        for cat in cls:
            if cat.key == key:
                return cat
        return None


@dataclass
class ConfigField:
    """Definition of a configuration field for a check.

    The ``permissiveness`` attribute is used by the gate-dodging check
    to determine whether a config change makes a gate *more* permissive.
    Possible values:

    - ``"higher_is_stricter"`` — higher numeric/alpha value = stricter
    - ``"lower_is_stricter"``  — lower numeric/alpha value = stricter
    - ``"fewer_is_stricter"``  — fewer list items = stricter
    - ``"more_is_stricter"``   — more list items = stricter
    - ``"fail_is_stricter"``   — severity hierarchy: fail > warn
    - ``"true_is_stricter"``   — boolean True = stricter
    - ``None`` — neutral / not a strictness knob (default)
    """

    name: str
    field_type: str  # "boolean", "integer", "string", "string[]"
    default: Any
    description: str = ""
    required: bool = False
    min_value: Optional[int] = None  # For integers
    max_value: Optional[int] = None  # For integers
    choices: Optional[List[str]] = None  # For enums
    permissiveness: Optional[str] = None  # See class docstring


# Standard config fields that all gates have
STANDARD_CONFIG_FIELDS = [
    ConfigField(
        name="enabled",
        field_type="boolean",
        default=False,
        description="Whether this gate is enabled",
        permissiveness="true_is_stricter",
    ),
    ConfigField(
        name="auto_fix",
        field_type="boolean",
        default=False,
        description="Automatically fix issues when possible",
    ),
    ConfigField(
        name="config_file_path",
        field_type="string",
        default=None,
        description="Path to tool's native config file (e.g., pytest.ini, .bandit)",
        required=False,
    ),
]


class BaseCheck(ABC):
    """Abstract base class for all quality gate checks.

    Subclasses must implement:
    - name: Unique identifier for the check (e.g., 'lint-format')
    - display_name: Human-readable name with emoji
    - category: GateCategory for this check
    - is_applicable(): Whether check applies to current project
    - run(): Execute the check and return result

    Optional overrides:
    - tool_context: ToolContext declaring how tools are resolved
    - depends_on: List of check names this depends on
    - config_schema: Additional config fields beyond standard ones
    - can_auto_fix(): Whether issues can be auto-fixed
    - auto_fix(): Attempt to fix issues automatically
    """

    # Default tool context — subclasses SHOULD override.  PURE is the safest
    # default because it makes no assumptions about tool availability.
    tool_context: ClassVar[ToolContext] = ToolContext.PURE

    # Default gate level — subclasses override to SCOUR for gates that
    # only run during thorough validation (PR readiness, CI).
    level: ClassVar[GateLevel] = GateLevel.SWAB

    # Default check role — DIAGNOSTIC until proven otherwise.  Gates that
    # wrap standard tooling (black, pytest, eslint, etc.) where the tool's
    # core logic IS the check should override to CheckRole.FOUNDATION.
    # See CheckRole docstring for the full taxonomy.
    role: ClassVar[CheckRole] = CheckRole.DIAGNOSTIC

    def __init__(
        self, config: Dict[str, Any], runner: Optional[SubprocessRunner] = None
    ):
        """Initialize the check.

        Args:
            config: Configuration dictionary for this check
            runner: Subprocess runner to use (default: global runner)
        """
        self.config = config
        self._runner = runner or get_runner()

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this check.

        This should be a lowercase, hyphenated string like 'lint-format'.
        Note: Do NOT include the language prefix - that comes from category.
        """

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable display name with emoji.

        Example: '🎨 Lint & Format (black, isort, flake8)'
        """

    @property
    @abstractmethod
    def category(self) -> GateCategory:
        """The language/type category for this check.

        Returns:
            GateCategory enum value (PYTHON, JAVASCRIPT, or flaw-based category)
        """

    @property
    @abstractmethod
    def flaw(self) -> Flaw:
        """The AI character flaw this check catches.

        Returns:
            Flaw enum value (OVERCONFIDENCE, DECEPTIVENESS, LAZINESS, MYOPIA)
        """

    @property
    def gate_description(self) -> str:
        """One-line description of what this gate does, for README tables.

        This is the single source of truth for the "What It Does" column
        in auto-generated gate tables.  Override in each check to provide
        a concise, emoji-prefixed summary.

        Defaults to ``display_name`` if not overridden.
        """
        return self.display_name

    @property
    def full_name(self) -> str:
        """Full name including category prefix.

        Returns:
            String like 'laziness:sloppy-formatting.py'
        """
        return f"{self.category.key}:{self.name}"

    @property
    def depends_on(self) -> List[str]:
        """List of check names this check depends on.

        Override to specify dependencies. Dependent checks run after their
        dependencies complete successfully.
        """
        return []

    @property
    def superseded_by(self) -> Optional[str]:
        """Full name of check that supersedes this one.

        If another check fully encompasses this check's functionality,
        return its full name (e.g., 'security:full'). This prevents
        recommending a subset check when its superset is already running.

        Returns:
            Full name of superseding check, or None if not superseded
        """
        return None

    @property
    def config_schema(self) -> List[ConfigField]:
        """Additional configuration fields for this check.

        Override to add check-specific config fields beyond the standard ones
        (enabled, auto_fix). Standard fields are automatically included.

        Returns:
            List of ConfigField definitions
        """
        return []

    def get_full_config_schema(self) -> List[ConfigField]:
        """Get complete config schema including standard fields.

        Returns:
            List of all ConfigField definitions (standard + check-specific)
        """
        return STANDARD_CONFIG_FIELDS + self.config_schema

    @abstractmethod
    def is_applicable(self, project_root: str) -> bool:
        """Return True if this check applies to the given project.

        Args:
            project_root: Path to project root directory

        Returns:
            True if check should run, False to skip
        """

    def skip_reason(self, project_root: str) -> str:
        """Return reason why this check is not applicable.

        Called when is_applicable returns False to provide a human-readable
        explanation for why the check was skipped.

        Default implementation provides a generic message based on check type.
        Override for more specific skip reasons.

        Args:
            project_root: Path to project root directory

        Returns:
            Human-readable skip reason
        """
        # Default implementation provides a generic message
        return "Not applicable to this project"

    @abstractmethod
    def run(self, project_root: str) -> CheckResult:
        """Execute the check and return result.

        Args:
            project_root: Path to project root directory

        Returns:
            CheckResult with status, output, and any error info
        """

    def can_auto_fix(self) -> bool:
        """Return True if this check can automatically fix issues.

        Override to enable auto-fix capability.
        """
        return False

    def auto_fix(self, project_root: str) -> bool:
        """Attempt to automatically fix issues.

        Args:
            project_root: Path to project root directory

        Returns:
            True if fix was successful, False otherwise
        """
        return False

    def _create_result(
        self,
        status: CheckStatus,
        duration: float,
        output: str = "",
        error: Optional[str] = None,
        fix_suggestion: Optional[str] = None,
        auto_fixed: bool = False,
        status_detail: Optional[str] = None,
        findings: Optional[List[Finding]] = None,
    ) -> CheckResult:
        """Helper to create a CheckResult for this check.

        Args:
            status: Check status
            duration: Execution time in seconds
            output: Check output
            error: Error message if failed
            fix_suggestion: Suggested fix for failures
            auto_fixed: Whether issues were auto-fixed
            findings: Structured per-issue findings.  **Required** for
                FAILED/WARNED — these become inline PR annotations in
                GitHub Code Scanning.  Omitting them triggers a
                UserWarning (see rail below).  PASSED/SKIPPED/ERROR
                don't emit SARIF and can leave this at ``None``.

        Returns:
            CheckResult instance
        """
        # Rail: catch missing findings during gate development instead
        # of letting SarifReporter's synthetic fallback paper over it.
        # No file to anchor to?  Pass Finding(message=...) anyway —
        # that satisfies this AND labels the Security tab entry.
        if not findings and status in (CheckStatus.FAILED, CheckStatus.WARNED):
            warnings.warn(
                f"{self.full_name!r} returned {status.value.upper()} without "
                f"findings — SARIF output will use a synthetic location-less "
                f"alert. Pass findings=[Finding(...)] to _create_result() "
                f"for inline PR annotations in GitHub Code Scanning.",
                UserWarning,
                stacklevel=2,
            )

        # Auto-generate output from structured findings when gate
        # didn't supply free-form text.  Ensures console display shows
        # the per-issue breakdown even for gates that only return
        # Finding objects.
        if findings and not output:
            output = "\n".join(str(f) for f in findings)

        return CheckResult(
            name=self.full_name,
            status=status,
            duration=duration,
            output=output,
            error=error,
            fix_suggestion=fix_suggestion,
            auto_fixed=auto_fixed,
            category=self.category.key if self.category else None,
            status_detail=status_detail,
            role=self.role.value,
            findings=findings or [],
        )

    def _run_command(
        self,
        command: List[str],
        cwd: Optional[str] = None,
        timeout: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> SubprocessResult:
        """Run a command using the subprocess runner.

        When the first element is a bare executable name (not an absolute
        path), it is resolved via find_tool() using cwd as the project root.
        This ensures the project's own tools (from its venv) take priority
        over sm's own bundled dependencies — critical when sm is installed
        via pipx, where bundled pytest won't have framework-specific plugins
        (pytest-django, pytest-asyncio, etc.) that the project relies on.

        Args:
            command: Command to run
            cwd: Working directory (also used as project root for tool lookup)
            timeout: Timeout in seconds
            env: Optional environment variables for the subprocess

        Returns:
            SubprocessResult
        """
        if command and cwd and not Path(command[0]).is_absolute():
            resolved = find_tool(command[0], cwd)
            if resolved:
                command = [resolved, *command[1:]]
        return self._runner.run(command, cwd=cwd, timeout=timeout, env=env)
