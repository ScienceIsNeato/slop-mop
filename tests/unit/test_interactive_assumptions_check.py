"""Tests for the interactive-assumptions gate."""

from slopmop.checks.base import GateCategory, GateLevel, ToolContext
from slopmop.checks.general.interactive_assumptions import InteractiveAssumptionsCheck
from slopmop.core.result import CheckStatus


def _ia_run(tmp_path, config=None):
    return InteractiveAssumptionsCheck(config or {}).run(str(tmp_path))


def _ia_check(config=None):
    return InteractiveAssumptionsCheck(config or {})


# ---------------------------------------------------------------------------
# Identity / metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_name(self):
        assert _ia_check().name == "interactive-assumptions"

    def test_full_name(self):
        assert _ia_check().full_name == "myopia:interactive-assumptions"

    def test_category(self):
        assert _ia_check().category == GateCategory.MYOPIA

    def test_gate_level(self):
        assert InteractiveAssumptionsCheck.level == GateLevel.SCOUR

    def test_tool_context(self):
        assert InteractiveAssumptionsCheck.tool_context == ToolContext.PURE

    def test_display_name_has_emoji(self):
        assert "🙋" in _ia_check().display_name


# ---------------------------------------------------------------------------
# Applicability
# ---------------------------------------------------------------------------


class TestApplicability:
    def test_applicable_with_sh_file(self, tmp_path):
        (tmp_path / "build.sh").write_text("echo hi\n")
        assert _ia_check().is_applicable(str(tmp_path)) is True

    def test_applicable_with_yaml_file(self, tmp_path):
        (tmp_path / "ci.yml").write_text("steps: []\n")
        assert _ia_check().is_applicable(str(tmp_path)) is True

    def test_applicable_with_dockerfile(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM ubuntu\n")
        assert _ia_check().is_applicable(str(tmp_path)) is True

    def test_applicable_with_dockerfile_variant(self, tmp_path):
        (tmp_path / "Dockerfile.dev").write_text("FROM ubuntu\n")
        assert _ia_check().is_applicable(str(tmp_path)) is True

    def test_applicable_with_makefile(self, tmp_path):
        (tmp_path / "Makefile").write_text("all:\n\techo hi\n")
        assert _ia_check().is_applicable(str(tmp_path)) is True

    def test_not_applicable_python_only(self, tmp_path):
        (tmp_path / "app.py").write_text("print('hi')\n")
        assert _ia_check().is_applicable(str(tmp_path)) is False

    def test_not_applicable_empty_dir(self, tmp_path):
        assert _ia_check().is_applicable(str(tmp_path)) is False

    def test_not_applicable_when_only_excluded_dirs(self, tmp_path):
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "build.sh").write_text("echo hi\n")
        assert _ia_check().is_applicable(str(tmp_path)) is False


# ---------------------------------------------------------------------------
# NPX patterns
# ---------------------------------------------------------------------------


