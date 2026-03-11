"""Load template assets from package data."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from importlib.abc import Traversable
from typing import Iterator, List


@dataclass(frozen=True)
class TemplateAsset:
    """A single file to copy into the target repository."""

    destination_relpath: str
    content: bytes


def _templates_package() -> Traversable:
    return resources.files("slopmop.agent_install.templates")


def _walk(traversable: Traversable) -> Iterator[Traversable]:
    """Recursively yield all files under a Traversable."""
    for entry in traversable.iterdir():
        if entry.is_dir():
            yield from _walk(entry)
        else:
            yield entry


def iter_template_assets(template_dir: str) -> Iterator[TemplateAsset]:
    """Yield all files within a template directory.

    The destination path equals the file path relative to the template dir root.
    """
    base = _templates_package().joinpath(template_dir)
    if not base.is_dir():
        raise FileNotFoundError(f"Template directory not found: {template_dir}")

    base_str = str(base)
    for entry in _walk(base):
        if entry.is_dir():
            continue
        entry_str = str(entry)
        rel = entry_str[len(base_str) :].lstrip("/")
        yield TemplateAsset(
            destination_relpath=rel,
            content=entry.read_bytes(),
        )


def load_assets(template_dir: str) -> List[TemplateAsset]:
    """Load all assets for a template directory, sorted by destination."""
    assets = list(iter_template_assets(template_dir))
    assets.sort(key=lambda a: a.destination_relpath)
    return assets
