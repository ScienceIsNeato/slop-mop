"""Detect metadata that disagrees with itself across a site.

Myopia: an agent edits one place a page describes itself — the canonical
link — and never looks at the others. The page now ships three different
answers to "what URL am I?" and a crawler has to guess. Each signal looked
right in the file the agent was staring at; the slop is only visible when
you hold them side by side.

Conflicts this gate catches (all PURE, stdlib parsing — no network):

  canonical vs og:url
      ``<link rel="canonical">`` and ``<meta property="og:url">`` on the
      same page point at different URLs. Search and social then index the
      page under two identities. Fix: make them identical.

  canonical vs sitemap
      A page's canonical URL and its ``<loc>`` in sitemap.xml are the same
      address written two ways (one has a trailing slash, the other does
      not; one is http, the other https). Crawlers treat those as distinct
      URLs and split the page's ranking. Fix: pick one spelling everywhere.

  noindex page in sitemap
      A page asks robots not to index it (``<meta name="robots"
      content="noindex">``) yet still advertises itself in the sitemap.
      The two directives contradict; the sitemap entry is a lie. Fix: drop
      the page from the sitemap or remove the noindex.
"""

from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path
from typing import ClassVar, Dict, List, Tuple

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
)
from slopmop.checks.general._web_meta import (
    HtmlMeta,
    is_sitemap_index,
    iter_html_files,
    load_sitemap_locs,
    loose_key,
    normalize_url,
    parse_html,
    resolve_local_path,
)
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel

_EXCLUDED = SCOPE_EXCLUDED_DIRS | {"node_modules", "vendor", "dist", "build"}
_SITEMAP_NAMES = ("sitemap.xml", "sitemap_index.xml")