class TestNpxPatterns:
    def test_npx_without_yes_fails(self, tmp_path):
        (tmp_path / "ci.yml").write_text("      run: npx jest --coverage\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.FAILED

    def test_npx_with_yes_passes(self, tmp_path):
        (tmp_path / "ci.yml").write_text("      run: npx --yes jest --coverage\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.PASSED

    def test_npx_yes_anywhere_on_line_passes(self, tmp_path):
        # --yes can appear after the tool name too.
        (tmp_path / "ci.yml").write_text("      run: npx jest --yes --coverage\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.PASSED

    def test_npx_in_shell_script_fails(self, tmp_path):
        (tmp_path / "build.sh").write_text("npx jscpd src/\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.FAILED

    def test_npx_versioned_without_yes_fails(self, tmp_path):
        (tmp_path / "ci.yml").write_text("npx jest@30.3.0 --coverage\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.FAILED

    def test_npx_in_comment_ignored(self, tmp_path):
        # Comment line should not be flagged.
        (tmp_path / "build.sh").write_text("# npx jest --coverage (without --yes)\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.PASSED

    def test_npx_finding_has_rule_id(self, tmp_path):
        (tmp_path / "ci.yml").write_text("run: npx tsc\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.FAILED
        assert any(f.rule_id == "npx-without-yes" for f in (r.findings or []))

    def test_npx_finding_has_correct_line(self, tmp_path):
        (tmp_path / "ci.yml").write_text("steps:\n  - run: npx eslint .\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.FAILED
        findings = [f for f in (r.findings or []) if f.rule_id == "npx-without-yes"]
        assert len(findings) == 1
        assert findings[0].line == 2

    def test_npx_multiple_occurrences(self, tmp_path):
        content = "npx jest\nnpx --yes eslint\nnpx tsc\n"
        (tmp_path / "ci.yml").write_text(content)
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.FAILED
        bad = [f for f in (r.findings or []) if f.rule_id == "npx-without-yes"]
        assert len(bad) == 2  # lines 1 and 3; line 2 has --yes

    def test_npx_in_makefile_fails(self, tmp_path):
        (tmp_path / "Makefile").write_text("test:\n\tnpx jest\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.FAILED


# ---------------------------------------------------------------------------
# APT patterns
# ---------------------------------------------------------------------------


class TestAptPatterns:
    def test_apt_get_without_y_fails(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("RUN apt-get install python3\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.FAILED

    def test_apt_without_y_fails(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("RUN apt install vim\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.FAILED

    def test_apt_get_with_y_passes(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("RUN apt-get install -y python3\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.PASSED

    def test_apt_with_assume_yes_passes(self, tmp_path):
        (tmp_path / "Dockerfile").write_text(
            "RUN apt-get install --assume-yes python3\n"
        )
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.PASSED

    def test_apt_with_qq_passes(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("RUN apt-get install -qq python3\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.PASSED

    def test_apt_get_in_shell_script_fails(self, tmp_path):
        (tmp_path / "setup.sh").write_text("apt-get install build-essential\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.FAILED

    def test_apt_in_comment_ignored(self, tmp_path):
        (tmp_path / "setup.sh").write_text(
            "# apt-get install python3  (remember to add -y)\n"
        )
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.PASSED

    def test_apt_finding_has_rule_id(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("RUN apt-get install curl\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.FAILED
        assert any(f.rule_id == "apt-without-y" for f in (r.findings or []))

    def test_apt_in_yaml_fails(self, tmp_path):
        (tmp_path / "ci.yml").write_text("      run: apt-get install python3-pip\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.FAILED


# ---------------------------------------------------------------------------
# Mixed patterns
# ---------------------------------------------------------------------------


class TestMixedPatterns:
    def test_both_patterns_in_single_file(self, tmp_path):
        (tmp_path / "ci.yml").write_text(
            "run: apt-get install python3\nrun: npx jest\n"
        )
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.FAILED
        rule_ids = {f.rule_id for f in (r.findings or [])}
        assert "npx-without-yes" in rule_ids
        assert "apt-without-y" in rule_ids

    def test_clean_file_passes(self, tmp_path):
        (tmp_path / "ci.yml").write_text(
            "run: apt-get install -y python3\nrun: npx --yes jest\n"
        )
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.PASSED

    def test_output_contains_file_and_line(self, tmp_path):
        (tmp_path / "build.sh").write_text("npx jscpd .\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.FAILED
        assert "build.sh" in r.output
        assert ":1" in r.output

    def test_fix_suggestion_present(self, tmp_path):
        (tmp_path / "build.sh").write_text("npx jscpd .\n")
        r = _ia_run(tmp_path)
        assert r.fix_suggestion is not None
        assert "--yes" in r.fix_suggestion


# ---------------------------------------------------------------------------
# Directory exclusions
# ---------------------------------------------------------------------------


class TestExclusions:
    def test_husky_excluded_by_default(self, tmp_path):
        husky = tmp_path / ".husky"
        husky.mkdir()
        (husky / "pre-commit").write_text("npx lint-staged\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.PASSED

    def test_node_modules_excluded(self, tmp_path):
        nm = tmp_path / "node_modules" / "some-lib"
        nm.mkdir(parents=True)
        (nm / "install.sh").write_text("npx something\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.PASSED

    def test_custom_exclude_dirs_respected(self, tmp_path):
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "ci.sh").write_text("npx jest\n")
        # Without exclusion: fails.
        assert _ia_run(tmp_path).status is CheckStatus.FAILED
        # With exclusion: passes.
        r = _ia_run(tmp_path, config={"exclude_dirs": ["scripts"]})
        assert r.status is CheckStatus.PASSED

    def test_vendor_excluded_by_default(self, tmp_path):
        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / "bootstrap.sh").write_text("apt-get install curl\n")
        r = _ia_run(tmp_path)
        assert r.status is CheckStatus.PASSED
