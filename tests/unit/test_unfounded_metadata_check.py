"""Tests for the deceptiveness:unfounded-metadata gate."""

from slopmop.checks.base import GateCategory, GateLevel, ToolContext
from slopmop.checks.general.unfounded_metadata import UnfoundedMetadataCheck
from slopmop.core.result import CheckStatus


def _um_check(config=None):
    return UnfoundedMetadataCheck(config or {})


def _um_run(tmp_path, config=None):
    return UnfoundedMetadataCheck(config or {}).run(str(tmp_path))


def _um_faq_jsonld(question, answer):
    return (
        '{"@context":"https://schema.org","@type":"FAQPage","mainEntity":'
        '[{"@type":"Question","name":"' + question + '",'
        '"acceptedAnswer":{"@type":"Answer","text":"' + answer + '"}}]}'
    )


def _um_page(jsonld="", body="<p>Hello world</p>"):
    script = f'<script type="application/ld+json">{jsonld}</script>' if jsonld else ""
    return f"<!doctype html><html><head>{script}</head><body>{body}</body></html>"


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_full_name(self):
        assert _um_check().full_name == "deceptiveness:unfounded-metadata"

    def test_category(self):
        assert _um_check().category == GateCategory.DECEPTIVENESS

    def test_gate_level(self):
        assert UnfoundedMetadataCheck.level == GateLevel.SWAB

    def test_tool_context(self):
        assert UnfoundedMetadataCheck.tool_context == ToolContext.PURE


# ---------------------------------------------------------------------------
# Applicability
# ---------------------------------------------------------------------------


class TestApplicability:
    def test_applicable_with_html(self, tmp_path):
        (tmp_path / "index.html").write_text(_um_page())
        assert _um_check().is_applicable(str(tmp_path)) is True

    def test_not_applicable_without_html(self, tmp_path):
        (tmp_path / "app.py").write_text("print('hi')\n")
        assert _um_check().is_applicable(str(tmp_path)) is False


# ---------------------------------------------------------------------------
# Pass cases
# ---------------------------------------------------------------------------


class TestPasses:
    def test_no_jsonld(self, tmp_path):
        (tmp_path / "index.html").write_text(_um_page())
        assert _um_run(tmp_path).status == CheckStatus.PASSED

    def test_faq_text_present_on_page(self, tmp_path):
        q, a = "What is slop-mop?", "A quality tool for agents."
        body = f"<h2>{q}</h2><p>{a}</p>"
        (tmp_path / "faq.html").write_text(_um_page(_um_faq_jsonld(q, a), body))
        assert _um_run(tmp_path).status == CheckStatus.PASSED

    def test_faq_present_despite_markup_and_smart_quotes(self, tmp_path):
        # JSON-LD answer is plain; visible copy wraps it in markup + smart quote
        q, a = "Does it work", "It is the agents best friend"
        body = f"<h2>{q}</h2><p>It is the agents <b>best</b> friend</p>"
        (tmp_path / "faq.html").write_text(_um_page(_um_faq_jsonld(q, a), body))
        assert _um_run(tmp_path).status == CheckStatus.PASSED


# ---------------------------------------------------------------------------
# Fail cases
# ---------------------------------------------------------------------------


class TestFailures:
    def test_malformed_jsonld(self, tmp_path):
        (tmp_path / "index.html").write_text(_um_page('{"@type": "FAQPage", invalid}'))
        result = _um_run(tmp_path)
        assert result.status == CheckStatus.FAILED
        assert any(f.rule_id == "malformed-jsonld" for f in result.findings)

    def test_faq_answer_not_on_page(self, tmp_path):
        q, a = "What is slop-mop?", "A totally invisible promise nowhere in copy."
        body = f"<h2>{q}</h2><p>Some unrelated paragraph.</p>"
        (tmp_path / "faq.html").write_text(_um_page(_um_faq_jsonld(q, a), body))
        result = _um_run(tmp_path)
        assert result.status == CheckStatus.FAILED
        assert any(f.rule_id == "faq-answer-not-on-page" for f in result.findings)

    def test_faq_question_not_on_page(self, tmp_path):
        q, a = "A question never shown to the reader", "Visible answer text here."
        body = "<p>Visible answer text here.</p>"
        (tmp_path / "faq.html").write_text(_um_page(_um_faq_jsonld(q, a), body))
        result = _um_run(tmp_path)
        assert result.status == CheckStatus.FAILED
        assert any(f.rule_id == "faq-question-not-on-page" for f in result.findings)

    def test_exclude_dirs_suppresses(self, tmp_path):
        vendored = tmp_path / "thirdparty"
        vendored.mkdir()
        (vendored / "f.html").write_text(_um_page('{"bad": invalid}'))
        result = _um_run(tmp_path, {"exclude_dirs": ["thirdparty"]})
        assert result.status == CheckStatus.PASSED
