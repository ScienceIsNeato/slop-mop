"""Load template assets from package data."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from importlib import resources

if sys.version_info >= (3, 11):
    from importlib.resources.abc import Traversable
else:
    from importlib.abc import Traversable  # type: ignore[no-redef]

from typing import Iterator, List

_CORE_PLACEHOLDER = b"{{CORE}}"


@dataclass(frozen=True)
class TemplateAsset:
    """A single file to copy into the target repository."""

    destination_relpath: str
    content: bytes


def _templates_package() -> Traversable:
    return resources.files("slopmop.agent_install").joinpath("templates")


def _load_shared_core() -> bytes:
    """Load the shared core.md content once."""
    core = _templates_package().joinpath("_shared").joinpath("core.md")
    return core.read_bytes()


def _walk(traversable: Traversable) -> Iterator[Traversable]:
    """Recursively yield all files under a Traversable."""
    for entry in traversable.iterdir():
        if entry.is_dir():
            yield from _walk(entry)
        else:
            yield entry


def iter_template_assets(template_dir: str) -> Iterator[TemplateAsset]:
    """Yield all files within a template directory.

    Files containing ``{{CORE}}`` get the shared core.md content
    substituted in at load time.
    """
    base = _templates_package().joinpath(template_dir)
    if not base.is_dir():
        raise FileNotFoundError(f"Template directory not found: {template_dir}")

    core: bytes | None = None
    base_str = str(base)
    for entry in _walk(base):
        if entry.is_dir():
            continue
        entry_str = str(entry)
        rel = entry_str[len(base_str) :].lstrip("/")
        raw = entry.read_bytes()
        if _CORE_PLACEHOLDER in raw:
            if core is None:
                core = _load_shared_core()
            raw = raw.replace(_CORE_PLACEHOLDER, core.rstrip())
        yield TemplateAsset(
            destination_relpath=rel,
            content=raw,
        )


def load_assets(template_dir: str) -> List[TemplateAsset]:
    """Load all assets for a template directory, sorted by destination."""
    assets = list(iter_template_assets(template_dir))
    assets.sort(key=lambda a: a.destination_relpath)
    return assets
