"""CLI command handlers for slop-mop.

This package stays intentionally light at import time so parser creation and
other read-only surfaces do not eagerly import the entire command tree.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from slopmop.cli.agent import cmd_agent
    from slopmop.cli.buff import cmd_buff
    from slopmop.cli.config import cmd_config
    from slopmop.cli.detection import detect_project_type
    from slopmop.cli.doctor import cmd_doctor
    from slopmop.cli.help import cmd_help
    from slopmop.cli.hooks import cmd_commit_hooks
    from slopmop.cli.init import cmd_init
    from slopmop.cli.refit import cmd_refit
    from slopmop.cli.sail import cmd_sail
    from slopmop.cli.scan_triage import run_triage
    from slopmop.cli.status import cmd_status, run_status
    from slopmop.cli.upgrade import cmd_upgrade
    from slopmop.cli.validate import cmd_scour, cmd_swab

_EXPORT_MAP = {
    "cmd_agent": ("slopmop.cli.agent", "cmd_agent"),
    "cmd_buff": ("slopmop.cli.buff", "cmd_buff"),
    "cmd_commit_hooks": ("slopmop.cli.hooks", "cmd_commit_hooks"),
    "cmd_config": ("slopmop.cli.config", "cmd_config"),
    "cmd_doctor": ("slopmop.cli.doctor", "cmd_doctor"),
    "cmd_help": ("slopmop.cli.help", "cmd_help"),
    "cmd_init": ("slopmop.cli.init", "cmd_init"),
    "cmd_refit": ("slopmop.cli.refit", "cmd_refit"),
    "cmd_sail": ("slopmop.cli.sail", "cmd_sail"),
    "cmd_scour": ("slopmop.cli.validate", "cmd_scour"),
    "cmd_status": ("slopmop.cli.status", "cmd_status"),
    "cmd_swab": ("slopmop.cli.validate", "cmd_swab"),
    "cmd_upgrade": ("slopmop.cli.upgrade", "cmd_upgrade"),
    "detect_project_type": ("slopmop.cli.detection", "detect_project_type"),
    "run_status": ("slopmop.cli.status", "run_status"),
    "run_triage": ("slopmop.cli.scan_triage", "run_triage"),
}


def __getattr__(name: str) -> Any:
    """Lazily resolve command handlers to avoid eager import cycles."""
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


__all__ = [
    "cmd_agent",
    "cmd_commit_hooks",
    "cmd_config",
    "cmd_doctor",
    "cmd_help",
    "cmd_init",
    "cmd_buff",
    "cmd_refit",
    "cmd_sail",
    "cmd_scour",
    "cmd_status",
    "cmd_swab",
    "cmd_upgrade",
    "detect_project_type",
    "run_triage",
    "run_status",
]
