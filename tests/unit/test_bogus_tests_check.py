"""Tests for bogus test detection check."""

import textwrap

from slopmop.checks.quality.bogus_tests import (
    BogusTestsCheck,
)
from slopmop.core.result import CheckStatus


class TestBogusTestsCheckProperties:
    """Tests for BogusTestsCheck metadata."""

    def test_name(self):
        """Test check name."""
        check = BogusTestsCheck({})
        assert check.name == "bogus-tests"

    def test_full_name(self):
        """Test full check name with category."""
        check = BogusTestsCheck({})
        assert check.full_name == "deceptiveness:bogus-tests"

    def test_display_name(self):
        """Test display name."""
        check = BogusTestsCheck({})
        assert "Bogus" in check.display_name

    def test_description(self):
        """Test description is present."""
        check = BogusTestsCheck({})
        assert len(check.description) > 0

    def test_config_schema(self):
        """Test config schema includes expected fields."""
        check = BogusTestsCheck({})
        schema = check.config_schema
        field_names = [f.name for f in schema]
        assert "test_dirs" in field_names
        assert "exclude_patterns" in field_names
        assert "min_test_statements" in field_names
        assert "short_test_severity" in field_names

    def test_min_test_statements_allows_zero(self):
        """Test that min_test_statements accepts 0 (disable heuristic)."""
        check = BogusTestsCheck({})
        schema = check.config_schema
        mts = next(f for f in schema if f.name == "min_test_statements")
        assert mts.min_value == 0
        assert mts.default == 1


class TestBogusTestsApplicability:
    """Tests for is_applicable behavior."""

    def test_applicable_with_test_files(self, tmp_path):
        """Test is_applicable returns True when test files exist."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_example.py").write_text("def test_something(): pass")
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        assert check.is_applicable(str(tmp_path)) is True

    def test_not_applicable_without_test_files(self, tmp_path):
        """Test is_applicable returns False when no test files exist."""
        (tmp_path / "app.py").write_text("print('hello')")
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        assert check.is_applicable(str(tmp_path)) is False

    def test_not_applicable_empty_test_dir(self, tmp_path):
        """Test is_applicable returns False for empty test directory."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        assert check.is_applicable(str(tmp_path)) is False


class TestEmptyTestBodies:
    """Tests for detection of empty test bodies."""

    def test_detects_pass_body(self, tmp_path):
        """Test detects test with only pass."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_empty.py").write_text(textwrap.dedent("""\
            def test_nothing():
                pass
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "empty test body" in result.output

    def test_detects_ellipsis_body(self, tmp_path):
        """Test detects test with only ellipsis."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_empty.py").write_text(textwrap.dedent("""\
            def test_nothing():
                ...
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "empty test body" in result.output

    def test_detects_docstring_only_body(self, tmp_path):
        """Test detects test with only a docstring."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_empty.py").write_text(textwrap.dedent('''\
            def test_nothing():
                """This test does nothing."""
            '''))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "empty test body" in result.output

    def test_detects_docstring_plus_pass(self, tmp_path):
        """Test detects test with docstring and pass."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_empty.py").write_text(textwrap.dedent('''\
            def test_nothing():
                """This test does nothing."""
                pass
            '''))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "empty test body" in result.output


class TestTautologicalAssertions:
    """Tests for detection of tautological assertions."""

    def test_detects_assert_true(self, tmp_path):
        """Test detects assert True."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_taut.py").write_text(textwrap.dedent("""\
            def test_bogus():
                assert True
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "tautological" in result.output

    def test_detects_assert_not_false(self, tmp_path):
        """Test detects assert not False."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_taut.py").write_text(textwrap.dedent("""\
            def test_bogus():
                assert not False
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "tautological" in result.output

    def test_detects_assert_equal_constants(self, tmp_path):
        """Test detects assert 1 == 1."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_taut.py").write_text(textwrap.dedent("""\
            def test_bogus():
                assert 1 == 1
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "tautological" in result.output

    def test_detects_tautology_with_ellipsis_and_docstring(self, tmp_path):
        """Ellipsis and docstrings are ignored — tautology is still flagged."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_taut.py").write_text(textwrap.dedent("""\
            def test_bogus():
                \"\"\"Looks busy but isn't.\"\"\"
                ...
                assert True
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "tautological" in result.output

    def test_does_not_flag_tautology_with_real_code(self, tmp_path):
        """Test does NOT flag assert True if real assertions also present."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_mixed.py").write_text(textwrap.dedent("""\
            def test_real_with_tautology():
                result = 2 + 2
                assert result == 4
                assert True  # belt and suspenders
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED


