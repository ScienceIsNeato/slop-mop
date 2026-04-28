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
