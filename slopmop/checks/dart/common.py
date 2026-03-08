"""Shared helpers for Dart/Flutter checks."""

from pathlib import Path
from typing import Iterable, List

NO_PUBSPEC_FOUND = "No pubspec.yaml found"
VERIFY_WITH_PREFIX = "Verify with: "


def find_pubspec_dirs(project_root: str) -> List[Path]:
    """Return package directories containing pubspec.yaml.

    Hidden directories are ignored to avoid tooling/cache artifacts.
    """
    root = Path(project_root)
    dirs: List[Path] = []
    for pubspec in root.rglob("pubspec.yaml"):
        try:
            rel_parts = pubspec.relative_to(root).parts
        except ValueError:
            continue
        if any(part.startswith(".") for part in rel_parts):
            continue
        dirs.append(pubspec.parent)
    return sorted(set(dirs))


def has_dart_project(project_root: str) -> bool:
    """Return True when at least one Dart package is present."""
    return bool(find_pubspec_dirs(project_root))


def find_dart_test_files(project_root: str) -> List[Path]:
    """Return Dart test files across all discovered package roots."""
    files: List[Path] = []
    for package_dir in find_pubspec_dirs(project_root):
        test_dir = package_dir / "test"
        if not test_dir.is_dir():
            continue
        files.extend(sorted(test_dir.rglob("*_test.dart")))
    return files


def unique_strings(values: Iterable[str]) -> List[str]:
    """Deduplicate strings while preserving order."""
    seen: set[str] = set()
    out: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
