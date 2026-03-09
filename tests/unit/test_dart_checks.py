"""Tests for Dart/Flutter checks."""

from unittest.mock import MagicMock, patch

from slopmop.checks.dart.bogus_tests import DartBogusTestsCheck
from slopmop.checks.dart.coverage import DartCoverageCheck
from slopmop.checks.dart.generated_artifacts import DartGeneratedArtifactsCheck
from slopmop.core.result import CheckStatus


class TestDartCoverageCheck:
    """Tests for DartCoverageCheck."""

    def test_name(self):
        check = DartCoverageCheck({})
        assert check.name == "coverage-gaps.dart"
        assert check.full_name == "overconfidence:coverage-gaps.dart"

    def test_is_applicable_requires_test_dir(self, tmp_path):
        (tmp_path / "pubspec.yaml").write_text("name: app\n")
        check = DartCoverageCheck({})
        assert check.is_applicable(str(tmp_path)) is False

        (tmp_path / "test").mkdir()
        assert check.is_applicable(str(tmp_path)) is True

    def test_warns_when_flutter_missing(self, tmp_path):
        (tmp_path / "pubspec.yaml").write_text("name: app\n")
        (tmp_path / "test").mkdir()
        check = DartCoverageCheck({})

        with patch("slopmop.checks.dart.coverage.find_tool", return_value=None):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.WARNED

    def test_fails_when_flutter_test_fails(self, tmp_path):
        (tmp_path / "pubspec.yaml").write_text("name: app\n")
        (tmp_path / "test").mkdir()
        check = DartCoverageCheck({})

        run_result = MagicMock()
        run_result.success = False
        run_result.timed_out = False
        run_result.output = "test failure"

        with (
            patch("slopmop.checks.dart.coverage.find_tool", return_value="flutter"),
            patch.object(check, "_run_command", return_value=run_result),
        ):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "flutter test failed" in (result.error or "")

    def test_skips_on_flutter_sdk_cache_permission_error(self, tmp_path):
        (tmp_path / "pubspec.yaml").write_text("name: app\n")
        (tmp_path / "test").mkdir()
        check = DartCoverageCheck({})

        run_result = MagicMock()
        run_result.success = False
        run_result.timed_out = False
        run_result.output = (
            "/opt/homebrew/share/flutter/bin/internal/update_engine_version.sh: "
            "line 64: /opt/homebrew/share/flutter/bin/cache/engine.stamp: "
            "Operation not permitted"
        )

        with (
            patch("slopmop.checks.dart.coverage.find_tool", return_value="flutter"),
            patch.object(check, "_run_command", return_value=run_result),
        ):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.SKIPPED
        assert "not writable" in (result.output or "")

    def test_passes_when_coverage_meets_threshold(self, tmp_path):
        (tmp_path / "pubspec.yaml").write_text("name: app\n")
        (tmp_path / "test").mkdir()
        coverage_dir = tmp_path / "coverage"
        coverage_dir.mkdir()
        (coverage_dir / "lcov.info").write_text(
            "SF:lib/main.dart\n" "DA:1,1\n" "DA:2,1\n" "end_of_record\n"
        )
        check = DartCoverageCheck({"threshold": 80})

        run_result = MagicMock()
        run_result.success = True
        run_result.timed_out = False
        run_result.output = ""

        with (
            patch("slopmop.checks.dart.coverage.find_tool", return_value="flutter"),
            patch.object(check, "_run_command", return_value=run_result),
        ):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_fails_when_coverage_below_threshold(self, tmp_path):
        (tmp_path / "pubspec.yaml").write_text("name: app\n")
        (tmp_path / "test").mkdir()
        coverage_dir = tmp_path / "coverage"
        coverage_dir.mkdir()
        (coverage_dir / "lcov.info").write_text(
            "SF:lib/main.dart\n" "DA:1,1\n" "DA:2,0\n" "DA:3,0\n" "end_of_record\n"
        )
        check = DartCoverageCheck({"threshold": 80})

        run_result = MagicMock()
        run_result.success = True
        run_result.timed_out = False
        run_result.output = ""

        with (
            patch("slopmop.checks.dart.coverage.find_tool", return_value="flutter"),
            patch.object(check, "_run_command", return_value=run_result),
        ):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "below threshold" in (result.error or "")


