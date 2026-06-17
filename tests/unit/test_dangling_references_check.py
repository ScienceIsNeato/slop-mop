"""Tests for the overconfidence:dangling-references gate."""

from slopmop.checks.base import GateCategory, GateLevel, ToolContext
from slopmop.checks.general.dangling_references import DanglingReferencesCheck
from slopmop.core.result import CheckStatus


def _dr_check(config=None):
    return DanglingReferencesCheck(config or {})


def _dr_run(tmp_path, config=None):
    return DanglingReferencesCheck(config or {}).run(str(tmp_path))


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_full_name(self):
        assert _dr_check().full_name == "overconfidence:dangling-references"

    def test_category(self):
        assert _dr_check().category == GateCategory.OVERCONFIDENCE

    def test_level_is_scour(self):
        assert DanglingReferencesCheck.level == GateLevel.SCOUR

    def test_tool_context_pure(self):
        assert DanglingReferencesCheck.tool_context == ToolContext.PURE


# ---------------------------------------------------------------------------
# Applicability
# ---------------------------------------------------------------------------


class TestApplicability:
    def test_applicable_with_markdown(self, tmp_path):
        (tmp_path / "README.md").write_text("# hi\n")
        assert _dr_check().is_applicable(str(tmp_path)) is True

    def test_not_applicable_without_markdown(self, tmp_path):
        (tmp_path / "app.py").write_text("print('hi')\n")
        assert _dr_check().is_applicable(str(tmp_path)) is False


# ---------------------------------------------------------------------------
# Fail cases — genuinely broken relative references
# ---------------------------------------------------------------------------


class TestFailures:
    def test_broken_relative_link(self, tmp_path):
        (tmp_path / "README.md").write_text("See [the guide](./docs/guide.md).\n")
        result = _dr_run(tmp_path)
        assert result.status == CheckStatus.FAILED
        assert any(f.rule_id == "dangling-reference" for f in result.findings)

    def test_broken_image(self, tmp_path):
        (tmp_path / "README.md").write_text("![logo](./img/logo.png)\n")
        assert _dr_run(tmp_path).status == CheckStatus.FAILED

    def test_broken_reference_definition(self, tmp_path):
        (tmp_path / "README.md").write_text("[g]: ./missing.md\nSee [g].\n")
        assert _dr_run(tmp_path).status == CheckStatus.FAILED

    def test_broken_link_in_subdir_resolves_relative_to_file(self, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        # ../README.md does not exist (only docs/x.md), so this is broken
        (docs / "x.md").write_text("[home](../README.md)\n")
        assert _dr_run(tmp_path).status == CheckStatus.FAILED

    def test_fragment_stripped_before_file_check(self, tmp_path):
        (tmp_path / "README.md").write_text("[s](./guide.md#install)\n")
        # guide.md is absent → broken regardless of the anchor
        assert _dr_run(tmp_path).status == CheckStatus.FAILED


# ---------------------------------------------------------------------------
# Pass cases — references that DO resolve
# ---------------------------------------------------------------------------


class TestResolves:
    def test_existing_relative_link(self, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "guide.md").write_text("# Guide\n")
        (tmp_path / "README.md").write_text("See [the guide](./docs/guide.md).\n")
        assert _dr_run(tmp_path).status == CheckStatus.PASSED

    def test_link_to_directory(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "README.md").write_text("See [docs](./docs/).\n")
        assert _dr_run(tmp_path).status == CheckStatus.PASSED

    def test_percent_encoded_space(self, tmp_path):
        (tmp_path / "my file.md").write_text("x\n")
        (tmp_path / "README.md").write_text("[f](./my%20file.md)\n")
        assert _dr_run(tmp_path).status == CheckStatus.PASSED


# ---------------------------------------------------------------------------
# False-positive-free by construction — each of these must NOT flag
# ---------------------------------------------------------------------------


class TestNoFalsePositives:
    def test_external_url_skipped(self, tmp_path):
        (tmp_path / "README.md").write_text("[site](https://example.com/x)\n")
        assert _dr_run(tmp_path).status == CheckStatus.PASSED

    def test_mailto_skipped(self, tmp_path):
        (tmp_path / "README.md").write_text("[mail](mailto:a@b.com)\n")
        assert _dr_run(tmp_path).status == CheckStatus.PASSED

    def test_pure_fragment_skipped(self, tmp_path):
        (tmp_path / "README.md").write_text("[top](#installation)\n")
        assert _dr_run(tmp_path).status == CheckStatus.PASSED

    def test_site_absolute_path_skipped(self, tmp_path):
        # ambiguous repo-root vs site-root — we never guess
        (tmp_path / "README.md").write_text("[about](/about)\n")
        assert _dr_run(tmp_path).status == CheckStatus.PASSED

    def test_templated_path_skipped(self, tmp_path):
        (tmp_path / "README.md").write_text("[x]({{ site.baseurl }}/guide.md)\n")
        assert _dr_run(tmp_path).status == CheckStatus.PASSED

    def test_non_source_extension_skipped(self, tmp_path):
        # .html could be a built artifact from a .md source — never flag it
        (tmp_path / "README.md").write_text("[built](./guide.html)\n")
        assert _dr_run(tmp_path).status == CheckStatus.PASSED

    def test_protocol_relative_skipped(self, tmp_path):
        (tmp_path / "README.md").write_text("[cdn](//cdn.example.com/x.png)\n")
        assert _dr_run(tmp_path).status == CheckStatus.PASSED

    def test_parent_escape_not_flagged(self, tmp_path):
        # a target that climbs out of the repo is out of scope, never flagged
        root = tmp_path / "repo"
        root.mkdir()
        (root / "README.md").write_text("[x](../../etc/passwd)\n")
        assert DanglingReferencesCheck({}).run(str(root)).status == CheckStatus.PASSED
