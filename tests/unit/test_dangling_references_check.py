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

    def test_noise_and_excluded_dirs_are_pruned(self, tmp_path):
        # markdown inside node_modules / .git / a configured exclude must not
        # be scanned (and must not make the gate applicable on its own)
        for d in ("node_modules", ".git", "thirdparty"):
            sub = tmp_path / d
            sub.mkdir()
            (sub / "BROKEN.md").write_text("[x](./does-not-exist.md)\n")
        check = _dr_check({"exclude_dirs": ["thirdparty"]})
        assert check.is_applicable(str(tmp_path)) is False
        assert check.run(str(tmp_path)).status == CheckStatus.PASSED


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

    def test_repo_escaping_target_is_flagged(self, tmp_path):
        # a relative link climbing above the repo root can never resolve in a
        # published/CI context (the issue's "outside the published tree" goal)
        root = tmp_path / "repo"
        root.mkdir()
        (root / "README.md").write_text("[x](../../secrets.md)\n")
        result = DanglingReferencesCheck({}).run(str(root))
        assert result.status == CheckStatus.FAILED
        assert any(f.rule_id == "dangling-reference" for f in result.findings)


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

    def test_existing_link_with_parentheses_in_path(self, tmp_path):
        # parentheses are legal in Markdown destinations when balanced — the
        # path must be captured whole, not truncated at the first ")"
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "api(v2).md").write_text("# API\n")
        (tmp_path / "README.md").write_text("[api](./docs/api(v2).md)\n")
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

    def test_repo_internal_parent_link_resolves(self, tmp_path):
        # ../ that stays inside the repo resolves normally (monorepo sibling)
        (tmp_path / "guide.md").write_text("# Guide\n")
        sub = tmp_path / "docs"
        sub.mkdir()
        (sub / "page.md").write_text("[home](../guide.md)\n")
        assert _dr_run(tmp_path).status == CheckStatus.PASSED

    def test_fenced_code_block_skipped(self, tmp_path):
        # handlers[key](arg) is python subscript-then-call, not a link
        (tmp_path / "README.md").write_text(
            "# Doc\n\n```python\nreturn handlers[parsed_args.command](parsed_args)\n```\n"
        )
        assert _dr_run(tmp_path).status == CheckStatus.PASSED

    def test_tilde_fence_skipped(self, tmp_path):
        (tmp_path / "README.md").write_text("~~~python\nd = cfg[name](value)\n~~~\n")
        assert _dr_run(tmp_path).status == CheckStatus.PASSED

    def test_inline_code_span_skipped(self, tmp_path):
        (tmp_path / "README.md").write_text("Call `handlers[cmd](args)` to run.\n")
        assert _dr_run(tmp_path).status == CheckStatus.PASSED

    def test_link_after_fence_still_checked(self, tmp_path):
        # closing the fence must re-enable checking, or real breaks slip through
        (tmp_path / "README.md").write_text(
            "```python\nx = a[b](c)\n```\n\n[gone](./missing.md)\n"
        )
        result = _dr_run(tmp_path)
        assert result.status == CheckStatus.FAILED
        assert "missing.md" in str(result.findings[0].message)

    def test_code_span_as_link_text_still_checked(self, tmp_path):
        # blanking the span must not swallow the link's target
        (tmp_path / "README.md").write_text("[`spec.md`](./missing_spec.md)\n")
        result = _dr_run(tmp_path)
        assert result.status == CheckStatus.FAILED
        assert "missing_spec.md" in str(result.findings[0].message)
