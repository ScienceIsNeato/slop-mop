"""Upgrade the installed slop-mop package and validate the result."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, distribution, version
from pathlib import Path
from typing import Dict, List, Optional, TypedDict, cast

from packaging.version import InvalidVersion, Version

from slopmop.core.config import config_file_path, state_dir_path
from slopmop.migrations import planned_upgrade_migrations, run_upgrade_migrations

PACKAGE_NAME = "slopmop"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"
BACKUP_DIR_NAME = "backups"
VALIDATION_VERB = "scour"
STATE_BACKUP_FILES = (
    "cache.json",
    "timings.json",
    "current_pr.json",
    "last_swab.json",
    "last_scour.json",
    "baseline_snapshot.json",
)


class UpgradeError(RuntimeError):
    """Raised when the upgrade command cannot proceed safely."""


class DirectUrlDirInfo(TypedDict, total=False):
    editable: bool


class DirectUrlPayload(TypedDict, total=False):
    dir_info: DirectUrlDirInfo


class PypiInfo(TypedDict):
    version: str


class PypiResponse(TypedDict):
    info: PypiInfo


def _module_root() -> Path:
    import slopmop

    return Path(slopmop.__file__).resolve().parent.parent


def _running_from_source_checkout() -> bool:
    root = _module_root()
    return (root / "pyproject.toml").exists() and (root / ".git").exists()


def _installed_version() -> str:
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError as exc:
        raise UpgradeError(
            "slopmop is not installed in this Python environment."
        ) from exc


def _distribution_direct_url() -> Optional[DirectUrlPayload]:
    try:
        dist = distribution(PACKAGE_NAME)
    except PackageNotFoundError:
        return None
    raw = dist.read_text("direct_url.json")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return cast(DirectUrlPayload, parsed)


def _is_editable_install(direct_url: Optional[DirectUrlPayload] = None) -> bool:
    payload = direct_url if direct_url is not None else _distribution_direct_url()
    if not payload:
        return False
    dir_info = payload.get("dir_info")
    if isinstance(dir_info, dict) and bool(dir_info.get("editable", False)):
        return True
    return False


def _detect_install_type(
    *,
    executable: Optional[str] = None,
    prefix: Optional[str] = None,
    base_prefix: Optional[str] = None,
    virtual_env: Optional[str] = None,
    direct_url: Optional[DirectUrlPayload] = None,
) -> str:
    exe = (executable or sys.executable).replace("\\", "/")
    prefix_val = prefix or sys.prefix
    base_prefix_val = base_prefix or getattr(sys, "base_prefix", prefix_val)
    virtual_env_val = (
        virtual_env if virtual_env is not None else os.environ.get("VIRTUAL_ENV")
    )

    if _is_editable_install(direct_url):
        raise UpgradeError(
            "sm upgrade does not support editable/source-checkout installs yet. "
            "Use pipx or a non-editable virtualenv install."
        )

    if "/pipx/venvs/" in exe:
        return "pipx"

    if virtual_env_val or prefix_val != base_prefix_val:
        return "venv"

    raise UpgradeError(
        "sm upgrade currently supports pipx installs or pip installs inside an active virtual environment."
    )


def _validated_pypi_url() -> str:
    parsed = urllib.parse.urlparse(PYPI_URL)
    if parsed.scheme != "https" or parsed.netloc != "pypi.org":
        raise UpgradeError(f"Refusing to query unexpected PyPI URL: {PYPI_URL}")
    return parsed.geturl()


def _fetch_latest_pypi_version() -> str:
    try:
        safe_url = _validated_pypi_url()
        with urllib.request.urlopen(safe_url, timeout=5) as response:  # nosec B310
            payload = cast(PypiResponse, json.load(response))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise UpgradeError(
            f"Failed to fetch the latest {PACKAGE_NAME} version from PyPI."
        ) from exc

    latest = payload.get("info", {}).get("version")
    if not latest:
        raise UpgradeError(
            f"PyPI did not return a valid latest version for {PACKAGE_NAME}."
        )
    return latest


def _resolve_target_version(requested_version: Optional[str]) -> str:
    return requested_version or _fetch_latest_pypi_version()


def _validate_target_version(current_version: str, target_version: str) -> None:
    try:
        current = Version(current_version)
        target = Version(target_version)
    except InvalidVersion as exc:
        raise UpgradeError(f"Invalid version value: {exc}") from exc
    if target < current:
        raise UpgradeError(
            f"Refusing to downgrade from {current_version} to {target_version}."
        )


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _backup_dir(project_root: Path, stamp: Optional[str] = None) -> Path:
    return (
        state_dir_path(project_root)
        / BACKUP_DIR_NAME
        / f"upgrade_{stamp or _timestamp()}"
    )


def _backup_upgrade_state(
    project_root: Path,
    *,
    from_version: str,
    target_version: str,
    install_type: str,
) -> Path:
    backup_dir = _backup_dir(project_root)
    backup_dir.mkdir(parents=True, exist_ok=False)

    copied: List[str] = []
    config_path = config_file_path(project_root)
    if config_path.exists():
        destination = backup_dir / config_path.name
        shutil.copy2(config_path, destination)
        copied.append(destination.name)

    state_root = state_dir_path(project_root)
    for name in STATE_BACKUP_FILES:
        source = state_root / name
        if source.exists():
            destination = backup_dir / name
            shutil.copy2(source, destination)
            copied.append(destination.name)

    manifest: Dict[str, object] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "from_version": from_version,
        "target_version": target_version,
        "install_type": install_type,
        "copied_files": copied,
    }
    (backup_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return backup_dir


def _upgrade_command(install_type: str, target_version: str) -> List[str]:
    spec = f"{PACKAGE_NAME}=={target_version}"
    if install_type == "pipx":
        pipx = shutil.which("pipx")
        if not pipx:
            raise UpgradeError(
                "pipx is not available on PATH, so the pipx install cannot be upgraded."
            )
        return [pipx, "install", "--force", spec]
    if install_type == "venv":
        return [sys.executable, "-m", "pip", "install", spec]
    raise UpgradeError(f"Unsupported install type: {install_type}")


def _run_upgrade_install(install_type: str, target_version: str) -> None:
    command = _upgrade_command(install_type, target_version)
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        details = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or "upgrade command failed"
        )
        raise UpgradeError(f"Upgrade failed: {details}")


def _validate_upgraded_install(
    project_root: Path, verbose: bool
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-m",
        PACKAGE_NAME,
        VALIDATION_VERB,
        "--project-root",
        str(project_root),
    ]
    if verbose:
        command.append("--verbose")
    return subprocess.run(command, capture_output=True, text=True)


def _print_check_plan(
    *,
    install_type: str,
    current_version: str,
    target_version: str,
    project_root: Path,
) -> None:
    planned = planned_upgrade_migrations(current_version, target_version)
    print(f"Current version: {current_version}")
    print(f"Target version:  {target_version}")
    print(f"Install type:    {install_type}")
    print(f"Backup dir:      {_backup_dir(project_root, 'YYYYMMDD_HHMMSS')}")
    if planned:
        print(f"Migrations:      {', '.join(planned)}")
    else:
        print("Migrations:      none")
    print(f"Validation:      sm {VALIDATION_VERB}")


def cmd_upgrade(args: argparse.Namespace) -> int:
    """Upgrade the installed slop-mop package and validate the result."""
    project_root = Path(getattr(args, "project_root", ".")).resolve()
    if _running_from_source_checkout():
        print(
            "❌ sm upgrade must be run from an installed slopmop package, not from a source checkout.",
            file=sys.stderr,
        )
        return 1
    try:
        current_version = _installed_version()
        install_type = _detect_install_type()
        target_version = _resolve_target_version(getattr(args, "to_version", None))
        _validate_target_version(current_version, target_version)
    except UpgradeError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    if getattr(args, "check", False):
        _print_check_plan(
            install_type=install_type,
            current_version=current_version,
            target_version=target_version,
            project_root=project_root,
        )
        return 0

    if Version(target_version) == Version(current_version):
        print(f"slopmop is already at {current_version}; nothing to upgrade.")
        return 0

    try:
        backup_dir = _backup_upgrade_state(
            project_root,
            from_version=current_version,
            target_version=target_version,
            install_type=install_type,
        )
        _run_upgrade_install(install_type, target_version)
        installed_version = _installed_version()
        applied_migrations = run_upgrade_migrations(
            project_root, current_version, installed_version
        )
        validation = _validate_upgraded_install(
            project_root, getattr(args, "verbose", False)
        )
    except UpgradeError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    if validation.returncode != 0:
        print(
            f"❌ Upgrade installed {installed_version}, but validation failed. Backup: {backup_dir}",
            file=sys.stderr,
        )
        details = validation.stdout.strip() or validation.stderr.strip()
        if details:
            print(details, file=sys.stderr)
        return 1

    print(f"✅ Upgraded slopmop: {current_version} -> {installed_version}")
    print(f"📦 Backup: {backup_dir}")
    if applied_migrations:
        print(f"🔄 Migrations: {', '.join(applied_migrations)}")
    else:
        print("🔄 Migrations: none")
    print(f"✔️  Validation: sm {VALIDATION_VERB}")
    return 0
