"""Tests for the JavaScript bogus test detection gate."""

from slopmop.checks.javascript.bogus_tests import JavaScriptBogusTestsCheck
from slopmop.core.result import CheckStatus


class TestJavaScriptBogusTestsCheck:
    """Tests for JavaScriptBogusTestsCheck."""

    def test_config_schema_includes_additional_assert_functions(self):
        """Custom assertion helpers should be configurable."""
        check = JavaScriptBogusTestsCheck({})
        schema = check.config_schema
        field_names = [f.name for f in schema]

        assert "additional_assert_functions" in field_names

    def test_expect_prefix_helper_is_treated_as_assertion(self, tmp_path):
        """expect* helper wrappers should not trigger bogus-test failures."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "validation.test.ts").write_text("""
function expectValidationError(fn: () => unknown): void {
  const err = assertThrows(fn, Error);
  assertEquals(err.name, "Error");
}

Deno.test("missing title throws", () => {
  expectValidationError(() => {
    throw new Error("boom");
  });
});
""".strip())

        check = JavaScriptBogusTestsCheck({})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_additional_assert_functions_support_nonstandard_helpers(self, tmp_path):
        """Configured helper names should count as assertions."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "custom-helper.test.ts").write_text("""
function verifyValidationError(fn: () => unknown): void {
  const err = assertThrows(fn, Error);
  assertEquals(err.name, "Error");
}

Deno.test("configured helper passes", () => {
  verifyValidationError(() => {
    throw new Error("boom");
  });
});
""".strip())

        without_config = JavaScriptBogusTestsCheck({})
        without_result = without_config.run(str(tmp_path))
        assert without_result.status == CheckStatus.FAILED
        assert "no expect() or assertion calls found" in without_result.output

        with_config = JavaScriptBogusTestsCheck(
            {"additional_assert_functions": ["verifyValidationError"]}
        )
        with_result = with_config.run(str(tmp_path))

        assert with_result.status == CheckStatus.PASSED