class ConflictingMetadataCheck(BaseCheck):
    """Flag self-contradicting page metadata (canonical / og:url / sitemap).

    A PURE cross-file scan: parse every HTML page plus sitemap.xml and
    confirm the page's identity signals agree.

      canonical vs og:url     — same page, two different self-URLs.
      canonical vs sitemap    — same URL spelled two ways (trailing slash,
                                scheme) across the page and the sitemap.
      noindex in sitemap      — a noindex page still listed in the sitemap.

    PURE check — stdlib HTML/XML parsing, no external tools or network.

    Level: swab (cheap, deterministic — safe on every commit).

    Configuration:
      exclude_dirs: [] — additional directories to skip.

    Re-check:
      sm swab -g myopia:conflicting-metadata --verbose
    """

    tool_context: ClassVar[ToolContext] = ToolContext.PURE
    role = CheckRole.DIAGNOSTIC
    level = GateLevel.SWAB
    remediation_churn = RemediationChurn.DOWNSTREAM_CHANGES_VERY_UNLIKELY

    @property
    def name(self) -> str:
        return "conflicting-metadata"

    @property
    def display_name(self) -> str:
        return "🧭 Conflicting Metadata (canonical/og/sitemap)"

    @property
    def gate_description(self) -> str:
        return (
            "🧭 Catches pages that disagree with themselves: canonical vs "
            "og:url, canonical vs sitemap, noindex pages in the sitemap"
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
                description=EXCLUDE_DIRS_DESCRIPTION,
                permissiveness="more_is_stricter",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        excluded = self._excluded()
        return bool(iter_html_files(Path(project_root), excluded))

    def skip_reason(self, project_root: str) -> str:
        return "No HTML pages found"

    def _excluded(self) -> set[str]:
        return _EXCLUDED | set(self.config.get("exclude_dirs") or [])

    def run(self, project_root: str) -> CheckResult:
        start = time.perf_counter()
        root = Path(project_root)
        pages = iter_html_files(root, self._excluded())
        metas = [(p.relative_to(root).as_posix(), parse_html(p)) for p in pages]

        # raw spelling -> source label, keyed by a SCHEME-INSENSITIVE URL key,
        # so the same address written two ways across page + sitemap — including
        # http vs https — collapses into one group worth flagging.
        spellings: Dict[str, Dict[str, str]] = defaultdict(dict)
        canonical_norms: Dict[str, str] = {}  # loose key -> rel path

        findings = self._scan_pages(metas, spellings, canonical_norms)
        sitemap_norms = self._collect_sitemap(root, spellings)
        findings += self._scan_noindex(metas, sitemap_norms)
        findings += self._scan_spellings(spellings, canonical_norms, sitemap_norms)

        return self._result(findings, len(pages), time.perf_counter() - start)

    @staticmethod
    def _scan_pages(
        metas: List[Tuple[str, HtmlMeta]],
        spellings: Dict[str, Dict[str, str]],
        canonical_norms: Dict[str, str],
    ) -> List[Finding]:
        """Record each page's canonical spelling and flag canonical/og:url splits."""
        findings: List[Finding] = []
        for rel, meta in metas:
            if meta.canonical:
                key = loose_key(meta.canonical)
                spellings[key][meta.canonical.strip()] = f"{rel} canonical"
                canonical_norms[key] = rel
            # Same-page equality keeps the scheme: a canonical/og:url that
            # differ only by http vs https IS the conflict to report here.
            if (
                meta.canonical
                and meta.og_url
                and normalize_url(meta.canonical) != normalize_url(meta.og_url)
            ):
                findings.append(
                    Finding(
                        message=(
                            f"canonical and og:url disagree on the same page: "
                            f"canonical={meta.canonical.strip()!r} "
                            f"og:url={meta.og_url.strip()!r}"
                        ),
                        level=FindingLevel.ERROR,
                        file=rel,
                        rule_id="canonical-vs-og-url",
                    )
                )
        return findings

    @classmethod
    def _collect_sitemap(
        cls, root: Path, spellings: Dict[str, Dict[str, str]]
    ) -> Dict[str, str]:
        """Index page <loc> URLs (normalized -> sitemap path) and their spellings."""
        sitemap_norms: Dict[str, str] = {}
        for name in _SITEMAP_NAMES:
            sm = root / name
            if sm.is_file():
                cls._ingest_sitemap(sm, root, sitemap_norms, spellings, depth=0)
        return sitemap_norms

    @classmethod
    def _ingest_sitemap(
        cls,
        sm: Path,
        root: Path,
        sitemap_norms: Dict[str, str],
        spellings: Dict[str, Dict[str, str]],
        depth: int,
    ) -> None:
        """Record a sitemap's page <loc>s; for a <sitemapindex>, follow its
        children to local files instead of treating them as pages."""
        if is_sitemap_index(sm):
            if depth >= 3:  # guard against cyclic / pathological index nesting
                return
            for child in load_sitemap_locs(sm):
                child_path = resolve_local_path(root, child)
                if child_path is not None:
                    cls._ingest_sitemap(
                        child_path, root, sitemap_norms, spellings, depth + 1
                    )
            return
        sm_rel = sm.relative_to(root).as_posix()
        for loc in load_sitemap_locs(sm):
            key = loose_key(loc)
            sitemap_norms[key] = sm_rel
            spellings[key][loc.strip()] = f"{sm_rel} <loc>"

    @staticmethod
    def _scan_noindex(
        metas: List[Tuple[str, HtmlMeta]], sitemap_norms: Dict[str, str]
    ) -> List[Finding]:
        """Flag noindex pages still advertised in the sitemap."""
        findings: List[Finding] = []
        for rel, meta in metas:
            if not (meta.is_noindex and meta.canonical):
                continue
            key = loose_key(meta.canonical)
            if key in sitemap_norms:
                findings.append(
                    Finding(
                        message=(
                            f"page is noindex but its URL is listed in "
                            f"{sitemap_norms[key]}: {meta.canonical.strip()}"
                        ),
                        level=FindingLevel.ERROR,
                        file=rel,
                        rule_id="noindex-in-sitemap",
                    )
                )
        return findings

    @staticmethod
    def _scan_spellings(
        spellings: Dict[str, Dict[str, str]],
        canonical_norms: Dict[str, str],
        sitemap_norms: Dict[str, str],
    ) -> List[Finding]:
        """Flag one logical URL spelled inconsistently across canonical + sitemap."""
        findings: List[Finding] = []
        for norm, raws in spellings.items():
            if len(raws) <= 1:
                continue
            where = "; ".join(f"{raw!r} ({src})" for raw, src in sorted(raws.items()))
            findings.append(
                Finding(
                    message=(
                        f"one URL written {len(raws)} ways — crawlers treat "
                        f"these as different pages: {where}"
                    ),
                    level=FindingLevel.ERROR,
                    file=canonical_norms.get(norm) or sitemap_norms.get(norm),
                    rule_id="inconsistent-url-spelling",
                )
            )
        return findings

    def _result(
        self, findings: List[Finding], page_count: int, elapsed: float
    ) -> CheckResult:
        if not findings:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=elapsed,
                output=f"Metadata is self-consistent ({page_count} page(s) checked)",
            )
        preview = "\n".join(f"  {f.file}: {f.message}" for f in findings[:20])
        more = f"\n  … and {len(findings) - 20} more" if len(findings) > 20 else ""
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=elapsed,
            output=f"{preview}{more}",
            findings=findings,
            error=(
                f"Found {len(findings)} metadata conflict(s) across "
                f"{page_count} page(s)."
            ),
            fix_suggestion=(
                "Make every page agree with itself about its own URL:\n"
                "  - canonical and og:url must be identical\n"
                "  - a page's canonical and its sitemap <loc> must match exactly\n"
                "    (same scheme, same trailing-slash style)\n"
                "  - drop noindex pages from the sitemap (or remove the noindex)\n"
                "To suppress a directory, add it to\n"
                "  myopia.gates.conflicting-metadata.exclude_dirs in .sb_config.json"
            ),
        )