class TestShortTests:
    """Tests for the short-test heuristic (no assert + few statements)."""

    def test_detects_one_statement_no_assert(self, tmp_path):
        """Single-statement test with no assert is flagged at default threshold."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_short.py").write_text(textwrap.dedent("""\
            def test_just_a_call():
                print("hello")
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "suspiciously short" in result.output

    def test_detects_two_statements_no_assert(self, tmp_path):
        """Two-statement test with no assert is flagged at threshold=2."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_short.py").write_text(textwrap.dedent("""\
            def test_two_lines():
                x = 1 + 1
                print(x)
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"], "min_test_statements": 2})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "suspiciously short" in result.output

    def test_two_statements_pass_at_default_threshold(self, tmp_path):
        """Two-statement test passes at default threshold (1)."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_short.py").write_text(textwrap.dedent("""\
            def test_two_lines():
                x = 1 + 1
                print(x)
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_passes_three_statements_no_assert(self, tmp_path):
        """Three-statement test with no assert passes at threshold=2."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_long.py").write_text(textwrap.dedent("""\
            def test_three_lines():
                x = 1
                y = x + 1
                print(y)
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"], "min_test_statements": 2})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_threshold_zero_disables_heuristic(self, tmp_path):
        """Setting min_test_statements=0 disables the short-test check."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_short.py").write_text(textwrap.dedent("""\
            def test_just_a_call():
                print("hello")
            """))
        check = BogusTestsCheck(
            {
                "test_dirs": ["tests"],
                "min_test_statements": 0,
            }
        )
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_custom_threshold(self, tmp_path):
        """Custom threshold flags tests at that level."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_medium.py").write_text(textwrap.dedent("""\
            def test_four_lines():
                a = 1
                b = 2
                c = a + b
                print(c)
            """))
        check = BogusTestsCheck(
            {
                "test_dirs": ["tests"],
                "min_test_statements": 5,
            }
        )
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "suspiciously short" in result.output

    def test_warn_severity(self, tmp_path):
        """Short-test severity 'warn' returns WARNED instead of FAILED."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_short.py").write_text(textwrap.dedent("""\
            def test_just_a_call():
                print("hello")
            """))
        check = BogusTestsCheck(
            {
                "test_dirs": ["tests"],
                "short_test_severity": "warn",
            }
        )
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.WARNED
        assert "suspicious" in result.output

    def test_framework_test_passes_above_threshold(self, tmp_path):
        """Longer framework tests (e.g., Playwright) pass at default threshold."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_playwright.py").write_text(textwrap.dedent("""\
            from playwright.sync_api import expect

            def test_homepage(page):
                page.goto("https://example.com")
                expect(page.locator("h1")).to_be_visible()
                expect(page.locator("h1")).to_have_text("Hello")
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_assert_keyword_exempts_from_short_test(self, tmp_path):
        """Tests with assert keyword are never flagged as short tests."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_short_assert.py").write_text(textwrap.dedent("""\
            def test_short_but_asserts():
                assert True is not False
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        # Has assert keyword → not a short-test finding
        # Has non-tautological assertion → passes
        assert result.status == CheckStatus.PASSED

    def test_pytest_raises_exempts_from_short_test(self, tmp_path):
        """Tests with pytest.raises are never flagged as short tests."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_raises.py").write_text(textwrap.dedent("""\
            import pytest

            def test_raises_value_error():
                with pytest.raises(ValueError):
                    int("not a number")
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_pytest_warns_exempts_from_short_test(self, tmp_path):
        """Tests with pytest.warns are never flagged as short tests."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_warns.py").write_text(textwrap.dedent("""\
            import pytest
            import warnings

            def test_warns_deprecation():
                with pytest.warns(DeprecationWarning):
                    warnings.warn("old", DeprecationWarning)
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_pytest_raises_with_match_exempts(self, tmp_path):
        """pytest.raises with match kwarg is also recognised."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_raises_match.py").write_text(textwrap.dedent("""\
            import pytest

            def test_raises_with_match():
                with pytest.raises(ValueError, match="invalid"):
                    int("nope")
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_non_pytest_context_manager_still_flagged(self, tmp_path):
        """Non-pytest context managers don't exempt from short-test."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_other_cm.py").write_text(textwrap.dedent("""\
            def test_with_open():
                with open("/dev/null") as f:
                    f.read()
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "suspiciously short" in result.output


class TestSuppression:
    """Tests for the inline suppression comment."""

    def test_suppression_on_def_line(self, tmp_path):
        """Suppression comment on the def line skips short-test."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_supp.py").write_text(textwrap.dedent("""\
            def test_smoke():  # overconfidence:short-test-ok
                print("ok")
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_suppression_in_body(self, tmp_path):
        """Suppression comment inside the function body works."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_supp.py").write_text(textwrap.dedent("""\
            def test_smoke():
                # overconfidence:short-test-ok
                print("ok")
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_suppression_only_affects_annotated_test(self, tmp_path):
        """Suppression only affects the annotated test."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_mixed_supp.py").write_text(textwrap.dedent("""\
            def test_suppressed():  # overconfidence:short-test-ok
                print("ok")

            def test_not_suppressed():
                print("also ok")
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "test_not_suppressed" in result.output
        assert "test_suppressed" not in result.output

    def test_suppression_does_not_affect_empty_body(self, tmp_path):
        """Suppression does NOT suppress empty body detection."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_supp_empty.py").write_text(textwrap.dedent("""\
            def test_empty():  # overconfidence:short-test-ok
                pass
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "empty test body" in result.output

    def test_suppression_does_not_affect_tautology(self, tmp_path):
        """Suppression does NOT suppress tautological assertion detection."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_supp_taut.py").write_text(textwrap.dedent("""\
            def test_taut():  # overconfidence:short-test-ok
                assert True
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "tautological" in result.output


class TestLegitimateTests:
    """Tests confirming legitimate test patterns are not flagged."""

    def test_normal_assertion_passes(self, tmp_path):
        """Test that a normal test with assertions passes."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_good.py").write_text(textwrap.dedent("""\
            def test_addition():
                assert 2 + 2 == 4

            def test_string():
                assert "hello".upper() == "HELLO"
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_class_based_tests_pass(self, tmp_path):
        """Test that class-based test methods are also checked."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_class.py").write_text(textwrap.dedent("""\
            class TestMyClass:
                def test_something(self):
                    assert 1 + 1 == 2
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_non_test_functions_ignored(self, tmp_path):
        """Test that helper functions without assertions are not flagged."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_helpers.py").write_text(textwrap.dedent("""\
            def make_fixture():
                return {"key": "value"}

            def test_with_helper():
                data = make_fixture()
                assert data["key"] == "value"
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_no_test_files_passes(self, tmp_path):
        """Test passes when test directory has no test files."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "conftest.py").write_text("# config only")
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        # Not applicable, but if run somehow, should not crash
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED


class TestExcludePatterns:
    """Tests for file exclusion behavior."""

    def test_conftest_excluded_by_default(self, tmp_path):
        """Test that conftest.py is excluded by default."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        # conftest fixtures often don't have assertions
        (test_dir / "conftest.py").write_text(textwrap.dedent("""\
            def test_like_fixture():
                x = 1
            """))
        (test_dir / "test_real.py").write_text(textwrap.dedent("""\
            def test_good():
                assert True is not False
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        # conftest should be skipped, and test_real has a real assertion
        assert result.status == CheckStatus.PASSED


class TestMultipleFindings:
    """Tests for output when multiple bogus tests are found."""

    def test_reports_all_findings(self, tmp_path):
        """Test that all bogus tests in a file are reported."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_multi.py").write_text(textwrap.dedent("""\
            def test_empty():
                pass

            def test_tautology():
                assert True

            def test_short_no_assert():
                x = 1 + 1

            def test_real():
                assert 2 + 2 == 4
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        # 2 hard findings + 1 short-test finding = 3 total
        assert "3 bogus test(s)" in result.output
        assert "test_empty" in result.output
        assert "test_tautology" in result.output
        assert "test_short_no_assert" in result.output
        assert "suspiciously short" in result.output
        assert "test_real" not in result.output


class TestFixSuggestion:
    """Tests for tailored fix_suggestion based on finding types."""

    def test_hard_only_suggests_rewrite(self, tmp_path):
        """When only hard failures, don't suggest suppression comment."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_hard.py").write_text(textwrap.dedent("""\
            def test_empty():
                pass
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "cannot be suppressed" in result.fix_suggestion
        assert "short-test-ok" not in result.fix_suggestion

    def test_short_only_suggests_suppression(self, tmp_path):
        """When only short-test findings, suggest suppression comment."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_short.py").write_text(textwrap.dedent("""\
            def test_stub():
                x = 1
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "short-test-ok" in result.fix_suggestion
        assert "cannot be suppressed" not in result.fix_suggestion

    def test_mixed_suggests_both(self, tmp_path):
        """When both hard and short findings, explain both."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_mixed.py").write_text(textwrap.dedent("""\
            def test_empty():
                pass

            def test_stub():
                x = 1
            """))
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "cannot be suppressed" in result.fix_suggestion
        assert "short-test-ok" in result.fix_suggestion


class TestSyntaxErrors:
    """Tests for handling malformed test files."""

    def test_reports_syntax_errors(self, tmp_path):
        """Test that unparseable test files produce ERROR status."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_broken.py").write_text("def test_broken(:\n    pass\n")
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.ERROR
        assert "parse" in result.error.lower()
