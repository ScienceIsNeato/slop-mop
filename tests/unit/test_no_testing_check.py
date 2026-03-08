"""Tests for overconfidence:literally-no-testing."""

from slopmop.checks.quality.no_testing import NoTestingCheck
from slopmop.core.result import CheckStatus


def _run(tmp_path, config=None):
    return NoTestingCheck(config or {}).run(str(tmp_path))


class TestBasics:
    def test_name_and_full_name(self):
        check = NoTestingCheck({})
        assert check.name == "literally-no-testing"
        assert check.full_name == "overconfidence:literally-no-testing"

    def test_not_applicable_without_source(self, tmp_path):
        (tmp_path / "README.md").write_text("# docs only\n")
        check = NoTestingCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_skips_without_source(self, tmp_path):
        (tmp_path / "README.md").write_text("# docs only\n")
        result = _run(tmp_path)
        assert result.status == CheckStatus.SKIPPED


class TestDetection:
    def test_fails_when_source_exists_without_tests(self, tmp_path):
        (tmp_path / "app.py").write_text("print('hi')\n")
        result = _run(tmp_path)
        assert result.status == CheckStatus.FAILED
        assert "no test" in (result.error or "").lower()

    def test_passes_with_test_file_pattern(self, tmp_path):
        (tmp_path / "app.py").write_text("print('hi')\n")
        (tmp_path / "test_app.py").write_text("def test_ok():\n    assert True\n")
        result = _run(tmp_path)
        assert result.status == CheckStatus.PASSED

    def test_passes_with_tests_directory_signal(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.ts").write_text("export const x = 1;\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "smoke.ts").write_text("it('ok', () => {})\n")
        result = _run(tmp_path)
        assert result.status == CheckStatus.PASSED

    def test_passes_with_test_config_file(self, tmp_path):
        (tmp_path / "app.py").write_text("print('hi')\n")
        (tmp_path / "pytest.ini").write_text("[pytest]\n")
        result = _run(tmp_path)
        assert result.status == CheckStatus.PASSED

    def test_ignores_excluded_dirs(self, tmp_path):
        (tmp_path / "app.py").write_text("print('hi')\n")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "test_foo.py").write_text(
            "def test_fake():\n    assert True\n"
        )
        result = _run(tmp_path)
        assert result.status == CheckStatus.FAILED

    def test_honors_custom_exclude_dirs(self, tmp_path):
        (tmp_path / "app.py").write_text("print('hi')\n")
        (tmp_path / "generated-tests").mkdir()
        (tmp_path / "generated-tests" / "test_auto.py").write_text(
            "def test_fake():\n    assert True\n"
        )
        result = _run(tmp_path, {"exclude_dirs": ["generated-tests"]})
        assert result.status == CheckStatus.FAILED


class TestLimits:
    def test_warns_when_file_limit_hit(self, tmp_path):
        (tmp_path / "a.py").write_text("print('a')\n")
        (tmp_path / "b.py").write_text("print('b')\n")
        result = _run(tmp_path, {"max_files": 1})
        assert result.status == CheckStatus.WARNED
        assert "stopped" in (result.output or "").lower()
