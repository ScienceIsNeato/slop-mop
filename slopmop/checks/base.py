"""Abstract base class for quality gate checks.

All quality checks inherit from BaseCheck and implement the required methods.
This enables the Open/Closed principle - add new checks without modifying
existing code.
"""

import logging
import os
import shutil
import subprocess
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Dict, Iterable, List, Optional

from slopmop.checks.metadata import Reasoning, builtin_reasoning_for_check_class
from slopmop.core.result import (
    CheckResult,
    CheckStatus,
    Finding,
    ScopeInfo,
)
from slopmop.subprocess.runner import SubprocessResult, SubprocessRunner, get_runner
from slopmop.utils import is_path_excluded

logger = logging.getLogger(__name__)


@dataclass
class GateDiagnosticResult:
    """A gate-specific health observation surfaced by ``sm doctor``.

    Gates that know about their own failure modes beyond "is the binary
    present?" can return these from ``BaseCheck.diagnose()``.  The doctor
    framework collects them and renders them alongside the standard tool
    presence checks.

    ``severity`` must be one of ``"ok"``, ``"warn"``, or ``"fail"``.
    """

    severity: str  # "ok" | "warn" | "fail"
    summary: str
    detail: str = ""
    fix_hint: str = ""


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


class RemediationChurn(Enum):
    """Likelihood that fixing this gate will cascade into other gates.

    Determines fix ordering when multiple gates fail simultaneously.
    Gates whose fixes are very likely to trigger downstream failures
    go first; gates whose fixes are isolated go last.

    DOWNSTREAM_CHANGES_VERY_LIKELY — Restructures code: refactoring
        functions, deduplicating across files, removing dead code.
        The fix reshapes file structure and will almost certainly
        invalidate other gates' fixes.

    DOWNSTREAM_CHANGES_LIKELY — Changes logic within existing
        structure: rewriting bogus tests, fixing gate-dodging,
        resolving config debt.  Modifies what code does without
        reorganising files.

    DOWNSTREAM_CHANGES_UNLIKELY — Adds new code without changing
        existing: writing tests for coverage, adding type
        annotations.  Low collision risk.  Default for all gates.

    DOWNSTREAM_CHANGES_VERY_UNLIKELY — Surface-level or generated:
        auto-formatting, removing debug artifacts, regenerating
        config.  Nearly zero interaction with other fixes.
    """

    DOWNSTREAM_CHANGES_VERY_LIKELY = 4
    DOWNSTREAM_CHANGES_LIKELY = 3
    DOWNSTREAM_CHANGES_UNLIKELY = 2
    DOWNSTREAM_CHANGES_VERY_UNLIKELY = 1


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

    DENO — Tool is resolved via the ``deno`` binary on PATH.  Requires
           ``deno.json`` or ``deno.jsonc`` at project root.  Examples:
           deno lint, deno fmt, deno test.
    """

    PURE = "pure"
    SM_TOOL = "sm_tool"
    PROJECT = "project"
    NODE = "node"
    DENO = "deno"


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

    def _is_usable_tool_path(path: Path) -> bool:
        """Return True when path exists, is executable, and has a valid shebang.

        Some stale virtualenv entrypoints are executable files whose shebang
        points to a deleted interpreter ("bad interpreter"). Treat those as
        unusable so we can fall back to a working binary on PATH.
        """
        if not path.exists() or not path.is_file() or not os.access(path, os.X_OK):
            return False

        try:
            with path.open("rb") as f:
                first_line = f.readline(256).strip()
        except OSError:
            return False

        if not first_line.startswith(b"#!"):
            return True

        shebang = first_line[2:].decode("utf-8", errors="ignore").strip()
        if not shebang:
            return True

        parts = shebang.split()
        interpreter = parts[0]

        # Handles shebangs like: #!/usr/bin/env python3
        if interpreter.endswith("/env") and len(parts) > 1:
            return shutil.which(parts[1]) is not None

        if Path(interpreter).is_absolute():
            return Path(interpreter).exists()

        return shutil.which(interpreter) is not None

    root = Path(project_root)
    for venv_dir in ["venv", ".venv"]:
        candidate = root / venv_dir / "bin" / name
        if _is_usable_tool_path(candidate):
            return str(candidate)
        # Windows
        candidate = root / venv_dir / "Scripts" / f"{name}.exe"
        if _is_usable_tool_path(candidate):
            return str(candidate)

    # Check the currently activated venv (e.g. user ran `source venv/bin/activate`
    # but the venv lives outside project_root, or sm is invoked via pipx)
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env:
        candidate = Path(virtual_env) / "bin" / name
        if _is_usable_tool_path(candidate):
            return str(candidate)
        candidate = Path(virtual_env) / "Scripts" / f"{name}.exe"
        if _is_usable_tool_path(candidate):
            return str(candidate)

    return shutil.which(name)


def _module_available(import_name: str) -> bool:
    """Return True if a Python module is importable, without importing it.

    Uses ``importlib.util.find_spec`` rather than ``import_module``: importing
    some packages (e.g. bandit) pulls in stevedore, which enumerates every
    entry-point plugin and logs a WARNING per failed load. ``find_spec`` probes
    the import machinery without executing the target package.
    """
    import importlib.util

    try:
        return importlib.util.find_spec(import_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


# Non-dot directories to exclude from scope counting (dot-prefixed directories
# are always excluded automatically via should_prune_dir()).
SCOPE_EXCLUDED_DIRS = {
    "node_modules",
    "venv",  # non-hidden venv installs
    "__pycache__",
    "dist",
    "build",
    "htmlcov",
    "cursor-rules",
    "logs",
}


# Shared ConfigField description for the near-universal exclude_dirs option,
# so gates don't each redeclare the same literal (string-duplication gate).
EXCLUDE_DIRS_DESCRIPTION = "Additional directories to exclude from the scan"


def should_prune_dir(name: str) -> bool:
    """Return True if a directory should be excluded from file scanning.

    Excludes all dot-directories (hidden dirs, e.g. .git, .venv, .tmp) plus
    known non-dot noise directories (node_modules, venv, build artifacts).
    Pass the *name* component of the directory, not a full path.
    """
    return name.startswith(".") or name in SCOPE_EXCLUDED_DIRS


def is_vendored_dir(path: str) -> bool:
    """True for a directory that holds third-party code, whatever it's named.

    Name lists miss the common cases: a virtualenv can be ``.venv``, ``env``,
    ``server/.venv``, or anything else the author chose. The marker files are
    definitive, so look for those instead of guessing from the name.
    """
    for marker in ("pyvenv.cfg", "site-packages"):
        if os.path.exists(os.path.join(path, marker)):
            return True
    return False


def git_project_files(
    project_root: str,
    extensions: Optional[set[str]] = None,
    timeout: int = 30,
) -> Optional[List[str]]:
    """Files the repository itself considers part of the project, or None.

    ``git ls-files -co --exclude-standard`` lists tracked files plus untracked
    ones that aren't ignored — exactly "the project's own files", straight from
    the authority that already knows. Returns None when this isn't a git repo
    or git can't be run, so callers fall back to walking.
    """
    try:
        result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
            ["git", "ls-files", "-co", "--exclude-standard", "-z"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    files = [entry for entry in result.stdout.split("\0") if entry]
    if extensions is not None:
        files = [f for f in files if os.path.splitext(f)[1] in extensions]
    return files


def resolve_tool_paths(
    project_root: str,
    exclude_dirs: Optional[Iterable[str]] = None,
    extensions: Optional[set[str]] = None,
    max_depth: int = 6,
    max_paths: int = 300,
) -> List[str]:
    """Concrete paths to hand an external tool, with non-source trees pruned.

    Most tools take an ignore flag — ``isort --skip``, ``flake8
    --extend-exclude``, ``detect-secrets --exclude-files`` — but apply it as a
    POST-FILTER: the walk still descends into ``node_modules`` or a nested
    ``.venv`` and pays to open every file it finds there. Handing such a tool
    ``.`` therefore costs full price for directories the config excluded.

    **The repository already knows what is source.** Ask git and the guessing
    disappears: no name list keeps up with ``.venv`` vs ``env``, an uploads
    directory full of customer images, agent worktrees under ``.claude``, or
    whatever the next repo invents. On the repo that surfaced this, git listed
    139 Python files in 24ms where walking found 20,445 — the difference
    between a 0.3s check and one that blew its 60s timeout and reported the
    kill as a phantom finding.

    Falls back to walking (pruning excluded and vendored directories at any
    depth) when there's no git available, so non-repo projects still work. This
    is the single place that decides what any tool sees, so a fix here fixes
    every gate at once.

    Returns ``["."]`` when nothing needs pruning or the list would exceed
    ``max_paths``, so callers always get a usable, correct target list.
    """
    excluded = set(SCOPE_EXCLUDED_DIRS) | set(exclude_dirs or ())

    tracked = git_project_files(project_root, extensions)
    if tracked is not None and tracked:
        kept = [f for f in tracked if not is_path_excluded(f, excluded)]
        if not kept:
            return ["."]
        if len(kept) <= max_paths:
            return sorted(kept)
        # Too many files to pass individually: collapse to their directories,
        # which stays correct because git already told us these trees hold
        # project files.
        dirs = sorted({os.path.dirname(f) or "." for f in kept})
        return dirs if len(dirs) <= max_paths else ["."]

    def is_excluded(rel: str, abs_path: str) -> bool:
        name = os.path.basename(rel)
        if should_prune_dir(name):
            return True
        if is_path_excluded(rel, excluded):
            return True
        return os.path.isdir(abs_path) and is_vendored_dir(abs_path)

    def walk(rel: str, depth: int) -> tuple[List[str], bool, bool]:
        """(paths, contains_relevant_file, anything_dropped) for ``rel``."""
        abs_path = os.path.join(project_root, rel) if rel else project_root
        try:
            children = sorted(os.listdir(abs_path))
        except OSError:
            return ([rel] if rel else []), True, False

        dropped = False
        files: List[str] = []
        subdirs: List[tuple[str, List[str], bool, bool]] = []
        relevant = False

        for name in children:
            child_rel = f"{rel}/{name}" if rel else name
            child_abs = os.path.join(project_root, child_rel)
            if is_excluded(child_rel, child_abs):
                dropped = True
                continue
            if os.path.isdir(child_abs):
                if depth + 1 >= max_depth:
                    subdirs.append((child_rel, [child_rel], True, False))
                    relevant = True
                    continue
                sub_paths, sub_relevant, sub_dropped = walk(child_rel, depth + 1)
                subdirs.append((child_rel, sub_paths, sub_relevant, sub_dropped))
                if sub_relevant:
                    relevant = True
                else:
                    # A subtree with nothing the tool cares about is one more
                    # thing it would otherwise walk.
                    dropped = True
            elif extensions is None or os.path.splitext(name)[1] in extensions:
                files.append(child_rel)
                relevant = True
            else:
                dropped = True

        dropped_below = any(sub_dropped for _, _, _, sub_dropped in subdirs)
        # Nothing dropped anywhere beneath: hand the whole directory over as a
        # single cheap argument.
        if rel and relevant and not dropped and not dropped_below:
            return [rel], True, False

        out = list(files)
        for _, sub_paths, sub_relevant, _ in subdirs:
            if sub_relevant:
                out.extend(sub_paths)
        return out, relevant, (dropped or dropped_below)

    paths, _relevant, _dropped = walk("", 0)
    if not paths or len(paths) > max_paths:
        return ["."]
    return paths


# Source-code file extensions used for project-size metrics (e.g. sm status).
# Deliberately excludes docs, data, and binary files so the scope displayed
# to users reflects actual code rather than generated or vendored content.
SOURCE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".dart",
        ".sh",
        ".bash",
        ".rb",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".swift",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",
        ".php",
        ".yml",
        ".yaml",
        ".toml",
    }
)


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
            rel_path = file_path.relative_to(root)
            if is_path_excluded(rel_path, excluded):
                continue
            if any(should_prune_dir(p) for p in rel_path.parts[:-1]):
                continue

            # Skip .egg-info directories (not exact match, contains pattern)
            rel_str = str(rel_path)
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
        name="run_on",
        field_type="string",
        default=None,
        choices=[GateLevel.SWAB.value, GateLevel.SCOUR.value],
        description=(
            "Execution rail for this gate. 'swab' runs it in both swab and scour; "
            "'scour' keeps it out of swab but still runs it during scour."
        ),
    ),
    ConfigField(
        name="extra_exclude_paths",
        field_type="string[]",
        default=[],
        description=(
            "Additional repo-relative paths or glob patterns to exclude for this "
            "gate only."
        ),
        permissiveness="fewer_is_stricter",
    ),
    ConfigField(
        name="include_paths",
        field_type="string[]",
        default=[],
        description=(
            "Repo-relative paths or glob patterns to re-include for this gate, "
            "even when they are globally excluded."
        ),
        permissiveness="more_is_stricter",
    ),
]


# ── Gate external-dependency contract ────────────────────────────────
#
# Gates that shell out to external tools declare what they need here so a
# single authority — ``sm doctor`` and, downstream, the GitHub Action — can
# enumerate and install dependencies from one source of truth instead of each
# gate detecting tools ad hoc (the scattered ``shutil.which`` problem).
#
# The manifest these produce is a CONSUMED CONTRACT (doctor reads it; the
# Action installs from it), so its shape is versioned. Bump the schema version
# on any breaking change to the serialized field set.
REQUIREMENTS_MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Requirement:
    """A single external dependency an enabled gate needs to run.

    ``optional`` encodes the distinction that matters for a CI merge gate:

    - **required** (``optional=False``) — the gate *cannot run* without it.
      A missing required tool must surface a visible, non-green
      "could-not-run" state, never a silent pass. (See
      :meth:`BaseCheck.requirement_block_result`.)
    - **optional** (``optional=True``) — the gate degrades but still runs;
      a missing optional tool is reported (so doctor can recommend it) but
      does not block.

    ``version`` is an EXACT pin (e.g. ``"1.7.5"``), never a floor. The pin is
    part of the gate definition — bumping a scanner can change findings — so it
    is bumped deliberately via a reviewed change, not floated at install time.
    ``None`` means "any present version is acceptable" (e.g. system ``git``).

    ``alternatives`` lists interchangeable names that also satisfy the
    requirement (any one present is enough) — for tools resolvable under more
    than one binary name / install path.

    ``kind`` is the INSTALL channel (how the Action installs it); ``probe`` is
    how presence is DETECTED — they are orthogonal. A pip-installed tool that's
    invoked as a binary (e.g. ``semgrep``) is ``kind="python", probe="binary"``.
    ``probe`` defaults per kind: python→import, system/npm→binary, env→env.

    ``import_name`` is the module to probe when ``probe="import"`` and the
    install name differs from the import name (e.g. ``detect-secrets`` installs
    under that name but imports as ``detect_secrets``). Empty ⇒ derive from
    ``name`` by replacing ``-`` with ``_``.
    """

    kind: str  # "system" | "python" | "npm" | "env"  — the install channel
    name: str
    version: Optional[str] = None  # exact pin; None = any present version
    reason: str = ""
    optional: bool = False
    alternatives: tuple[str, ...] = ()
    probe: str = ""  # "" = default by kind; "binary" | "import" | "env" | "none"
    import_name: str = ""  # for probe="import" when it differs from name
    # User-facing install command for slop-mop's OWN env-doctor remediation —
    # e.g. "pipx install slopmop[security]" or "Install Flutter SDK: …". Distinct
    # from how the downstream Action installs (name + version + kind): this tells
    # a slop-mop *user* how to fix their environment. Empty ⇒ doctor falls back
    # to a kind-based default ("pip install <name>").
    install_hint: str = ""

    def to_manifest(self) -> Dict[str, Any]:
        """Serialize to the deterministic manifest shape doctor/the Action read."""
        return {
            "kind": self.kind,
            "name": self.name,
            "version": self.version,
            "optional": self.optional,
            "alternatives": sorted(self.alternatives),
            "probe": self.probe,
            "import_name": self.import_name,
            "install_hint": self.install_hint,
            "reason": self.reason,
        }

    def resolved_install_hint(self) -> str:
        """The remediation to show a user, with a kind-based fallback."""
        if self.install_hint:
            return self.install_hint
        if self.kind == "python":
            return f"pip install {self.name}"
        if self.kind == "npm":
            return f"npm install -g {self.name}"
        if self.kind == "env":
            return f"Set the {self.name} environment variable"
        return f"Install {self.name}"


@dataclass(frozen=True)
class Requirements:
    """The set of external dependencies a gate needs given its current config."""

    items: tuple[Requirement, ...] = ()

    def to_manifest(self) -> List[Dict[str, Any]]:
        """Manifest entries, sorted by (kind, name) so output is byte-stable."""
        ordered = sorted(self.items, key=lambda r: (r.kind, r.name))
        return [r.to_manifest() for r in ordered]


def build_requirements_document(requirements: "Requirements") -> Dict[str, Any]:
    """Wrap requirement entries in a schema-versioned manifest document.

    This is the unit doctor emits and the Action consumes. The
    ``schema_version`` is mandatory and load-bearing: consumers pin on it.
    """
    return {
        "schema_version": REQUIREMENTS_MANIFEST_SCHEMA_VERSION,
        "requirements": requirements.to_manifest(),
    }


def pip_cli_requirement(
    name: str,
    version: Optional[str],
    reason: str,
    *,
    optional: bool = False,
    extra: Optional[str] = None,
) -> Requirement:
    """A pip-installed tool invoked as a CLI binary — the common gate case.

    Most Python quality tools (black, mypy, vulture, …) ship on PyPI but are
    run as a command, so they install via pip (``kind="python"``) yet are
    detected on PATH (``probe="binary"``). ``version`` is an EXACT pin; keep it
    in sync with pyproject's declared floor (a drift test guards this).

    ``extra`` names the slop-mop extras group that bundles this tool (``lint``,
    ``typing``, ``analysis``, ``security``) so the env-doctor can tell a slop-mop
    user to ``pipx install slopmop[<extra>]`` — one command for the whole group.
    """
    return Requirement(
        kind="python",
        name=name,
        version=version,
        probe="binary",
        reason=reason,
        optional=optional,
        install_hint=f"pipx install slopmop[{extra}]" if extra else "",
    )


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
    - init_config(): init-time config discovery for this gate only
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

    # Terminal checks run only after ALL other applicable checks have
    # completed and passed.  They are the last thing that runs in a
    # scour pass — typically used for "what's next?" navigation guidance
    # that only makes sense when the rest of the gate suite is green.
    # Set to True in subclasses that should behave this way.
    terminal: ClassVar[bool] = False

    # Likelihood that fixing this gate cascades into other gates.
    # Gates with high downstream likelihood should be fixed first.
    # This is a coarse default, not the final ordering mechanism.
    remediation_churn: ClassVar[RemediationChurn] = (
        RemediationChurn.DOWNSTREAM_CHANGES_UNLIKELY
    )

    # Fine-grained remediation ordering.
    # Lower numbers are fixed first. ``None`` means "derive a default from
    # remediation_churn". This keeps the broad churn taxonomy for docs while
    # allowing precise ordering when multiple gates share a churn band.
    #
    # This is remediation order, not execution order: checks may still be
    # dispatched concurrently, but in REMEDIATION phase the executor processes
    # completed results and applies fail-fast according to registry-derived
    # remediation priority.
    remediation_priority: ClassVar[Optional[int]] = None

    # Structured gate-level reasoning metadata. Built-in gates are populated from
    # the shared metadata registry during registration; custom gates can set this
    # directly on the class when they have equivalent context.
    REASONING: ClassVar[Optional[Reasoning]] = None

    # Whether this gate is a pure formatter gate (zero logic changes).
    # Used by refit to classify formatting-only commits as ``style:``
    # rather than relying on gate-name string matching.
    is_formatting_gate: ClassVar[bool] = False

    # External tools a gate needs are declared via requirements() (the
    # Requirement contract — name, exact pin, kind/probe, install_hint). The
    # former required_tools / required_tool_versions / install_hint class
    # attributes have been retired in favour of that single source.

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
    def verify_command(self) -> str:
        """Shell command to re-run just this gate.

        Used in fix_suggestion text to tell agents exactly how to
        verify their fix.  Centralised here to avoid string duplication
        across every gate that wants the pattern.
        """
        verb = self.effective_level.value
        return f"sm {verb} -g {self.full_name}"

    @property
    def effective_level(self) -> GateLevel:
        """Configured execution level for this gate instance."""
        run_on = self.config.get("run_on")
        if isinstance(run_on, str):
            try:
                return GateLevel(run_on)
            except ValueError:
                pass
        return self.level

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

    def requirements(self) -> Requirements:
        """External tools/packages this gate needs to run, given its config.

        The default is none. Gates that shell out to external tools (linters,
        scanners, npm CLIs, ``gh``) override this so a single authority can
        enumerate dependencies instead of each gate detecting tools ad hoc.

        Return value is CONFIG-DEPENDENT: a gate whose tool is gated behind a
        config flag should return an empty :class:`Requirements` when that flag
        is off, so the manifest reflects only what *this* repo's config needs.
        """
        return Requirements()

    @staticmethod
    def _effective_probe(req: Requirement) -> str:
        """How to detect this requirement's presence (``probe`` or kind default)."""
        if req.probe:
            return req.probe
        return {
            "python": "import",
            "system": "binary",
            "npm": "binary",
            "env": "env",
        }.get(req.kind, "binary")

    def resolve_requirement_path(
        self, req: Requirement, project_root: str
    ) -> Optional[str]:
        """Resolve a binary-probed requirement to an executable path, or ``None``.

        Tries the declared name and every ``alternatives`` entry (any one
        satisfies it), via the venv-aware :func:`find_tool`. Only meaningful for
        binary-probed requirements (a Python import has no path); returns
        ``None`` otherwise. A gate that needs to *invoke* a tool resolves it
        here, the same path :meth:`is_requirement_satisfied` checks — so "the
        gate found it" and "declared satisfied" can never disagree.
        """
        if self._effective_probe(req) != "binary":
            return None
        for candidate in (req.name, *req.alternatives):
            path = find_tool(candidate, project_root)
            if path:
                return path
        return None

    def is_requirement_satisfied(self, req: Requirement, project_root: str) -> bool:
        """Whether *req* is present, probed the way its ``kind``/``probe`` says.

        - ``binary`` → resolvable on PATH/venv (see resolve_requirement_path)
        - ``import`` → the module is importable (install-name → import-name)
        - ``env``    → the named environment variable is set and non-empty
        - ``none``   → cannot probe in-process; assumed satisfied (installer's job)
        """
        probe = self._effective_probe(req)
        if probe == "binary":
            return self.resolve_requirement_path(req, project_root) is not None
        if probe == "import":
            names = [req.import_name or req.name.replace("-", "_")]
            names += [alt.replace("-", "_") for alt in req.alternatives]
            return any(_module_available(name) for name in names)
        if probe == "env":
            # Honour alternatives like binary/import do (e.g. GH_TOKEN with a
            # GITHUB_TOKEN alternative) — any one set satisfies it.
            return any(os.environ.get(n) for n in (req.name, *req.alternatives))
        return True  # "none" — defer to the installing layer

    def missing_requirements(self, project_root: str) -> List[Requirement]:
        """Return the declared requirements that aren't satisfied in-process.

        Each requirement is probed the way its kind/probe dictates
        (binary/import/env). ``none``-probed requirements are never reported
        missing here — verifying them belongs to the installing layer.
        """
        return [
            req
            for req in self.requirements().items
            if not self.is_requirement_satisfied(req, project_root)
        ]

    def requirement_block_result(
        self, project_root: str, duration: float = 0.0
    ) -> Optional[CheckResult]:
        """Return an ERROR result if a REQUIRED tool is missing, else ``None``.

        This is the "could-not-run" state: a required dependency that isn't
        installed means the gate cannot do its job, and the run must be visibly
        non-green rather than silently passing. ``ERROR`` fails the overall
        verdict (``all_passed`` counts errors), so branch protection is not
        bypassed by a broken environment.

        Missing *optional* requirements return ``None`` here — the gate runs in
        a degraded mode and reports the absence elsewhere (doctor recommends
        the tool); they never block.

        A gate that shells out to a required tool calls this at the top of
        ``run()`` and returns the result if it is not ``None``.
        """
        required_missing = [
            r for r in self.missing_requirements(project_root) if not r.optional
        ]
        if not required_missing:
            return None
        names = ", ".join(sorted(r.name for r in required_missing))
        return self._create_result(
            status=CheckStatus.ERROR,
            duration=duration,
            output=(
                f"Cannot run {self.name}: required tool(s) not installed: "
                f"{names}. Run `sm doctor` for the exact install commands, then "
                f"re-run. (This is an environment failure, not a code failure — "
                f"the gate did not run.)"
            ),
            error=f"missing required tools: {names}",
        )

    def init_config(self, project_root: str) -> Dict[str, Any]:
        """Return init-time config overrides discovered by this gate.

        This hook is the gate-owned extension point for `sm init`. Gates that know how
        to discover their own native config or baseline files should override
        it and return only the gate-specific fields they own. The default is
        empty because most gates do not need repo-specific config-file lookup.

        `sm init` treats these values as discovered defaults, not hard
        overrides: existing non-empty gate config wins.
        """
        return {}

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

    def cache_inputs(self, project_root: str) -> Optional[str]:
        """Return a per-check fingerprint, or ``None`` to use the global one.

        The executor calls this before looking up cached results.  When
        a check inspects only a well-defined subset of files (e.g. only
        ``*.py`` files in ``src_dirs``), it should override this method
        and return a fingerprint scoped to that subset via
        :func:`slopmop.core.cache.hash_file_scope`.

        With a scoped fingerprint, editing a JavaScript file won't
        invalidate a Python-only check's cache — and vice versa.

        The default returns ``None``, which tells the executor to fall
        back to the project-wide fingerprint (conservative, always
        correct, but invalidates on *any* source change).
        """
        return None

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

    def diagnose(self, project_root: str) -> List[GateDiagnosticResult]:
        """Return gate-specific health observations for ``sm doctor``.

        Gates that know their own failure modes beyond "is the binary present?"
        can override this to surface actionable hints.  For example, a coverage
        gate might return a ``warn`` result if no ``.coverage`` data file is
        present, since that's the most common reason coverage checks fail.

        Doctor calls this for every applicable, enabled gate and renders the
        results alongside the standard tool inventory.

        The default implementation returns an empty list — no gate-specific
        issues.  Gates opt in by overriding.

        Args:
            project_root: Absolute path to the project root directory.

        Returns:
            A list of :class:`GateDiagnosticResult` observations.  Empty
            means "no gate-specific issues found."
        """
        return []

    @property
    def why_it_matters(self) -> Optional[str]:
        """Gate-level context explaining why this failure category matters."""
        reasoning = self.reasoning
        if reasoning is None:
            return None
        return reasoning.rationale

    @property
    def reasoning(self) -> Optional[Reasoning]:
        """Structured gate-level reasoning metadata."""
        if self.REASONING is not None:
            return self.REASONING
        return builtin_reasoning_for_check_class(type(self))

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
        suppress_sarif: bool = False,
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
            suppress_sarif: Suppress this result from SARIF/code-scanning
                output while preserving normal local reporting.

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
            why_it_matters=self.why_it_matters,
            findings=findings or [],
            suppress_sarif=suppress_sarif,
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
