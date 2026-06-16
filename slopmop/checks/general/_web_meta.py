"""Shared, dependency-free parsing for the web-metadata gates.

Both ``myopia:conflicting-metadata`` and ``deceptiveness:unfounded-metadata``
read the same things out of an HTML page — its canonical/og URLs, robots
directive, JSON-LD blocks, and visible text — plus the sitemap. This module
holds that parsing using only the standard library (``html.parser``, ``json``,
``xml.etree``), so the gates stay ``ToolContext.PURE`` with no extra deps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast
from xml.etree import ElementTree

# html.parser hands attributes back as (name, value) pairs; value is None for
# valueless attributes (e.g. ``<script defer>``).
_Attrs = List[Tuple[str, Optional[str]]]

# Tags whose text content is not visible page copy.
_NON_VISIBLE = {"script", "style", "template", "noscript", "head"}


def _no_strs() -> List[str]:
    """Typed default-factory: bare ``list`` infers ``list[Unknown]`` under
    strict pyright; a named factory with a return annotation satisfies it."""
    return []


@dataclass
class HtmlMeta:
    """Metadata extracted from a single HTML document."""

    path: Path
    lang: Optional[str] = None
    title: Optional[str] = None
    canonical: Optional[str] = None
    og_url: Optional[str] = None
    og_title: Optional[str] = None
    og_description: Optional[str] = None
    meta_description: Optional[str] = None
    robots: Optional[str] = None
    jsonld_blocks: List[str] = field(default_factory=_no_strs)
    visible_text: str = ""

    @property
    def is_noindex(self) -> bool:
        return bool(self.robots) and "noindex" in (self.robots or "").lower()


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta = HtmlMeta(path=Path())
        self._depth_non_visible = 0
        self._in_title = False
        self._in_jsonld = False
        self._jsonld_buf: List[str] = []
        self._text_buf: List[str] = []

    @staticmethod
    def _attr(attrs: _Attrs, name: str) -> Optional[str]:
        for k, v in attrs:
            if k == name:
                return v
        return None

    def handle_starttag(self, tag: str, attrs: _Attrs) -> None:
        tag = tag.lower()
        if tag == "html":
            self.meta.lang = self._attr(attrs, "lang") or self.meta.lang
        elif tag == "title":
            self._in_title = True
        elif tag == "link":
            if (self._attr(attrs, "rel") or "").lower() == "canonical":
                self.meta.canonical = self._attr(attrs, "href")
        elif tag == "meta":
            prop = (self._attr(attrs, "property") or "").lower()
            name = (self._attr(attrs, "name") or "").lower()
            content = self._attr(attrs, "content")
            if prop == "og:url":
                self.meta.og_url = content
            elif prop == "og:title":
                self.meta.og_title = content
            elif prop == "og:description":
                self.meta.og_description = content
            elif name == "description":
                self.meta.meta_description = content
            elif name == "robots":
                self.meta.robots = content
        elif tag == "script":
            if (self._attr(attrs, "type") or "").lower() == "application/ld+json":
                self._in_jsonld = True
                self._jsonld_buf = []
        if tag in _NON_VISIBLE:
            self._depth_non_visible += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._in_jsonld:
            self.meta.jsonld_blocks.append("".join(self._jsonld_buf).strip())
            self._in_jsonld = False
        if tag in _NON_VISIBLE and self._depth_non_visible > 0:
            self._depth_non_visible -= 1

    def handle_data(self, data: str) -> None:
        if self._in_jsonld:
            self._jsonld_buf.append(data)
            return
        if self._in_title:
            self.meta.title = (self.meta.title or "") + data
        if self._depth_non_visible == 0:
            self._text_buf.append(data)

    def finalize(self, path: Path) -> HtmlMeta:
        self.meta.path = path
        if self.meta.title:
            self.meta.title = self.meta.title.strip()
        self.meta.visible_text = _collapse_ws(" ".join(self._text_buf))
        return self.meta


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


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
    host = re.sub(r":(80|443)$", "", host)
    path = m.group(3) or "/"
    if path != "/":
        path = path.rstrip("/")
    return f"{scheme}://{host}{path}"


def load_sitemap_locs(sitemap_path: Path) -> List[str]:
    """Return the raw ``<loc>`` URLs from a sitemap.xml (namespace-agnostic)."""
    try:
        tree = ElementTree.parse(sitemap_path)
    except (OSError, ElementTree.ParseError):
        return []
    locs: List[str] = []
    for el in tree.iter():
        tag = el.tag.rsplit("}", 1)[-1]  # strip namespace
        if tag == "loc" and el.text:
            locs.append(el.text.strip())
    return locs


def iter_html_files(root: Path, excluded: set[str]) -> List[Path]:
    """All .html/.htm files under root, excluded dirs pruned."""
    out: List[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".html", ".htm"):
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if set(rel.parts[:-1]) & excluded:
            continue
        out.append(path)
    return out


def parse_all_html(root: Path, excluded: set[str]) -> Dict[Path, HtmlMeta]:
    return {p: parse_html(p) for p in iter_html_files(root, excluded)}


def flatten_text(text: str) -> str:
    """Normalize text for cross-source comparison: strip HTML tags, fold smart
    quotes to ASCII, collapse whitespace, lowercase. JSON-LD answer text and
    visible page text are then comparable even when one carries inline markup."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("–", "-")
        .replace("—", "-")
        .replace(" ", " ")
    )
    return re.sub(r"\s+", " ", text).strip().lower()


def _type_set(node: Dict[str, Any]) -> set[str]:
    raw: Any = node.get("@type")
    if isinstance(raw, list):
        return {str(t) for t in cast(List[Any], raw)}
    return {str(raw)} if raw else set()


def extract_faq_pairs(data: Any) -> List[Tuple[str, str]]:
    """Walk parsed JSON-LD and return (question, answer) text pairs.

    Namespace-tolerant: handles a top-level object, a list, or an ``@graph``
    wrapper, and finds any ``Question`` node carrying ``name`` plus an
    ``acceptedAnswer`` (object or list) with ``text``.
    """
    pairs: List[Tuple[str, str]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in cast(List[Any], node):
                walk(item)
            return
        if not isinstance(node, dict):
            return
        d = cast(Dict[str, Any], node)
        if "Question" in _type_set(d) and d.get("name"):
            answers: Any = d.get("acceptedAnswer") or d.get("suggestedAnswer")
            answer_list: List[Any] = (
                cast(List[Any], answers) if isinstance(answers, list) else [answers]
            )
            for ans in answer_list:
                if isinstance(ans, dict):
                    ans_d = cast(Dict[str, Any], ans)
                    if ans_d.get("text"):
                        pairs.append((str(d["name"]), str(ans_d["text"])))
        for value in d.values():
            if isinstance(value, (list, dict)):
                walk(value)

    walk(data)
    return pairs