class TestDartBogusTestsCheck:
    """Tests for DartBogusTestsCheck."""

    def test_name(self):
        check = DartBogusTestsCheck({})
        assert check.name == "bogus-tests.dart"
        assert check.full_name == "deceptiveness:bogus-tests.dart"

    def test_is_applicable(self, tmp_path):
        (tmp_path / "pubspec.yaml").write_text("name: app\n")
        (tmp_path / "test").mkdir()
        check = DartBogusTestsCheck({})
        assert check.is_applicable(str(tmp_path)) is False

        (tmp_path / "test" / "widget_test.dart").write_text(
            "import 'package:flutter_test/flutter_test.dart';\n"
            "void main() {\n"
            "  test('ok', () { expect(1, equals(2)); });\n"
            "}\n"
        )
        assert check.is_applicable(str(tmp_path)) is True

    def test_flags_empty_and_tautological_tests(self, tmp_path):
        (tmp_path / "pubspec.yaml").write_text("name: app\n")
        (tmp_path / "test").mkdir()
        (tmp_path / "test" / "sample_test.dart").write_text(
            "import 'package:flutter_test/flutter_test.dart';\n"
            "void main() {\n"
            "  test('empty', () {\n"
            "    // no-op\n"
            "  });\n"
            "  test('taut', () {\n"
            "    expect(true, isTrue);\n"
            "  });\n"
            "}\n"
        )
        check = DartBogusTestsCheck({})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "suspicious Dart test" in (result.output or "")

    def test_passes_with_real_assertions(self, tmp_path):
        (tmp_path / "pubspec.yaml").write_text("name: app\n")
        (tmp_path / "test").mkdir()
        (tmp_path / "test" / "sample_test.dart").write_text(
            "import 'package:flutter_test/flutter_test.dart';\n"
            "void main() {\n"
            "  test('real', () {\n"
            "    expect(1 + 1, equals(2));\n"
            "  });\n"
            "}\n"
        )
        check = DartBogusTestsCheck({})
        result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED


class TestDartGeneratedArtifactsCheck:
    """Tests for DartGeneratedArtifactsCheck."""

    def test_name(self):
        check = DartGeneratedArtifactsCheck({})
        assert check.name == "generated-artifacts.dart"
        assert check.full_name == "laziness:generated-artifacts.dart"

    def test_warns_when_git_ls_files_fails(self, tmp_path):
        (tmp_path / "pubspec.yaml").write_text("name: app\n")
        check = DartGeneratedArtifactsCheck({})

        git_result = MagicMock()
        git_result.success = False
        git_result.output = "fatal: not a git repo"

        with patch.object(check, "_run_command", return_value=git_result):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.WARNED

    def test_passes_when_no_generated_artifacts_tracked(self, tmp_path):
        (tmp_path / "pubspec.yaml").write_text("name: app\n")
        check = DartGeneratedArtifactsCheck({})

        git_result = MagicMock()
        git_result.success = True
        git_result.stdout = "lib/main.dart\ntest/sample_test.dart\n"

        with patch.object(check, "_run_command", return_value=git_result):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_fails_when_generated_artifacts_are_tracked(self, tmp_path):
        (tmp_path / "pubspec.yaml").write_text("name: app\n")
        check = DartGeneratedArtifactsCheck({})

        git_result = MagicMock()
        git_result.success = True
        git_result.stdout = (
            "ios/Flutter/ephemeral/flutter_lldb_helper.py\n"
            ".dart_tool/package_config.json\n"
            "lib/main.dart\n"
        )

        with patch.object(check, "_run_command", return_value=git_result):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED
        assert "generated artifact" in (result.error or "")
