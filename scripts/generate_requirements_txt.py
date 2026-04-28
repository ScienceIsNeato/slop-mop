"""Generate requirements.txt from pyproject.toml.

requirements.txt is a fallback install path and human-readable dependency
summary. pyproject.toml remains the single source of truth; this script renders
the subset of extras that matter for fallback installs and release validation.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path
from typing import Any

_HEADER = """# Slop-Mop Dependencies
#
# Generated from pyproject.toml by scripts/generate_requirements_txt.py.
# pyproject.toml is the single source of truth; this file exists as a fallback
# install path and a human-readable summary of the toolchain slop-mop expects.
#
# Install via: pip install -e .  (preferred)
#         or:  pip install -r requirements.txt  (fallback)
"""

_SECTIONS: list[tuple[str, str | None]] = [
    ("Core runtime", None),
    ("Static analysis", "analysis"),
    ("Linting and formatting", "lint"),
    ("Type checking", "typing"),
    ("Security scanning", "security"),
    ("Testing", "testing"),
    ("Templates (optional — only needed for the jinja2_templates gate)", "templates"),
]


def load_pyproject(pyproject_path: Path) -> dict[str, Any]:
    with pyproject_path.open("rb") as fh:
        return tomllib.load(fh)


def render_requirements(pyproject: dict[str, Any]) -> str:
    project = pyproject["project"]
    extras = project.get("optional-dependencies", {})
    runtime = project.get("dependencies", [])

    lines = [_HEADER.rstrip(), ""]
    for heading, extra_name in _SECTIONS:
        if extra_name is None:
            requirements = list(runtime)
        else:
            requirements = list(extras.get(extra_name, []))
        if not requirements:
            continue
        lines.append(f"# {heading}")
        lines.extend(requirements)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def parse_generate_requirements_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pyproject",
        default="pyproject.toml",
        help="Path to pyproject.toml",
    )
    parser.add_argument(
        "--output",
        default="requirements.txt",
        help="Path to requirements.txt",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the output file does not match the rendered content",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_generate_requirements_args(argv or sys.argv[1:])
    pyproject_path = Path(args.pyproject)
    output_path = Path(args.output)
    rendered = render_requirements(load_pyproject(pyproject_path))

    if args.check:
        existing = (
            output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        )
        if existing != rendered:
            print(
                f"{output_path} is out of sync with {pyproject_path}. "
                "Run scripts/generate_requirements_txt.py to refresh it.",
                file=sys.stderr,
            )
            return 1
        return 0

    output_path.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
