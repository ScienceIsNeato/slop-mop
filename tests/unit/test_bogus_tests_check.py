"""Tests for bogus test detection check."""

import textwrap

from slopmop.checks.quality.bogus_tests import BogusTestsCheck, _TestAnalyzer
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
        assert check.full_name == "quality:bogus-tests"

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
        (test_dir / "test_empty.py").write_text(
            textwrap.dedent("""\
            def test_nothing():
                pass
            """)
        )
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "empty test body" in result.output

    def test_detects_ellipsis_body(self, tmp_path):
        """Test detects test with only ellipsis."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_empty.py").write_text(
            textwrap.dedent("""\
            def test_nothing():
                ...
            """)
        )
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "empty test body" in result.output

    def test_detects_docstring_only_body(self, tmp_path):
        """Test detects test with only a docstring."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_empty.py").write_text(
            textwrap.dedent('''\
            def test_nothing():
                """This test does nothing."""
            ''')
        )
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "empty test body" in result.output

    def test_detects_docstring_plus_pass(self, tmp_path):
        """Test detects test with docstring and pass."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_empty.py").write_text(
            textwrap.dedent('''\
            def test_nothing():
                """This test does nothing."""
                pass
            ''')
        )
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
        (test_dir / "test_taut.py").write_text(
            textwrap.dedent("""\
            def test_bogus():
                assert True
            """)
        )
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "tautological" in result.output

    def test_detects_assert_not_false(self, tmp_path):
        """Test detects assert not False."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_taut.py").write_text(
            textwrap.dedent("""\
            def test_bogus():
                assert not False
            """)
        )
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "tautological" in result.output

    def test_detects_assert_equal_constants(self, tmp_path):
        """Test detects assert 1 == 1."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_taut.py").write_text(
            textwrap.dedent("""\
            def test_bogus():
                assert 1 == 1
            """)
        )
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "tautological" in result.output

    def test_does_not_flag_tautology_with_real_code(self, tmp_path):
        """Test does NOT flag assert True if real assertions also present."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_mixed.py").write_text(
            textwrap.dedent("""\
            def test_real_with_tautology():
                result = 2 + 2
                assert result == 4
                assert True  # belt and suspenders
            """)
        )
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED


class TestNoAssertions:
    """Tests for detection of assertion-free test functions."""

    def test_detects_no_assertions(self, tmp_path):
        """Test detects test function with no assert statements."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_noassert.py").write_text(
            textwrap.dedent("""\
            def test_no_assertions():
                x = 1 + 1
                y = x * 2
                print(y)
            """)
        )
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "no assertions" in result.output

    def test_allows_pytest_raises(self, tmp_path):
        """Test accepts pytest.raises as a valid assertion."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_raises.py").write_text(
            textwrap.dedent("""\
            import pytest

            def test_raises_exception():
                with pytest.raises(ValueError):
                    int("not_a_number")
            """)
        )
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_allows_mock_assert_called(self, tmp_path):
        """Test accepts mock.assert_called_once_with as a valid assertion."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_mock.py").write_text(
            textwrap.dedent("""\
            from unittest.mock import MagicMock

            def test_mock_called():
                mock = MagicMock()
                mock("hello")
                mock.assert_called_once_with("hello")
            """)
        )
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED


class TestLegitimateTests:
    """Tests confirming legitimate test patterns are not flagged."""

    def test_normal_assertion_passes(self, tmp_path):
        """Test that a normal test with assertions passes."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_good.py").write_text(
            textwrap.dedent("""\
            def test_addition():
                assert 2 + 2 == 4

            def test_string():
                assert "hello".upper() == "HELLO"
            """)
        )
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_class_based_tests_pass(self, tmp_path):
        """Test that class-based test methods are also checked."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_class.py").write_text(
            textwrap.dedent("""\
            class TestMyClass:
                def test_something(self):
                    assert 1 + 1 == 2
            """)
        )
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_non_test_functions_ignored(self, tmp_path):
        """Test that helper functions without assertions are not flagged."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_helpers.py").write_text(
            textwrap.dedent("""\
            def make_fixture():
                return {"key": "value"}

            def test_with_helper():
                data = make_fixture()
                assert data["key"] == "value"
            """)
        )
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
        (test_dir / "conftest.py").write_text(
            textwrap.dedent("""\
            def test_like_fixture():
                x = 1
            """)
        )
        (test_dir / "test_real.py").write_text(
            textwrap.dedent("""\
            def test_good():
                assert True is not False
            """)
        )
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
        (test_dir / "test_multi.py").write_text(
            textwrap.dedent("""\
            def test_empty():
                pass

            def test_tautology():
                assert True

            def test_no_assert():
                x = 1 + 1

            def test_real():
                assert 2 + 2 == 4
            """)
        )
        check = BogusTestsCheck({"test_dirs": ["tests"]})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "3 bogus test(s)" in result.output
        assert "test_empty" in result.output
        assert "test_tautology" in result.output
        assert "test_no_assert" in result.output
        assert "test_real" not in result.output


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
