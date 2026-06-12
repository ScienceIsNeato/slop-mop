"""Parser builders for agent-facing CLI flows.

Keeps higher-churn, workflow-oriented parser definitions out of the
main verb registry module.
"""

from __future__ import annotations

import argparse
import sys

from slopmop.agent_install.registry import (
    INSTALL_HELP_HOME_PREVIEW_ROOT,
    INSTALL_HELP_PREVIEW_ROOT,
    TARGETS,
    cli_choices,
    preview_install_paths,
)
from slopmop.constants import PROJECT_ROOT_HELP


def try_suggest_config_command(message: str, flag_set: set[str]) -> bool:
    """Suggest correct config syntax if error message contains a config flag.

    Returns True if a suggestion was printed and error should exit, False otherwise.
    """
    words = message.lower().split()
    for flag in flag_set:
        if flag in words:
            print(f"\n❌ {message}")
            print("\n💡 Hint: Did you forget the '--' prefix?")
            print(f"   Try: sm config --{flag}")
            if flag == "set":
                print("        sm config --set <gate> <field> <value>")
            elif flag == "unset":
                print("        sm config --unset <gate> <field>")
            return True
    return False


def add_config_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the config subcommand parser."""
    config_parser = subparsers.add_parser(
        "config",
        help="View or update configuration",
        description="View or update quality gate configuration.",
    )

    # Store original error method
    original_error = config_parser.error

    # Custom error handler to catch common mistakes
    def config_error(message: str) -> None:
        """Custom error handler with helpful suggestions.

        When a suggestion is printed, exit directly instead of calling
        ``original_error``: argparse's handler would re-print the raw
        message plus a usage dump after our friendlier hint. Exit code 2
        matches what argparse itself uses for argument errors.
        """
        common_flags = {"enable", "disable", "set", "unset", "show", "json"}
        if try_suggest_config_command(message, common_flags):
            sys.exit(2)
        original_error(message)

    config_parser.error = config_error  # type: ignore[method-assign]

    config_parser.add_argument(
        "--show",
        action="store_true",
        help="Show current configuration and enabled gates",
    )
    config_parser.add_argument(
        "--enable",
        metavar="GATE",
        help="Enable a specific quality gate",
    )
    config_parser.add_argument(
        "--disable",
        metavar="GATE",
        help="Disable a specific quality gate",
    )
    config_parser.add_argument(
        "--json",
        metavar="FILE",
        help="Update configuration from JSON file",
    )
    config_parser.add_argument(
        "--swabbing-timeout",
        type=int,
        metavar="SECONDS",
        help="Set the swabbing-timeout budget (seconds). 0 or negative disables the limit.",
    )
    config_parser.add_argument(
        "--swabbing-time",
        type=int,
        metavar="SECONDS",
        dest="swabbing_timeout",
        help=argparse.SUPPRESS,  # deprecated alias for --swabbing-timeout
    )
    config_parser.add_argument(
        "--swab-off",
        metavar="GATE",
        help="Keep a gate out of swab while still running it during scour.",
    )
    config_parser.add_argument(
        "--swab-on",
        metavar="GATE",
        help="Make a gate run during both swab and scour.",
    )
    config_parser.add_argument(
        "--set",
        dest="set_field",
        nargs=3,
        metavar=("GATE", "FIELD", "VALUE"),
        help="Set gate config field: --set <gate> <field> <value> where gate is category:name (e.g., myopia:ignore-feedback)",
    )
    config_parser.add_argument(
        "--unset",
        dest="unset_field",
        nargs=2,
        metavar=("GATE", "FIELD"),
        help="Remove a gate-specific config field override.",
    )
    config_parser.add_argument(
        "--current-pr-number",
        type=int,
        metavar="PR",
        help="Set the working pull request number for buff commands.",
    )
    config_parser.add_argument(
        "--clear-current-pr",
        action="store_true",
        help="Clear the working pull request number.",
    )
    config_parser.add_argument(
        "--project-root",
        type=str,
        default=".",
        help=PROJECT_ROOT_HELP,
    )


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
            "--fail-fast",
            dest="fail_fast",
            action="store_true",
            default=False,
            help="Exit immediately on first CI failure, even if other checks are still pending.",
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
                "Install project and agent-home templates for AI coding agents so "
                "they discover and use the slop-mop swab/scour/buff workflow "
                "consistently."
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
                "Preview install destinations (using help preview roots "
                f"{INSTALL_HELP_PREVIEW_ROOT} for repo files and "
                f"{INSTALL_HELP_HOME_PREVIEW_ROOT} for user-home files):\n"
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
                "'all' installs all available agent targets."
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


class BarnacleParserBuilder:
    """Build the barnacle issue-filing parser."""

    def __init__(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    ) -> None:
        self.subparsers = subparsers

    @staticmethod
    def _add_file_args(parser: argparse.ArgumentParser) -> None:
        from slopmop.cli.barnacle import DEFAULT_REPO, HELP_AGENT  # noqa: PLC0415

        parser.add_argument("--title", help="Short issue title")
        parser.add_argument(
            "--command", required=True, help="Command that triggered the friction"
        )
        parser.add_argument("--gate", help="Gate name if the friction is gate-specific")
        parser.add_argument(
            "--expected", required=True, help="What should have happened"
        )
        parser.add_argument("--actual", required=True, help="What actually happened")
        parser.add_argument(
            "--output",
            dest="output_excerpt",
            help="Relevant terminal output excerpt",
        )
        parser.add_argument(
            "--repro-step",
            dest="reproduction_steps",
            action="append",
            help="Reproduction step; repeat for multiple steps",
        )
        parser.add_argument(
            "--tried",
            dest="things_tried",
            action="append",
            help="Thing already tried; repeat for multiple attempts",
        )
        parser.add_argument(
            "--workflow",
            choices=[
                "swab",
                "scour",
                "buff",
                "sail",
                "refit",
                "doctor",
                "upgrade",
                "install",
                "agent-skill",
                "unknown",
            ],
            default="unknown",
            help="Affected slop-mop workflow",
        )
        parser.add_argument(
            "--blocker-type",
            dest="blocker_type",
            choices=["blocking", "non-blocking"],
            default="blocking",
            help="Whether this barnacle blocks forward progress (default: blocking)",
        )
        parser.add_argument("--agent", help=HELP_AGENT)
        parser.add_argument(
            "--project-root", default=".", help="Root of the affected repository"
        )
        parser.add_argument(
            "--repo",
            default=DEFAULT_REPO,
            help=f"GitHub repo to file against (default: {DEFAULT_REPO})",
        )
        parser.add_argument(
            "--label",
            dest="labels",
            action="append",
            help="Issue label; defaults to barnacle + bug when omitted",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the issue title/body without creating a GitHub issue",
        )
        parser.add_argument(
            "--body-file",
            dest="body_file",
            help="Path for the generated Markdown body artifact",
        )
        parser.add_argument(
            "--json",
            dest="json_output",
            action="store_true",
            help="Emit machine-readable filing details",
        )

    def build(self) -> None:
        """Register the barnacle parser."""
        barnacle_parser = self.subparsers.add_parser(
            "barnacle",
            help="File upstream tool-friction issues",
            description=(
                "File a structured GitHub issue when slop-mop itself blocks or "
                "misguides work in a real repository. Barnacles are one-way "
                "upstream reports, not a local queue."
            ),
        )
        barnacle_sub = barnacle_parser.add_subparsers(
            dest="barnacle_action", help="Action to perform"
        )

        file_p = barnacle_sub.add_parser("file", help="File a barnacle GitHub issue")
        self._add_file_args(file_p)

        describe_p = barnacle_sub.add_parser(
            "describe",
            help="Deprecated alias for file",
            description="Deprecated alias for file",
        )
        self._add_file_args(describe_p)


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
        self._add_mode_args(refit_parser)
        refit_parser.add_argument(
            "--project-root",
            type=str,
            default=".",
            help=PROJECT_ROOT_HELP,
        )
        refit_parser.add_argument(
            "--approve-gate",
            action="append",
            default=[],
            metavar="GATE",
            help=(
                "With --start, record that a gate's current precheck output looks "
                "trustworthy and should be accepted for plan generation. Repeatable."
            ),
        )
        refit_parser.add_argument(
            "--record-blocker",
            dest="record_blocker",
            default=None,
            metavar="GATE",
            help=(
                "With --start, record that a disabled applicable gate remains off "
                "because of a slop-mop tooling blocker."
            ),
        )
        refit_parser.add_argument(
            "--blocker-issue",
            default=None,
            metavar="ISSUE",
            help="Bug/issue reference used with --record-blocker.",
        )
        refit_parser.add_argument(
            "--blocker-reason",
            default=None,
            metavar="TEXT",
            help="Short explanation used with --record-blocker.",
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

    @staticmethod
    def _add_mode_args(refit_parser: argparse.ArgumentParser) -> None:
        """Register the mutually-exclusive refit lifecycle modes."""
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
        mode_group.add_argument(
            "--skip",
            dest="skip",
            metavar="REASON",
            nargs="?",
            const="manual skip",
            default=None,
            help=(
                "Mark the current gate as skipped and advance the plan without "
                "running it. Optionally provide a reason. Skipped gates still "
                "block --finish; disable them in .sb_config.json to finish."
            ),
        )


class SchemaParserBuilder:
    """Build the schema parser (machine-interface self-description)."""

    def __init__(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    ) -> None:
        self.subparsers = subparsers

    def build(self) -> None:
        """Register the schema parser."""
        schema_parser = self.subparsers.add_parser(
            "schema",
            help="Print the machine-interface JSON Schema",
            description=(
                "Emit the slop-mop response envelope as a JSON Schema document, "
                "or — with a verb argument — that verb's full output schema. "
                "Self-description without execution: learn the exact response "
                "shape before running any command."
            ),
        )
        schema_parser.add_argument(
            "schema_verb",
            nargs="?",
            default=None,
            metavar="VERB",
            help="Optional verb whose full output schema to print (e.g. swab).",
        )


class CapabilitiesParserBuilder:
    """Build the capabilities parser (machine-interface discovery catalog)."""

    def __init__(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    ) -> None:
        self.subparsers = subparsers

    def build(self) -> None:
        """Register the capabilities parser."""
        capabilities_parser = self.subparsers.add_parser(
            "capabilities",
            help="Print the discovery catalog (version, verbs, gates)",
            description=(
                "Emit the discovery catalog: the installed slop-mop version, "
                "every verb with its output contract (group, formats, exit "
                "codes, data-schema reference), and every registered gate with "
                "its metadata and applicability to this project. Runs no gates "
                "— read this once to learn the entire surface."
            ),
        )
        capabilities_parser.add_argument(
            "--project-root",
            type=str,
            default=".",
            help=PROJECT_ROOT_HELP,
        )
