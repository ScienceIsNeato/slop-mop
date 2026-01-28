"""Tests for template_validation.py — Jinja2 syntax check."""

import os

from slopbucket.checks.template_validation import TemplateValidationCheck
from slopbucket.result import CheckStatus


class TestTemplateValidationCheck:
    """Validates template syntax check pass/fail/skip logic."""

    def setup_method(self) -> None:
        self.check = TemplateValidationCheck()

    def test_name_and_description(self) -> None:
        assert self.check.name == "template-validation"
        assert (
            "Jinja2" in self.check.description
            or "template" in self.check.description.lower()
        )

    def test_skips_when_no_templates(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.SKIPPED

    def test_passes_with_valid_templates(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tpl_dir = os.path.join(td, "templates")
            os.makedirs(tpl_dir)
            with open(os.path.join(tpl_dir, "index.html"), "w") as f:
                f.write("<h1>{{ title }}</h1>")
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.PASSED

    def test_fails_with_invalid_template(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tpl_dir = os.path.join(td, "templates")
            os.makedirs(tpl_dir)
            with open(os.path.join(tpl_dir, "bad.html"), "w") as f:
                f.write("{% if x %}no end tag")
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.FAILED
