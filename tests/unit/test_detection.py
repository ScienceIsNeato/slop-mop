"""Tests for slopmop.cli.detection — project-type detection logic."""

import json
from unittest.mock import MagicMock, patch

import pytest

from slopmop.cli.detection import _normalize_language_key, detect_project_type


class TestDetectProjectType:
    """Tests for detect_project_type function."""

    @pytest.fixture(autouse=True)
    def _disable_scc_by_default(self):
        """Keep legacy marker-based tests deterministic."""
        with patch(
            "slopmop.cli.detection._detect_languages_with_scc", return_value=None
        ):
            yield

    def test_detects_python_project_from_pyproject(self, tmp_path):
        """Detects Python from pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text("[tool.pytest]")
        result = detect_project_type(tmp_path)
        assert result["has_python"] is True
        assert result["has_pytest"] is True

    def test_detects_python_project_from_requirements(self, tmp_path):
        """Detects Python from requirements.txt."""
        (tmp_path / "requirements.txt").write_text("flask==2.0")
        result = detect_project_type(tmp_path)
        assert result["has_python"] is True

    def test_detects_javascript_project(self, tmp_path):
        """Detects JavaScript from package.json."""
        (tmp_path / "package.json").write_text("{}")
        result = detect_project_type(tmp_path)
        assert result["has_javascript"] is True

    def test_detects_jest(self, tmp_path):
        """Detects Jest from package.json devDependencies."""
        pkg = {"devDependencies": {"jest": "^29.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        result = detect_project_type(tmp_path)
        assert result["has_jest"] is True

    def test_detects_jest_from_nested_package_json(self, tmp_path):
        """Detects Jest from nested package.json in monorepo layouts."""
        pkg = {"devDependencies": {"jest": "^29.0.0"}}
        (tmp_path / "client").mkdir()
        (tmp_path / "client" / "package.json").write_text(json.dumps(pkg))
        result = detect_project_type(tmp_path)
        assert result["has_jest"] is True

    def test_detects_test_directories(self, tmp_path):
        """Detects test directories."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_foo.py").write_text("")
        result = detect_project_type(tmp_path)
        assert result["has_tests_dir"] is True
        assert "tests" in result["test_dirs"]

    def test_detects_nested_test_directories(self, tmp_path):
        """Detects nested test directories in monorepo layouts."""
        (tmp_path / "server" / "tests").mkdir(parents=True)
        (tmp_path / "server" / "tests" / "test_api.py").write_text("")
        (tmp_path / "client" / "test").mkdir(parents=True)
        (tmp_path / "client" / "test" / "app.test.js").write_text("")
        result = detect_project_type(tmp_path)
        assert result["has_tests_dir"] is True
        assert "server/tests" in result["test_dirs"]
        assert "client/test" in result["test_dirs"]

    def test_ignores_test_directories_in_excluded_paths(self, tmp_path):
        """Does not count node_modules test directories."""
        (tmp_path / "node_modules" / "foo" / "tests").mkdir(parents=True)
        (tmp_path / "node_modules" / "foo" / "tests" / "x.js").write_text("")
        result = detect_project_type(tmp_path)
        assert result["has_tests_dir"] is False
        assert result["test_dirs"] == []

    def test_ignores_test_directories_without_source_files(self, tmp_path):
        """A directory *named* test with no test sources isn't a test dir.

        Observed against manim: renderer/shaders/test/ holds only .glsl
        shader assets. sm init pointed coverage gates at it.
        """
        shader_test = tmp_path / "renderer" / "shaders" / "test"
        shader_test.mkdir(parents=True)
        (shader_test / "vertex.glsl").write_text("void main() {}")
        (shader_test / "fragment.glsl").write_text("void main() {}")
        # And a real test dir that should still be found
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_real.py").write_text("")

        result = detect_project_type(tmp_path)
        assert "tests" in result["test_dirs"]
        assert "renderer/shaders/test" not in result["test_dirs"]

    def test_detects_test_directory_with_nested_sources(self, tmp_path):
        """test/unit/test_foo.py layout should still be detected."""
        (tmp_path / "test" / "unit").mkdir(parents=True)
        (tmp_path / "test" / "unit" / "test_foo.py").write_text("")
        result = detect_project_type(tmp_path)
        assert "test" in result["test_dirs"]

    def test_detects_pytest_from_nested_config(self, tmp_path):
        """Detects pytest from nested pytest.ini."""
        (tmp_path / "server").mkdir()
        (tmp_path / "server" / "pytest.ini").write_text("[pytest]\n")
        result = detect_project_type(tmp_path)
        assert result["has_pytest"] is True

    def test_recommends_gates_for_python(self, tmp_path):
        """Recommends appropriate gates for Python-only projects."""
        (tmp_path / "setup.py").write_text("")
        result = detect_project_type(tmp_path)
        assert "recommended_gates" in result

    def test_recommends_gates_for_mixed(self, tmp_path):
        """Recommends appropriate gates for mixed Python/JS projects."""
        (tmp_path / "setup.py").write_text("")
        (tmp_path / "package.json").write_text("{}")
        result = detect_project_type(tmp_path)
        assert "recommended_gates" in result

    def test_detects_typescript_from_tsconfig(self, tmp_path):
        """Detects TypeScript from tsconfig.json."""
        (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {}}')
        result = detect_project_type(tmp_path)
        assert result["has_typescript"] is True
        assert result["has_javascript"] is True  # TS implies JS

    def test_detects_typescript_from_ci_config(self, tmp_path):
        """Detects TypeScript from tsconfig.ci.json."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.ci.json").write_text('{"compilerOptions": {}}')
        result = detect_project_type(tmp_path)
        assert result["has_typescript"] is True

    def test_typescript_recommends_types_gate(self, tmp_path):
        """TypeScript projects recommend type-blindness.js gate."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {}}')
        result = detect_project_type(tmp_path)
        assert "overconfidence:type-blindness.js" in result["recommended_gates"]

    def test_prefers_scc_detection_when_available(self, tmp_path):
        """scc output should drive language flags when available."""
        with patch(
            "slopmop.cli.detection._detect_languages_with_scc",
            return_value={"typescript"},
        ):
            result = detect_project_type(tmp_path)

        assert result["language_detector"] == "scc"
        assert result["has_typescript"] is True
        assert result["has_javascript"] is True  # TS implies JS
        assert "overconfidence:type-blindness.js" in result["recommended_gates"]

    def test_empty_scc_result_falls_back_to_manifest_detection(self, tmp_path):
        """Empty scc output should not suppress manifest-based language detection."""
        (tmp_path / "pyproject.toml").write_text("[tool.pytest]\n")
        mock_scc = MagicMock(returncode=0, stdout="{}")
        with (
            patch("slopmop.cli.detection.find_tool", return_value="/usr/bin/scc"),
            patch("subprocess.run", return_value=mock_scc),
        ):
            result = detect_project_type(tmp_path)

        assert result["language_detector"] == "manifest"
        assert result["has_python"] is True

    def test_normalize_language_key_handles_cplusplus_header(self):
        """Normalization should preserve C++ semantics in keys."""
        assert _normalize_language_key("C++ Header") == "cplusplusheader"

    def test_dart_detection_suggests_flutter_custom_gates(self, tmp_path):
        """Dart repos should get first-class Flutter gates, not custom shells."""
        with (
            patch(
                "slopmop.cli.detection._detect_languages_with_scc",
                return_value={"dart"},
            ),
            patch(
                "slopmop.cli.detection.find_tool",
                side_effect=lambda name, _root: f"/usr/bin/{name}",
            ),
        ):
            result = detect_project_type(tmp_path)

        assert result["has_dart"] is True
        assert result["suggested_custom_gates"] == []
        assert "overconfidence:missing-annotations.dart" in result["recommended_gates"]
        assert "overconfidence:untested-code.dart" in result["recommended_gates"]
        assert "laziness:sloppy-formatting.dart" in result["recommended_gates"]
        assert "overconfidence:coverage-gaps.dart" in result["recommended_gates"]
        assert "deceptiveness:bogus-tests.dart" in result["recommended_gates"]
        assert "laziness:generated-artifacts.dart" in result["recommended_gates"]

    def test_dart_detection_omits_flutter_custom_gates_when_tools_missing(
        self, tmp_path
    ):
        """Dart still gets first-class recommendations and missing-tool mapping."""
        with (
            patch(
                "slopmop.cli.detection._detect_languages_with_scc",
                return_value={"dart"},
            ),
            patch("slopmop.cli.detection.find_tool", return_value=None),
        ):
            result = detect_project_type(tmp_path)

        assert result["has_dart"] is True
        assert result["suggested_custom_gates"] == []
        assert "overconfidence:missing-annotations.dart" in result["recommended_gates"]
        assert "overconfidence:untested-code.dart" in result["recommended_gates"]
        assert "laziness:sloppy-formatting.dart" in result["recommended_gates"]
        assert "overconfidence:coverage-gaps.dart" in result["recommended_gates"]
        assert (
            "flutter",
            "overconfidence:missing-annotations.dart",
            "Install Flutter SDK: https://docs.flutter.dev/get-started/install",
        ) in result["missing_tools"]
        assert (
            "flutter",
            "overconfidence:untested-code.dart",
            "Install Flutter SDK: https://docs.flutter.dev/get-started/install",
        ) in result["missing_tools"]
        assert (
            "dart",
            "laziness:sloppy-formatting.dart",
            "Install Dart SDK: https://dart.dev/get-dart",
        ) in result["missing_tools"]
