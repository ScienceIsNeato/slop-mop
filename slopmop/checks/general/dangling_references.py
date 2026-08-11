"""Detect Markdown links that resolve in the agent's head, not on disk.

Overconfidence: an agent writes a relative link or image in a Markdown file —
``[see the guide](./docs/guide.md)``, ``![logo](../img/logo.png)`` — and moves
on. The file renders fine; the broken reference only surfaces when a reader
clicks it. The agent's mental model of the file tree disagreed with the actual
file tree, and nothing in the loop made it look. Same failure shape as code
that compiles but throws: ``"it looks linked, therefore it works."``

Scope is deliberately narrow so the check is FALSE-POSITIVE-FREE BY
CONSTRUCTION — every decision is a literal string test or a filesystem
existence check, never inference:

  * Markdown only. Markdown relative links have exactly one resolution
    semantics ("relative to the file on disk"), used identically by GitHub,
    npm, and every renderer. There is no router, base path, or build step to
    rewrite them — the HTML-serving minefield (routes, hashed assets) simply
    does not apply.
  * A reference is checked only when it is unambiguously a literal repo path.
    Anything that could legitimately resolve to something else is SKIPPED, not
    flagged: URL schemes, protocol-relative ``//``, templated ``{{ }}`` paths,
    site-absolute ``/...``, and pure ``#fragment`` anchors (anchor checking
    needs slug inference, so it is out of scope).
  * Only source-type targets (.md / images / directories) are resolved, so a
    link to a built artifact like ``guide.html`` is never mistaken for a miss.

The cost is deliberate false-negatives (broken HTML ``src``, anchors, external
404s) — all of which require inference or the network, so they are correctly
left out.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path, PurePosixPath
from typing import ClassVar, List, Optional, Tuple
from urllib.parse import unquote

from slopmop.checks.base import (
    EXCLUDE_DIRS_DESCRIPTION,
    SCOPE_EXCLUDED_DIRS,
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    GateLevel,
    RemediationChurn,
    ToolContext,
    should_prune_dir,
)
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel
from slopmop.utils import is_path_excluded

_EXCLUDED = SCOPE_EXCLUDED_DIRS | {"node_modules", "vendor", "dist", "build"}
_MARKDOWN_EXTS = (".md", ".markdown")

# Source-type targets we resolve. A suffix outside this set (e.g. .html, .js)
# might be a built/served artifact, so we skip it rather than risk a false miss.
# An empty suffix means a directory or extensionless file — always resolvable.
_SOURCE_EXTS = frozenset(
    {
        ".md",
        ".markdown",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".webp",
        ".ico",
        ".bmp",
        ".avif",
    }
)

# Markers that mean the path is templated/generated — never a literal path.
_TEMPLATE_MARKERS = ("{{", "}}", "{%", "%}", "<%", "%>", "${")

# Inline link/image target: [text](TARGET ...) — TARGET is <bracketed> or a
# whitespace-delimited token whose parentheses are balanced, so a path like
# ./docs/api(v2).md is captured whole rather than truncated at the first ")".
_INLINE_RE = re.compile(r"!?\[[^\]]*\]\(\s*(<[^>]+>|(?:[^()\s]+|\([^)]*\))+)")
# Reference definition at line start: [id]: TARGET "optional title"
_REFDEF_RE = re.compile(r"^\s*\[[^\]]+\]:\s*(<[^>]+>|\S+)")
# A leading URL scheme (mailto:, http:, tel:, …).
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")
# Fenced code block delimiter: up to 3 spaces of indent, then 3+ ` or ~.
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
# An inline code span. Subscript-then-call syntax is indistinguishable from
# a markdown link, so code spans are blanked before targets are extracted.
# A run of N backticks closes only on a run of exactly N (so a shorter run may
# appear inside the span), the span may wrap lines, and per CommonMark it
# cannot contain a blank line.
_INLINE_CODE_RE = re.compile(
    r"(?<!`)(`+)(?!`)((?:(?!\n\n).)+?)(?<!`)\1(?!`)", re.DOTALL
)


class DanglingReferencesCheck(BaseCheck):
    """Flag Markdown links/images whose relative target is not on disk.

    A PURE, network-free scan of every Markdown file: each relative link or
    image must resolve to a real file or directory in the repo. Catches the
    "it looks linked, therefore it works" overconfidence where an agent
    renames or moves a file and leaves a stale reference behind.

    False-positive-free by construction — only literal, unambiguous repo paths
    are checked; schemes, templated paths, site-absolute ``/...``, ``#``
    anchors, and non-source extensions are skipped, never flagged.

    PURE check — stdlib regex + filesystem, no external tools or network.

    Level: scour (PR-readiness / CI sweep).

    Configuration:
      exclude_dirs: [] — additional directories to skip.

    Re-check:
      sm scour -g overconfidence:dangling-references --verbose
    """

    tool_context: ClassVar[ToolContext] = ToolContext.PURE
    role = CheckRole.DIAGNOSTIC
    level = GateLevel.SCOUR
    remediation_churn = RemediationChurn.DOWNSTREAM_CHANGES_VERY_UNLIKELY

    @property
    def name(self) -> str:
        return "dangling-references"

    @property
    def display_name(self) -> str:
        return "🔗 Dangling References (broken Markdown links)"

    @property
    def gate_description(self) -> str:
        return (
            "🔗 Catches Markdown links/images pointing at a relative path that "
            "isn't on disk — broken doc links from a rename or move"
        )

    @property
    def category(self) -> GateCategory:
        return GateCategory.OVERCONFIDENCE

    @property
    def flaw(self) -> Flaw:
        return Flaw.OVERCONFIDENCE

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="exclude_dirs",
                field_type="string[]",
                default=[],
                description=EXCLUDE_DIRS_DESCRIPTION,
                permissiveness="more_is_stricter",
            ),
        ]

    def _excluded(self) -> set[str]:
        return _EXCLUDED | set(self.config.get("exclude_dirs") or [])

    def is_applicable(self, project_root: str) -> bool:
        return bool(_iter_markdown_files(Path(project_root), self._excluded()))

    def skip_reason(self, project_root: str) -> str:
        return "No Markdown files found"

    def run(self, project_root: str) -> CheckResult:
        start = time.perf_counter()
        root = Path(project_root)
        files = _iter_markdown_files(root, self._excluded())

        findings: List[Finding] = []
        for md in files:
            findings += _scan_markdown(md, root)

        return self._result(findings, len(files), time.perf_counter() - start)

    def _result(
        self, findings: List[Finding], file_count: int, elapsed: float
    ) -> CheckResult:
        if not findings:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=elapsed,
                output=f"All Markdown references resolve ({file_count} file(s))",
            )
        preview = "\n".join(f"  {f.file}:{f.line}: {f.message}" for f in findings[:20])
        more = f"\n  … and {len(findings) - 20} more" if len(findings) > 20 else ""
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=elapsed,
            output=f"{preview}{more}",
            findings=findings,
            error=(
                f"Found {len(findings)} dangling reference(s) across "
                f"{file_count} Markdown file(s)."
            ),
            fix_suggestion=(
                "Each link above points at a relative path that does not exist "
                "in the repo — fix the path or restore the moved/renamed file.\n"
                "Only literal relative links are checked (schemes, #anchors, "
                "site-absolute /paths, and templated links are ignored).\n"
                "To suppress a directory, add it to\n"
                "  overconfidence.gates.dangling-references.exclude_dirs in "
                ".sb_config.json"
            ),
        )


def _iter_markdown_files(root: Path, excluded: set[str]) -> List[Path]:
    """All .md/.markdown files under root, excluded and noise dirs pruned.

    Prunes excluded/noise directories top-down so we never descend into
    node_modules, .git, vendor, … — important since this gate applies to any
    repo with Markdown, where those trees can dwarf the source.
    """
    out: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        rel_dir = Path(dirpath).relative_to(root)
        dirnames[:] = [
            d
            for d in dirnames
            if not should_prune_dir(d)
            and not is_path_excluded(_rel_join(rel_dir, d), excluded)
        ]
        for name in filenames:
            if PurePosixPath(name).suffix.lower() not in _MARKDOWN_EXTS:
                continue
            out.append(Path(dirpath) / name)
    out.sort()
    return out


def _rel_join(rel_dir: Path, name: str) -> Path:
    """Join a child name onto a repo-relative dir, dropping the leading '.'."""
    return Path(name) if rel_dir == Path(".") else rel_dir / name


def _scan_markdown(md: Path, root: Path) -> List[Finding]:
    """Yield a finding for every relative link/image target that is not on disk."""
    try:
        text = md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rel_md = md.relative_to(root).as_posix()
    findings: List[Finding] = []
    prose = _blank_inline_code(_blank_fenced_blocks(text))
    for lineno, line in enumerate(prose.splitlines(), 1):
        for raw in _iter_targets(line):
            target = _checkable_path(raw)
            if target is None:
                continue
            if not _resolves(md.parent, root, target):
                findings.append(
                    Finding(
                        message=f"link target does not exist: {raw.strip()!r}",
                        level=FindingLevel.ERROR,
                        file=rel_md,
                        line=lineno,
                        rule_id="dangling-reference",
                    )
                )
    return findings


def _blank_fenced_blocks(text: str) -> str:
    """Return *text* with fenced code blocks blanked, line numbering intact.

    Code samples are not prose: ``handlers[key](arg)`` in a python block
    matches the inline-link pattern exactly, and reporting it as a broken
    link sends the reader chasing a target that was never a link. Lines are
    emptied rather than dropped so findings keep their real line numbers.
    """
    out: List[str] = []
    fence: Optional[Tuple[str, int]] = None
    for line in text.splitlines():
        marker = _FENCE_RE.match(line)
        if marker:
            char, width = marker.group(1)[0], len(marker.group(1))
            if fence is None:
                fence = (char, width)
            elif char == fence[0] and width >= fence[1] and not marker.group(2).strip():
                # A closing fence matches the opener's character, is at least
                # as long, and carries no info string.
                fence = None
            out.append("")
            continue
        out.append("" if fence is not None else line)
    return "\n".join(out)


def _blank_inline_code(text: str) -> str:
    """Replace inline code spans with spaces, preserving layout.

    Blanking rather than deleting keeps a real link's target intact when the
    link *text* is code, as in ``[`spec.md`](../spec.md)``. Newlines survive
    so a span that wraps lines does not renumber everything after it.
    """
    return _INLINE_CODE_RE.sub(
        lambda m: "".join("\n" if ch == "\n" else " " for ch in m.group(0)),
        text,
    )


def _iter_targets(line: str) -> List[str]:
    """Extract raw link/image/reference-definition targets from one line."""
    targets = [m.group(1) for m in _INLINE_RE.finditer(line)]
    ref = _REFDEF_RE.match(line)
    if ref:
        targets.append(ref.group(1))
    return targets


def _checkable_path(raw: str) -> Optional[str]:
    """Return the literal repo-relative path to check, or None to skip.

    Every skip is a literal string test — there is no inference about how a
    non-literal target *might* resolve; we simply decline to judge it.
    """
    target = raw.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if not target:
        return None
    if any(marker in target for marker in _TEMPLATE_MARKERS):
        return None  # templated / generated path
    if target.startswith("#"):
        return None  # pure fragment — anchor checking is out of scope
    if target.startswith("//") or _SCHEME_RE.match(target):
        return None  # external / protocol-relative
    # Strip fragment and query, then decode %20-style escapes.
    target = target.split("#", 1)[0].split("?", 1)[0]
    if not target or target.startswith("/"):
        return None  # empty or site-absolute (ambiguous root) — won't guess
    target = unquote(target)
    suffix = PurePosixPath(target.rstrip("/")).suffix.lower()
    if suffix and suffix not in _SOURCE_EXTS:
        return None  # could be a built/served artifact — skip, don't flag
    return target


def _resolves(md_dir: Path, root: Path, target: str) -> bool:
    """True if target resolves to an existing path inside the repo root."""
    try:
        resolved = (md_dir / target).resolve()
        root_resolved = root.resolve()
    except OSError:
        return True  # cannot resolve safely → do not flag
    if not resolved.is_relative_to(root_resolved):
        # climbs above the repo root — unresolvable in any published/CI context
        # (and we never stat outside the repo). Flag it as a broken reference.
        return False
    return resolved.exists()
