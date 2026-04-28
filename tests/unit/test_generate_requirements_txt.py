"""Regression coverage for requirements.txt generation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "generate_requirements_txt.py"
)
_SPEC = importlib.util.spec_from_file_location("generate_requirements_txt", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_rendered_requirements_matches_repo_file() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    pyproject = _MODULE.load_pyproject(repo_root / "pyproject.toml")
    rendered = _MODULE.render_requirements(pyproject)
    requirements = (repo_root / "requirements.txt").read_text(encoding="utf-8")

    assert rendered == requirements


def test_rendered_requirements_includes_runtime_and_optional_sections() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    pyproject = _MODULE.load_pyproject(repo_root / "pyproject.toml")
    rendered = _MODULE.render_requirements(pyproject)

    assert "# Core runtime" in rendered
    assert "tomli>=1.0.0; python_version < '3.11'" in rendered
    assert "# Static analysis" in rendered
    assert "radon>=5.1.0" in rendered
    assert "# Templates (optional" in rendered
    assert "jinja2>=3.0.0" in rendered


def test_main_writes_requirements_file(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    output = tmp_path / "requirements.txt"
    pyproject.write_text(
        "[project]\n"
        "dependencies = ['tomli>=1.0.0']\n"
        "[project.optional-dependencies]\n"
        "testing = ['pytest>=9']\n",
        encoding="utf-8",
    )

    result = _MODULE.main(["--pyproject", str(pyproject), "--output", str(output)])

    assert result == 0
    assert "tomli>=1.0.0" in output.read_text(encoding="utf-8")


def test_main_check_reports_out_of_sync(tmp_path: Path, capsys) -> None:
    pyproject = tmp_path / "pyproject.toml"
    output = tmp_path / "requirements.txt"
    pyproject.write_text(
        "[project]\n" "dependencies = ['tomli>=1.0.0']\n",
        encoding="utf-8",
    )
    output.write_text("stale\n", encoding="utf-8")

    result = _MODULE.main(
        ["--pyproject", str(pyproject), "--output", str(output), "--check"]
    )

    assert result == 1
    assert "out of sync" in capsys.readouterr().err


def test_main_check_passes_when_output_matches(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    output = tmp_path / "requirements.txt"
    pyproject.write_text(
        "[project]\n" "dependencies = ['tomli>=1.0.0']\n",
        encoding="utf-8",
    )
    output.write_text(
        _MODULE.render_requirements(_MODULE.load_pyproject(pyproject)),
        encoding="utf-8",
    )

    assert (
        _MODULE.main(
            ["--pyproject", str(pyproject), "--output", str(output), "--check"]
        )
        == 0
    )
