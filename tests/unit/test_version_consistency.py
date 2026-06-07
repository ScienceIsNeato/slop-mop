"""Guard tests: the version must never drift from slopmop/_version.py.

slopmop/_version.py is the single source of truth. These tests fail CI if the
package, pyproject, or any version-bearing doc disagrees with it — so a
mismatch can never be merged. The set of managed doc targets lives in
scripts/sync_version.py (imported here so there is one definition, not two).
"""

import importlib.util
import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on py310
    import tomli as tomllib  # type: ignore[no-redef]

import slopmop
from slopmop._version import __version__ as SOURCE_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_sync_module():
    path = REPO_ROOT / "scripts" / "sync_version.py"
    spec = importlib.util.spec_from_file_location("sync_version", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses can resolve annotations against the
    # module (sys.modules.get(cls.__module__) must not be None).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_source_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", SOURCE_VERSION), SOURCE_VERSION


def test_package_version_matches_source():
    assert slopmop.__version__ == SOURCE_VERSION


def test_pyproject_does_not_hardcode_version():
    """pyproject must derive the version dynamically, not pin its own literal."""
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in data["project"], (
        "pyproject.toml hardcodes a version; it must use "
        "dynamic = ['version'] reading slopmop/_version.py"
    )
    assert "version" in data["project"].get("dynamic", [])
    attr = data["tool"]["setuptools"]["dynamic"]["version"]["attr"]
    assert attr == "slopmop._version.__version__", attr


def test_docs_are_in_sync_with_source():
    """Every managed doc states exactly the source version (no drift)."""
    sync = _load_sync_module()
    version, problems = sync.check()
    assert version == SOURCE_VERSION
    assert not problems, "version drift detected:\n  " + "\n  ".join(problems)
