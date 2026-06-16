"""Tests for the myopia:conflicting-metadata gate."""

from slopmop.checks.base import GateCategory, GateLevel, ToolContext
from slopmop.checks.general.conflicting_metadata import ConflictingMetadataCheck
from slopmop.core.result import CheckStatus

CANONICAL = "https://example.com/about"


def _cm_check(config=None):
    return ConflictingMetadataCheck(config or {})


def _cm_run(tmp_path, config=None):
    return ConflictingMetadataCheck(config or {}).run(str(tmp_path))


def _page(canonical=None, og_url=None, robots=None, body="<p>Hello</p>"):
    head = ["<head>"]
    if canonical:
        head.append(f'<link rel="canonical" href="{canonical}">')
    if og_url:
        head.append(f'<meta property="og:url" content="{og_url}">')
    if robots:
        head.append(f'<meta name="robots" content="{robots}">')
    head.append("</head>")
    return f"<!doctype html><html lang='en'>{''.join(head)}<body>{body}</body></html>"


def _sitemap(*locs):
    entries = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{entries}</urlset>"
    )


# ---------------------------------------------------------------------------
# Identity / metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_name(self):
        assert _cm_check().name == "conflicting-metadata"

    def test_full_name(self):
        assert _cm_check().full_name == "myopia:conflicting-metadata"

    def test_category(self):
        assert _cm_check().category == GateCategory.MYOPIA

    def test_gate_level(self):
        assert ConflictingMetadataCheck.level == GateLevel.SWAB

    def test_tool_context(self):
        assert ConflictingMetadataCheck.tool_context == ToolContext.PURE


# ---------------------------------------------------------------------------
# Applicability
# ---------------------------------------------------------------------------


class TestApplicability:
    def test_applicable_with_html(self, tmp_path):
        (tmp_path / "index.html").write_text(_page(canonical=CANONICAL))
        assert _cm_check().is_applicable(str(tmp_path)) is True

    def test_not_applicable_without_html(self, tmp_path):
        (tmp_path / "app.py").write_text("print('hi')\n")
        assert _cm_check().is_applicable(str(tmp_path)) is False


# ---------------------------------------------------------------------------
# Pass cases
# ---------------------------------------------------------------------------


class TestPasses:
    def test_consistent_canonical_and_og(self, tmp_path):
        (tmp_path / "about.html").write_text(
            _page(canonical=CANONICAL, og_url=CANONICAL)
        )
        assert _cm_run(tmp_path).status == CheckStatus.PASSED

    def test_canonical_matches_sitemap(self, tmp_path):
        (tmp_path / "about.html").write_text(_page(canonical=CANONICAL))
        (tmp_path / "sitemap.xml").write_text(_sitemap(CANONICAL))
        assert _cm_run(tmp_path).status == CheckStatus.PASSED

    def test_trailing_slash_only_difference_is_normalized_away(self, tmp_path):
        # canonical and og:url differ ONLY by trailing slash -> still consistent
        (tmp_path / "about.html").write_text(
            _page(canonical=CANONICAL, og_url=CANONICAL + "/")
        )
        # but the sitemap also uses the same trailing-slash style as canonical,
        # so there is no cross-file spelling conflict here
        assert _cm_run(tmp_path).status == CheckStatus.PASSED


# ---------------------------------------------------------------------------
# Fail cases
# ---------------------------------------------------------------------------


class TestFailures:
    def test_canonical_vs_og_url_mismatch(self, tmp_path):
        (tmp_path / "about.html").write_text(
            _page(canonical=CANONICAL, og_url="https://example.com/team")
        )
        result = _cm_run(tmp_path)
        assert result.status == CheckStatus.FAILED
        assert any(f.rule_id == "canonical-vs-og-url" for f in result.findings)

    def test_canonical_vs_sitemap_trailing_slash(self, tmp_path):
        # the real bug: sitemap has trailing slash, canonical does not
        (tmp_path / "about.html").write_text(_page(canonical=CANONICAL))
        (tmp_path / "sitemap.xml").write_text(_sitemap(CANONICAL + "/"))
        result = _cm_run(tmp_path)
        assert result.status == CheckStatus.FAILED
        assert any(f.rule_id == "inconsistent-url-spelling" for f in result.findings)

    def test_noindex_page_in_sitemap(self, tmp_path):
        (tmp_path / "secret.html").write_text(
            _page(canonical=CANONICAL, robots="noindex, follow")
        )
        (tmp_path / "sitemap.xml").write_text(_sitemap(CANONICAL))
        result = _cm_run(tmp_path)
        assert result.status == CheckStatus.FAILED
        assert any(f.rule_id == "noindex-in-sitemap" for f in result.findings)

    def test_exclude_dirs_suppresses(self, tmp_path):
        vendored = tmp_path / "thirdparty"
        vendored.mkdir()
        (vendored / "about.html").write_text(
            _page(canonical=CANONICAL, og_url="https://example.com/team")
        )
        result = _cm_run(tmp_path, {"exclude_dirs": ["thirdparty"]})
        # no applicable pages remain after exclusion -> nothing to flag
        assert result.status == CheckStatus.PASSED
