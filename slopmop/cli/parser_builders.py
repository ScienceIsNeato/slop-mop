"""Parser builders for agent-facing CLI flows.

Keeps higher-churn, workflow-oriented parser definitions out of the
main verb registry module.
"""

from __future__ import annotations

import argparse

from slopmop.agent_install.registry import (
    INSTALL_HELP_PREVIEW_ROOT,
    TARGETS,
    cli_choices,
    preview_install_paths,
)
from slopmop.constants import PROJECT_ROOT_HELP


class BuffParserBuilder:
    """Build the post-PR buff parser."""

    def __init__(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    ) -> None:
        self.subparsers = subparsers

    def build(self) -> None:
        """Register the buff parser."""
        buff_parser = self.subparsers.add_parser(
            "buff",
            help="Post-PR CI triage and next-step guidance",
            description=(
                "Run the post-submit buff rail. Default mode is CI code-scanning "
                "triage for the PR branch. Additional subcommands let agents "
                "check CI status, verify unresolved review threads, and resolve individual threads "
                "without dropping to raw GitHub plumbing."
            ),
        )
        self._add_mode_args(buff_parser)
        self._add_triage_args(buff_parser)
        self._add_output_args(buff_parser)
        self._add_resolution_args(buff_parser)

    @staticmethod
    def _add_mode_args(buff_parser: argparse.ArgumentParser) -> None:
        buff_parser.add_argument(
            "pr_or_action",
            nargs="?",
            default=None,
            help=(
                "PR number for normal inspect mode, or one of: inspect, iterate, "
                "finalize, verify, resolve, status, watch. Examples: 'sm buff 85', "
                "'sm buff inspect 85', 'sm buff iterate 85', "
                "'sm buff finalize 85 --push', 'sm buff verify 85', "
                "'sm buff resolve 85 PRRT_xxx --message ...', "
                "'sm buff status 85', 'sm buff watch 85'"
            ),
        )
        buff_parser.add_argument(
            "action_args",
            nargs="*",
            help=argparse.SUPPRESS,
        )

    @staticmethod
    def _add_triage_args(buff_parser: argparse.ArgumentParser) -> None:
        buff_parser.add_argument(
            "--interval",
            type=int,
            default=30,
            help="Polling interval in seconds for 'sm buff watch' (default: 30)",
        )
        buff_parser.add_argument(
            "--run-id",
            type=int,
            default=None,
            help="Explicit Actions run id for scan triage (overrides PR auto-detect)",
        )
        buff_parser.add_argument(
            "--repo",
            default=None,
            help="GitHub repo owner/name (defaults to current repo)",
        )
        buff_parser.add_argument(
            "--workflow",
            default="slop-mop primary code scanning gate",
            help="Workflow name used for CI scan triage",
        )
        buff_parser.add_argument(
            "--artifact",
            default="slopmop-results",
            help="Artifact name containing JSON scan results",
        )

    @staticmethod
    def _add_output_args(buff_parser: argparse.ArgumentParser) -> None:
        buff_parser.add_argument(
            "--json",
            dest="json_output",
            action="store_true",
            default=None,
            help="Output buff results as JSON.",
        )
        buff_parser.add_argument(
            "--no-json",
            dest="json_output",
            action="store_false",
            help="Force human-readable buff output.",
        )
        buff_parser.add_argument(
            "--output-file",
            "--output",
            "-o",
            dest="output_file",
            default=None,
            metavar="PATH",
            help=(
                "Write machine-readable buff payload to a file while preserving "
                "stdout output mode."
            ),
        )

    @staticmethod
    def _add_resolution_args(buff_parser: argparse.ArgumentParser) -> None:
        buff_parser.add_argument(
            "--scenario",
            default=None,
            help="Resolution scenario used by 'sm buff resolve'.",
        )
        buff_parser.add_argument(
            "--message",
            default=None,
            help="Comment body used by 'sm buff resolve'.",
        )
        buff_parser.add_argument(
            "--no-resolve",
            action="store_true",
            help="Post the comment but leave the thread unresolved.",
        )
        buff_parser.add_argument(
            "--push",
            action="store_true",
            help="Used by 'sm buff finalize' to push after final validation passes.",
        )


class AgentParserBuilder:
    """Build the agent template installer parser."""

    def __init__(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    ) -> None:
        self.subparsers = subparsers

    def build(self) -> None:
        """Register the agent parser."""
        agent_parser = self.subparsers.add_parser(
            "agent",
            help="Install agent integration templates",
            description=(
                "Install repo-local templates for AI coding agents so they discover "
                "and use the slop-mop swab/scour/buff workflow consistently."
            ),
        )
        agent_subparsers = agent_parser.add_subparsers(
            dest="agent_action",
            help="Agent action",
        )

        install_parser = agent_subparsers.add_parser(
            "install",
            help="Install template files for common agent runtimes",
            description=(
                "Install template files for common agent runtimes.\n\n"
                "Preview install destinations (using the help preview root "
                f"{INSTALL_HELP_PREVIEW_ROOT}):\n"
                f"{self._preview_install_summary()}"
            ),
            formatter_class=argparse.RawTextHelpFormatter,
        )
        install_parser.add_argument(
            "--target",
            choices=cli_choices(),
            default="all",
            help=(
                "Which agent templates to install. "
                "'all' installs cursor, claude, copilot, windsurf, cline, roo, and aider."
            ),
        )
        install_parser.add_argument(
            "--project-root",
            type=str,
            default=".",
            help=PROJECT_ROOT_HELP,
        )
        install_parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing files managed by this command.",
        )

    @staticmethod
    def _preview_install_summary() -> str:
        """Render deterministic preview install paths for help output."""
        lines: list[str] = []
        for key in sorted(TARGETS):
            lines.append(f"  {key}:")
            try:
                paths = preview_install_paths(key)
            except FileNotFoundError as exc:
                lines.append(f"    - unavailable ({exc})")
                continue
            for path in paths:
                lines.append(f"    - {path}")
        return "\n".join(lines)


class RefitParserBuilder:
    """Build the remediation refit parser."""

    def __init__(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    ) -> None:
        self.subparsers = subparsers

    def build(self) -> None:
        """Register the refit parser."""
        refit_parser = self.subparsers.add_parser(
            "refit",
            help="Structured remediation planning and continuation",
            description=(
                "Onboard a repository into slop-mop. Generate a one-gate-at-a-time "
                "remediation plan, iterate through it, and finish by transitioning "
                "to maintenance mode."
            ),
        )
        mode_group = refit_parser.add_mutually_exclusive_group(required=True)
        mode_group.add_argument(
            "--start",
            dest="start",
            action="store_true",
            help="Capture the current scour failure set and persist a refit plan.",
        )
        mode_group.add_argument(
            "--iterate",
            dest="iterate",
            action="store_true",
            help="Resume the persisted refit plan until the next blocker.",
        )
        mode_group.add_argument(
            "--finish",
            dest="finish",
            action="store_true",
            help="Check plan completion and transition from remediation to maintenance.",
        )
        refit_parser.add_argument(
            "--project-root",
            type=str,
            default=".",
            help=PROJECT_ROOT_HELP,
        )
        refit_parser.add_argument(
            "--json",
            dest="json_output",
            action="store_true",
            default=False,
            help="Output refit status as JSON.",
        )
        refit_parser.add_argument(
            "--output-file",
            "--output",
            "-o",
            dest="output_file",
            default=None,
            metavar="PATH",
            help=(
                "Write machine-readable refit status to a file while preserving "
                "stdout output mode."
            ),
        )
