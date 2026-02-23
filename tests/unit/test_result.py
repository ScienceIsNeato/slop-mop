"""Tests for core result types."""

from slopmop.core.result import (
    CheckDefinition,
    CheckResult,
    CheckStatus,
    ExecutionSummary,
)


class TestCheckStatus:
    """Tests for CheckStatus enum."""

    def test_status_values(self):
        """Test that all status values are correct."""
        assert CheckStatus.PASSED.value == "passed"
        assert CheckStatus.FAILED.value == "failed"
        assert CheckStatus.SKIPPED.value == "skipped"
        assert CheckStatus.NOT_APPLICABLE.value == "not_applicable"
        assert CheckStatus.ERROR.value == "error"
        assert CheckStatus.WARNED.value == "warned"

    def test_status_str(self):
        """Test string representation."""
        assert str(CheckStatus.PASSED) == "passed"
        assert str(CheckStatus.FAILED) == "failed"
        assert str(CheckStatus.WARNED) == "warned"


class TestCheckResult:
    """Tests for CheckResult dataclass."""

    def test_create_result(self):
        """Test creating a check result."""
        result = CheckResult(
            name="test-check",
            status=CheckStatus.PASSED,
            duration=1.5,
            output="All tests passed",
        )

        assert result.name == "test-check"
        assert result.status == CheckStatus.PASSED
        assert result.duration == 1.5
        assert result.output == "All tests passed"
        assert result.error is None
        assert result.fix_suggestion is None

    def test_passed_property(self):
        """Test passed property."""
        passed_result = CheckResult("test", CheckStatus.PASSED, 1.0)
        failed_result = CheckResult("test", CheckStatus.FAILED, 1.0)

        assert passed_result.passed is True
        assert failed_result.passed is False

    def test_failed_property(self):
        """Test failed property."""
        passed_result = CheckResult("test", CheckStatus.PASSED, 1.0)
        failed_result = CheckResult("test", CheckStatus.FAILED, 1.0)

        assert passed_result.failed is False
        assert failed_result.failed is True

    def test_str_representation(self):
        """Test string representation."""
        result = CheckResult("test-check", CheckStatus.PASSED, 1.5)
        result_str = str(result)

        assert "test-check" in result_str
        assert "passed" in result_str
        assert "1.50s" in result_str
        assert "✅" in result_str

    def test_str_representation_warned(self):
        """Test string representation for warned status."""
        result = CheckResult("test-check", CheckStatus.WARNED, 1.5)
        result_str = str(result)

        assert "test-check" in result_str
        assert "warned" in result_str
        assert "\u26a0\ufe0f" in result_str

    def test_warned_not_passed_not_failed(self):
        """Test that warned status is neither passed nor failed."""
        result = CheckResult("test-check", CheckStatus.WARNED, 1.0)
        assert result.passed is False
        assert result.failed is False

    def test_result_with_error(self):
        """Test result with error info."""
        result = CheckResult(
            name="test-check",
            status=CheckStatus.FAILED,
            duration=2.0,
            error="Test failed",
            fix_suggestion="Fix the test",
        )

        assert result.error == "Test failed"
        assert result.fix_suggestion == "Fix the test"


class TestCheckDefinition:
    """Tests for CheckDefinition dataclass."""

    def test_create_definition(self):
        """Test creating a check definition."""
        definition = CheckDefinition(
            flag="laziness:py-lint",
            name="🎨 Python Lint & Format",
        )

        assert definition.flag == "laziness:py-lint"
        assert definition.name == "🎨 Python Lint & Format"
        assert definition.depends_on == []
        assert definition.auto_fix is False

    def test_definition_with_dependencies(self):
        """Test definition with dependencies."""
        definition = CheckDefinition(
            flag="deceptiveness:py-coverage",
            name="📊 Coverage",
            depends_on=["overconfidence:py-tests"],
        )

        assert definition.depends_on == ["overconfidence:py-tests"]

    def test_definition_equality(self):
        """Test definition equality based on flag."""
        def1 = CheckDefinition("test", "Test 1")
        def2 = CheckDefinition("test", "Test 2")
        def3 = CheckDefinition("other", "Other")

        assert def1 == def2
        assert def1 != def3

    def test_definition_hash(self):
        """Test definition hashing."""
        def1 = CheckDefinition("test", "Test")
        def2 = CheckDefinition("test", "Test")

        assert hash(def1) == hash(def2)
        assert {def1, def2} == {def1}


class TestExecutionSummary:
    """Tests for ExecutionSummary dataclass."""

    def test_from_results_all_passed(self):
        """Test creating summary from all passed results."""
        results = [
            CheckResult("check1", CheckStatus.PASSED, 1.0),
            CheckResult("check2", CheckStatus.PASSED, 2.0),
        ]

        summary = ExecutionSummary.from_results(results, 3.0)

        assert summary.total_checks == 2
        assert summary.passed == 2
        assert summary.failed == 0
        assert summary.total_duration == 3.0
        assert summary.all_passed is True

    def test_from_results_with_failures(self):
        """Test creating summary with failures."""
        results = [
            CheckResult("check1", CheckStatus.PASSED, 1.0),
            CheckResult("check2", CheckStatus.FAILED, 2.0),
            CheckResult("check3", CheckStatus.SKIPPED, 0.0),
            CheckResult("check4", CheckStatus.ERROR, 1.0),
            CheckResult("check5", CheckStatus.NOT_APPLICABLE, 0.0),
            CheckResult("check6", CheckStatus.WARNED, 0.5),
        ]

        summary = ExecutionSummary.from_results(results, 4.0)

        assert summary.total_checks == 6
        assert summary.passed == 1
        assert summary.failed == 1
        assert summary.skipped == 1
        assert summary.not_applicable == 1
        assert summary.errors == 1
        assert summary.warned == 1
        assert summary.all_passed is False

    def test_all_passed_true_with_warnings(self):
        """Test that warnings alone don't cause all_passed to be False."""
        results = [
            CheckResult("check1", CheckStatus.PASSED, 1.0),
            CheckResult("check2", CheckStatus.WARNED, 0.5),
        ]

        summary = ExecutionSummary.from_results(results, 1.5)
        assert summary.all_passed is True
        assert summary.warned == 1

    def test_all_passed_false_with_errors(self):
        """Test that errors cause all_passed to be False."""
        results = [
            CheckResult("check1", CheckStatus.PASSED, 1.0),
            CheckResult("check2", CheckStatus.ERROR, 1.0),
        ]

        summary = ExecutionSummary.from_results(results, 2.0)
        assert summary.all_passed is False
