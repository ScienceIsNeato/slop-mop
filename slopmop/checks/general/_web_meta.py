"""Shared, dependency-free parsing for the web-metadata gate(s).

``myopia:conflicting-metadata`` reads a page's canonical link, og:url, and
robots directive, plus the sitemap, to confirm a page agrees with itself about
its own URL. This module holds that parsing using only the standard library
(``html.parser`` plus a flat regex for the sitemap), so the gate stays
``ToolContext.PURE`` with no extra deps and no XML-parser attack surface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional, Tuple

from slopmop.checks.base import should_prune_dir
from slopmop.utils import is_path_excluded

# html.parser hands attributes back as (name, value) pairs; value is None for
# valueless attributes (e.g. ``<script defer>``).
_Attrs = List[Tuple[str, Optional[str]]]


@dataclass
class HtmlMeta:
    """The self-identity signals one HTML document declares about itself."""

    path: Path
    canonical: Optional[str] = None
    og_url: Optional[str] = None
    robots: Optional[str] = None

    @property
    def is_noindex(self) -> bool:
        # robots is a comma/space-separated token list — match the exact
        # "noindex" directive, not substrings like "noindexable".
        tokens = re.split(r"[,\s]+", (self.robots or "").lower())
        return "noindex" in tokens


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta = HtmlMeta(path=Path())

    @staticmethod
    def _attr(attrs: _Attrs, name: str) -> Optional[str]:
        for k, v in attrs:
            if k == name:
                return v
        return None

    def handle_starttag(self, tag: str, attrs: _Attrs) -> None:
        tag = tag.lower()
        if tag == "link":
            # rel is a space-separated token list (e.g. "alternate canonical")
            if "canonical" in (self._attr(attrs, "rel") or "").lower().split():
                self.meta.canonical = self._attr(attrs, "href")
        elif tag == "meta":
            prop = (self._attr(attrs, "property") or "").lower()
            name = (self._attr(attrs, "name") or "").lower()
            content = self._attr(attrs, "content")
            if prop == "og:url":
                self.meta.og_url = content
            elif name == "robots":
                self.meta.robots = content

    def finalize(self, path: Path) -> HtmlMeta:
        self.meta.path = path
        return self.meta


def parse_html(path: Path) -> HtmlMeta:
    """Parse one HTML file into an :class:`HtmlMeta` (best-effort, never raises)."""
    parser = _MetaParser()
    try:
        parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return HtmlMeta(path=path)
    return parser.finalize(path)


def normalize_url(url: str) -> str:
    """Canonical comparison form: lowercase scheme+host, no default port, no
    trailing slash (except root), no fragment. Path case is preserved."""
    u = url.strip()
    u = u.split("#", 1)[0]
    m = re.match(r"^(https?)://([^/]+)(/.*)?$", u, re.IGNORECASE)
    if not m:
        return u.rstrip("/") or u
    scheme = m.group(1).lower()
    host = m.group(2).lower()
    # Strip only the default port FOR THE SCHEME — http://h:443 and
    # http://h are genuinely different hosts and must not be conflated.
    if scheme == "http":
        host = re.sub(r":80$", "", host)
    elif scheme == "https":
        host = re.sub(r":443$", "", host)
    path = m.group(3) or "/"
    if path != "/":
        path = path.rstrip("/")
    return f"{scheme}://{host}{path}"


def loose_key(url: str) -> str:
    """Scheme-insensitive grouping key: the same host+path regardless of
    http vs https. Used to detect one logical resource spelled differently —
    including http/https drift between a canonical and a sitemap entry.
    ``normalize_url`` keeps the scheme for same-page equality checks, where a
    canonical/og:url scheme mismatch is itself the conflict to report."""
    return re.sub(r"^https?://", "", normalize_url(url), flags=re.IGNORECASE)


_LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE | re.DOTALL)


def load_sitemap_locs(sitemap_path: Path) -> List[str]:
    """Return the raw ``<loc>`` URLs from a sitemap (namespace-agnostic).

    Uses a flat ``<loc>`` regex rather than an XML parser: we need one field,
    and regex extraction sidesteps the XXE / billion-laughs attack surface of
    ``xml.etree`` with no extra dependency.
    """
    try:
        text = sitemap_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [m.strip() for m in _LOC_RE.findall(text) if m.strip()]


def is_sitemap_index(sitemap_path: Path) -> bool:
    """True when the file is a ``<sitemapindex>`` (its <loc>s point at child
    sitemaps, not pages)."""
    try:
        return (
            "<sitemapindex"
            in sitemap_path.read_text(encoding="utf-8", errors="replace").lower()
        )
    except OSError:
        return False


def resolve_local_path(root: Path, url: str) -> Optional[Path]:
    """Map a sitemap URL to the local file at its exact path under ``root``.

    A child-sitemap ``<loc>`` like ``https://site/sitemaps/pages.xml`` resolves
    to ``root/sitemaps/pages.xml``. We deliberately do NOT fall back to a
    basename match: an unrelated committed file sharing the basename would be
    ingested as the wrong sitemap. Any candidate that escapes the project root
    (``..`` in a hostile ``<loc>``) is rejected. Returns ``None`` when no file
    sits at that exact path.
    """
    m = re.match(r"^https?://[^/]+(/.*)?$", url.strip(), re.IGNORECASE)
    path_part = m.group(1) if m and m.group(1) else url.strip()
    rel = path_part.split("?", 1)[0].split("#", 1)[0].lstrip("/")
    if not rel:
        return None
    try:
        root_resolved = root.resolve()
        resolved = (root / rel).resolve()
    except OSError:
        return None
    if resolved.is_file() and resolved.is_relative_to(root_resolved):
        return resolved
    return None


def iter_html_files(root: Path, excluded: set[str]) -> List[Path]:
    """All .html/.htm files under root, excluded and noise dirs pruned."""
    out: List[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".html", ".htm"):
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        # is_path_excluded handles nested ("vendor/generated") and glob
        # filters, not just single segments; should_prune_dir drops the
        # standard noise/dot-dirs (.git, .venv, node_modules, …).
        if is_path_excluded(rel, excluded) or any(
            should_prune_dir(p) for p in rel.parts[:-1]
        ):
            continue
        out.append(path)
    return out
