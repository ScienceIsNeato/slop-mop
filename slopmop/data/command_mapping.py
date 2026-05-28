"""Command mapping: forbidden instinct commands → sm equivalents.

Single source of truth for ``sm gang``.  This table drives:

  - Shell function generation in ``~/.slopmop/aliases.sh``
  - The ``sm gang list`` display table
  - Agent context in ``_shared/core.md`` (kept in sync manually)

``intercept_type`` values:

  ``"function"``    Wrap the top-level command by name.
  ``"subcommand"``  Contribute a ``case`` arm inside a shared wrapper function
                    for ``wrapper_command`` (e.g. ``gh``).
  ``"npx"``         Contribute a ``case`` arm inside the ``npx()`` wrapper.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_CAT_TEST_COV = "test / coverage"
_REASON_BUFF_RUN = "sm buff watch <PR> is the structured CI triage rail — not gh run"
_SUGG_BUFF_RUN = "sm buff watch <PR#>  or  sm buff status to find your PR"
_REASON_FMT = "sm swab runs formatting gates in the correct pipeline context"
_SM_FMT = "sm swab -g laziness:sloppy-formatting.py"


@dataclass(frozen=True)
class CommandMap:
    """One forbidden-command → sm-command mapping entry."""

    forbidden: str
    """Human display name, e.g. ``'pytest'`` or ``'gh run list'``."""

    sm_command: str
    """Replacement sm command string.  Empty string for block-only entries."""

    reason: str
    """One-line explanation shown in the intercept message."""

    category: str
    """Display category for ``sm gang list``."""

    intercept_type: str
    """``'function'`` | ``'subcommand'`` | ``'npx'``."""

    wrapper_command: str = ""
    """Parent command for ``subcommand``/``npx`` types (e.g. ``'gh'``, ``'npx'``)."""

    subcommands: tuple[str, ...] = field(default_factory=tuple)
    """Subcommand tokens to match (e.g. ``('run', 'list')`` for ``gh run list``)."""

    flag_trigger: str = ""
    """If non-empty: only intercept when this flag appears in ``$*`` (e.g. ``'--cov'``)."""

    redirect: bool = True
    """``True`` = run ``sm_command``; ``False`` = block with message and suggest."""

    suggestion: str = ""
    """For block-only entries: the ``Use:`` line shown after the intercept message."""


COMMAND_MAPPING: list[CommandMap] = [
    # ── Test runners ─────────────────────────────────────────────────────────
    CommandMap(
        forbidden="pytest --cov",
        sm_command="sm scour",
        reason="sm scour runs coverage gates with diff-aware analysis",
        category=_CAT_TEST_COV,
        intercept_type="function",
        flag_trigger="--cov",
    ),
    CommandMap(
        forbidden="pytest",
        sm_command="sm swab",
        reason="sm swab runs all gates with correct state tracking and caching",
        category=_CAT_TEST_COV,
        intercept_type="function",
    ),
    # ── CI monitoring: gh run ────────────────────────────────────────────────
    CommandMap(
        forbidden="gh run list",
        sm_command="",
        reason=_REASON_BUFF_RUN,
        category="CI monitoring",
        intercept_type="subcommand",
        wrapper_command="gh",
        subcommands=("run", "list"),
        redirect=False,
        suggestion=_SUGG_BUFF_RUN,
    ),
    CommandMap(
        forbidden="gh run watch",
        sm_command="",
        reason=_REASON_BUFF_RUN,
        category="CI monitoring",
        intercept_type="subcommand",
        wrapper_command="gh",
        subcommands=("run", "watch"),
        redirect=False,
        suggestion=_SUGG_BUFF_RUN,
    ),
    CommandMap(
        forbidden="gh run view",
        sm_command="",
        reason=_REASON_BUFF_RUN,
        category="CI monitoring",
        intercept_type="subcommand",
        wrapper_command="gh",
        subcommands=("run", "view"),
        redirect=False,
        suggestion=_SUGG_BUFF_RUN,
    ),
    # ── PR triage: gh pr / gh api ────────────────────────────────────────────
    CommandMap(
        forbidden="gh pr checks",
        sm_command="",
        reason="sm buff status <PR> gives structured CI + PR state",
        category="PR triage",
        intercept_type="subcommand",
        wrapper_command="gh",
        subcommands=("pr", "checks"),
        redirect=False,
        suggestion="sm buff status <PR#>  or  sm buff inspect <PR#> for comments",
    ),
    CommandMap(
        forbidden="gh api graphql",
        sm_command="",
        reason="sm buff resolve <PR> <THREAD_ID> is the thread resolution rail",
        category="PR triage",
        intercept_type="subcommand",
        wrapper_command="gh",
        subcommands=("api", "graphql"),
        redirect=False,
        suggestion="sm buff resolve <PR#> <THREAD_ID> --scenario <type>",
    ),
    CommandMap(
        forbidden="gh pr merge",
        sm_command="",
        reason="sail mode stops at PR_READY; human decision to merge is required",
        category="PR triage",
        intercept_type="subcommand",
        wrapper_command="gh",
        subcommands=("pr", "merge"),
        redirect=False,
        suggestion="⛵ SAILING_NEEDS_HUMAN — PR is ready. Share with human for merge decision.",
    ),
    # ── Python formatting / linting ───────────────────────────────────────────
    CommandMap(
        forbidden="black",
        sm_command=_SM_FMT,
        reason=_REASON_FMT,
        category="formatting",
        intercept_type="function",
    ),
    CommandMap(
        forbidden="isort",
        sm_command=_SM_FMT,
        reason=_REASON_FMT,
        category="formatting",
        intercept_type="function",
    ),
    CommandMap(
        forbidden="flake8",
        sm_command=_SM_FMT,
        reason=_REASON_FMT,
        category="formatting",
        intercept_type="function",
    ),
    # ── Python type checking ──────────────────────────────────────────────────
    CommandMap(
        forbidden="mypy",
        sm_command="sm swab -g overconfidence:missing-annotations.py",
        reason="sm swab runs type checks with correct project configuration",
        category="type checking",
        intercept_type="function",
    ),
    CommandMap(
        forbidden="pyright",
        sm_command="sm swab -g overconfidence:type-blindness.py",
        reason="sm swab runs type checks with correct project configuration",
        category="type checking",
        intercept_type="function",
    ),
    # ── Python security / deps ────────────────────────────────────────────────
    CommandMap(
        forbidden="bandit",
        sm_command="sm swab -g myopia:vulnerability-blindness.py",
        reason="sm swab runs security scans with correct scope and reporting",
        category="security",
        intercept_type="function",
    ),
    CommandMap(
        forbidden="semgrep",
        sm_command="sm swab -g myopia:vulnerability-blindness.py",
        reason="sm swab runs security scans with correct scope and reporting",
        category="security",
        intercept_type="function",
    ),
    CommandMap(
        forbidden="pip-audit",
        sm_command="sm swab -g myopia:dependency-risk.py",
        reason="sm swab runs dependency audits with correct baseline handling",
        category="security",
        intercept_type="function",
    ),
    # ── Python dead code / complexity ─────────────────────────────────────────
    CommandMap(
        forbidden="vulture",
        sm_command="sm swab -g laziness:dead-code.py",
        reason="sm swab runs dead-code detection with baseline filtering",
        category="code quality",
        intercept_type="function",
    ),
    CommandMap(
        forbidden="radon",
        sm_command="sm swab -g laziness:complexity-creep.py",
        reason="sm swab runs complexity checks with baseline handling",
        category="code quality",
        intercept_type="function",
    ),
    CommandMap(
        forbidden="diff-cover",
        sm_command="sm swab -g myopia:just-this-once.py",
        reason="sm swab handles diff-coverage with correct baseline and reporting",
        category=_CAT_TEST_COV,
        intercept_type="function",
    ),
    # ── JavaScript / TypeScript ───────────────────────────────────────────────
    CommandMap(
        forbidden="npx knip",
        sm_command="sm swab -g laziness:dead-code.js",
        reason="sm swab runs JS dead-code detection with baseline filtering",
        category="JS/TS",
        intercept_type="npx",
        wrapper_command="npx",
        subcommands=("knip",),
    ),
    CommandMap(
        forbidden="npx eslint",
        sm_command="sm swab -g laziness:sloppy-formatting.js",
        reason="sm swab runs JS lint/format gates in correct pipeline context",
        category="JS/TS",
        intercept_type="npx",
        wrapper_command="npx",
        subcommands=("eslint",),
    ),
    CommandMap(
        forbidden="npx prettier",
        sm_command="sm swab -g laziness:sloppy-formatting.js",
        reason="sm swab runs JS lint/format gates in correct pipeline context",
        category="JS/TS",
        intercept_type="npx",
        wrapper_command="npx",
        subcommands=("prettier",),
    ),
    CommandMap(
        forbidden="npx tsc",
        sm_command="sm swab -g overconfidence:type-blindness.js",
        reason="sm swab runs TypeScript type checks with correct configuration",
        category="JS/TS",
        intercept_type="npx",
        wrapper_command="npx",
        subcommands=("tsc",),
    ),
]
