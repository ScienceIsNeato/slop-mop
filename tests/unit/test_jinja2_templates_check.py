"""Tests for TemplateValidationCheck (Jinja2 templates)."""

from unittest.mock import patch

from slopbucket.checks.general.jinja2_templates import TemplateValidationCheck
from slopbucket.core.result import CheckStatus
from slopbucket.subprocess.runner import SubprocessResult


def _make_result(output: str = "", returncode: int = 0):
    """Helper to create SubprocessResult with correct constructor."""
    return SubprocessResult(
        returncode=returncode,
        stdout=output,
        stderr="",
        duration=0.1,
        timed_out=False,
    )


class TestTemplateValidationCheck:
    """Tests for TemplateValidationCheck."""

    def test_name(self):
        """Test check name."""
        check = TemplateValidationCheck({})
        assert check.name == "templates"

    def test_display_name(self):
        """Test display name."""
        check = TemplateValidationCheck({})
        assert "Template Validation" in check.display_name
        assert "Jinja2" in check.display_name

    def test_full_name(self):
        """Test full name includes category."""
        check = TemplateValidationCheck({})
        assert check.full_name == "general:templates"

    def test_config_schema(self):
        """Test config schema defines templates_dir."""
        check = TemplateValidationCheck({})
        schema = check.config_schema
        assert len(schema) == 1
        assert schema[0].name == "templates_dir"
        assert schema[0].required is True

    def test_is_applicable_no_config(self, tmp_path):
        """Test is_applicable returns False without config."""
        check = TemplateValidationCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_is_applicable_no_directory(self, tmp_path):
        """Test is_applicable returns False if dir doesn't exist."""
        check = TemplateValidationCheck({"templates_dir": "templates"})
        assert check.is_applicable(str(tmp_path)) is False

    def test_is_applicable_with_valid_config(self, tmp_path):
        """Test is_applicable returns True with valid config."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        check = TemplateValidationCheck({"templates_dir": "templates"})
        assert check.is_applicable(str(tmp_path)) is True

    def test_run_no_templates_dir(self, tmp_path):
        """Test run skips when no templates_dir configured."""
        check = TemplateValidationCheck({})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.SKIPPED
        assert "No templates_dir configured" in result.output
        assert ".sb_config.json" in result.fix_suggestion

    def test_run_with_template_smoke_test(self, tmp_path):
        """Test run uses existing template smoke test when available."""
        # Create the template test file structure
        test_dir = tmp_path / "tests" / "integration"
        test_dir.mkdir(parents=True)
        test_file = test_dir / "test_template_smoke.py"
        test_file.write_text("# test file")

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        check = TemplateValidationCheck({"templates_dir": "templates"})

        success_result = _make_result(output="1 passed", returncode=0)
        with patch.object(check, "_run_command", return_value=success_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert "successfully" in result.output

    def test_run_template_test_fails(self, tmp_path):
        """Test run reports failure when template test fails."""
        test_dir = tmp_path / "tests" / "integration"
        test_dir.mkdir(parents=True)
        test_file = test_dir / "test_template_smoke.py"
        test_file.write_text("# test file")

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        check = TemplateValidationCheck({"templates_dir": "templates"})

        fail_result = _make_result(output="FAILED test_x.py", returncode=1)
        with patch.object(check, "_run_command", return_value=fail_result):
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "Template compilation failed" in result.error
        assert "Fix Jinja2 syntax errors" in result.fix_suggestion

    def test_run_validates_templates_all_pass(self, tmp_path):
        """Test run passes when all templates compile."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        # Create valid template files
        (templates_dir / "base.html").write_text("<html>{{ title }}</html>")
        (templates_dir / "partial.j2").write_text("{% block content %}{% endblock %}")

        check = TemplateValidationCheck({"templates_dir": "templates"})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert "2 templates" in result.output
        assert "successfully" in result.output

    def test_run_validates_templates_with_errors(self, tmp_path):
        """Test run fails when templates have syntax errors."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        # Create invalid template file
        (templates_dir / "bad.html").write_text("{{ unclosed")

        check = TemplateValidationCheck({"templates_dir": "templates"})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "1 template(s) failed to compile" in result.error
        assert "bad.html" in result.output
        assert "Fix Jinja2 syntax errors" in result.fix_suggestion

    def test_run_validates_templates_nested_dirs(self, tmp_path):
        """Test run validates templates in nested directories."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        # Create nested structure
        subdir = templates_dir / "partials"
        subdir.mkdir()
        (subdir / "header.html").write_text("<header>{{ name }}</header>")
        (templates_dir / "main.html").write_text(
            "<main>{% include 'partials/header.html' %}</main>"
        )

        check = TemplateValidationCheck({"templates_dir": "templates"})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert "2 templates" in result.output

    def test_run_ignores_non_template_files(self, tmp_path):
        """Test run ignores non-template file extensions."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        # Create non-template files (should be ignored)
        (templates_dir / "readme.txt").write_text("Not a template")
        (templates_dir / "style.css").write_text(".class { }")
        # Create one valid template
        (templates_dir / "index.html").write_text("<html>{{ content }}</html>")

        check = TemplateValidationCheck({"templates_dir": "templates"})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        # Should only count 1 template (the .html file)
        assert "1 template" in result.output


class TestTemplateValidationCheckHelpers:
    """Tests for TemplateValidationCheck helper methods."""

    def test_get_templates_dir_no_config(self, tmp_path):
        """Test _get_templates_dir returns None without config."""
        check = TemplateValidationCheck({})
        assert check._get_templates_dir(str(tmp_path)) is None

    def test_get_templates_dir_missing_directory(self, tmp_path):
        """Test _get_templates_dir returns None if dir doesn't exist."""
        check = TemplateValidationCheck({"templates_dir": "missing"})
        assert check._get_templates_dir(str(tmp_path)) is None

    def test_get_templates_dir_valid(self, tmp_path):
        """Test _get_templates_dir returns dir name when valid."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        check = TemplateValidationCheck({"templates_dir": "templates"})
        assert check._get_templates_dir(str(tmp_path)) == "templates"
