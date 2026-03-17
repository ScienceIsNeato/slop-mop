"""CLI command handlers for slop-mop.

This module contains the implementations of the various sm subcommands,
extracted from sm.py to keep files under the LOC limit.
"""

from slopmop.cli.agent import cmd_agent
from slopmop.cli.buff import cmd_buff
from slopmop.cli.config import cmd_config
from slopmop.cli.detection import detect_project_type
from slopmop.cli.help import cmd_help
from slopmop.cli.hooks import cmd_commit_hooks
from slopmop.cli.init import cmd_init
from slopmop.cli.scan_triage import run_triage
from slopmop.cli.status import cmd_status, run_status
from slopmop.cli.upgrade import cmd_upgrade
from slopmop.cli.validate import cmd_scour, cmd_swab

__all__ = [
    "cmd_agent",
    "cmd_commit_hooks",
    "cmd_config",
    "cmd_help",
    "cmd_init",
    "cmd_buff",
    "cmd_scour",
    "cmd_status",
    "cmd_swab",
    "cmd_upgrade",
    "detect_project_type",
    "run_triage",
    "run_status",
]
