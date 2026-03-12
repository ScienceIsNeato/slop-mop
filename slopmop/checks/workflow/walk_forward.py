"""walk-forward — terminal scour check that tells the agent what to do next.

Runs *only* after every other scour gate has passed.  It inspects the real
state of the working tree and the PR to determine the correct next action and
surfaces it as actionable output.  Think of it as the handoff point between
``sm scour`` and the rest of the loop.

Checks performed (in order):
1. Working-tree cleanliness — classifies dirty files with per-file guidance.
2. Push status — detects unpushed local commits.
3. PR number alignment — compares the configured PR number with the branch's
   actual open PR on GitHub.
4. Next-step determination — reads the persisted workflow state and looks up
   the correct ``next_action`` from the state machine.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import List, Optional, Tuple

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    Flaw,
    GateCategory,
    GateLevel,
    ToolContext,
)
from slopmop.constants import (
    ACTION_BUFF_INSPECT,
    NOT_A_GIT_REPO,
    action_buff_inspect_pr,
)
from slopmop.core.result import CheckResult, CheckStatus, Finding


class WalkForwardCheck(BaseCheck):
    """Terminal scour check: next-step guidance after all gates pass.

    Evaluates working-tree state, push status, and PR alignment, then emits
    the single most important next action the agent should take.

    Level: scour (PR context may be needed)
    Role:  diagnostic — no off-the-shelf tool does this
    """

    level = GateLevel.SCOUR
    role = CheckRole.DIAGNOSTIC
    tool_context = ToolContext.PURE
    terminal = True  # runs only after all non-terminal checks pass

    @property
    def name(self) -> str:
        return "walk-forward"

    @property
    def display_name(self) -> str:
        return "🧭 Walk-Forward (next-step guidance)"

    @property
    def gate_description(self) -> str:
        return (
            "Terminal gate — inspects working tree, push status, and PR alignment "
            "to tell the agent exactly what to do next after all other gates pass."
        )

    @property
    def category(self) -> GateCategory:
        return GateCategory.MYOPIA

    @property
    def flaw(self) -> Flaw:
        return Flaw.MYOPIA

    def is_applicable(self, project_root: str) -> bool:
        return Path(project_root, ".git").exists()

    def skip_reason(self, project_root: str) -> str:
        return NOT_A_GIT_REPO

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    def run(self, project_root: str) -> CheckResult:
        start = time.time()
        root = Path(project_root)
        warnings: List[str] = []
        findings: List[Finding] = []

        # 1. Working-tree cleanliness
        dirty_warning = self._check_working_tree(root)
        if dirty_warning:
            warnings.append(dirty_warning)
            findings.append(Finding(message=dirty_warning))

        # 2. Push status
        push_warning = self._check_push_status(root)
        if push_warning:
            warnings.append(push_warning)
            findings.append(Finding(message=push_warning))

        # 3. PR number alignment
        pr_warning, configured_pr, branch_pr = self._check_pr_alignment(root)
        if pr_warning:
            warnings.append(pr_warning)
            findings.append(Finding(message=pr_warning))

        # 4. Next-step from state machine
        next_action = self._next_action(root, configured_pr or branch_pr)

        duration = time.time() - start

        if warnings:
            lines = ["⚠️  Address these before moving forward:\n"]
            for w in warnings:
                lines.append(f"  • {w}")
            lines.append(f"\n➡️  Next: {next_action}")
            return self._create_result(
                status=CheckStatus.WARNED,
                duration=duration,
                output="\n".join(lines),
                findings=findings,
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output=f"✅ Working tree clean, push status OK.\n➡️  Next: {next_action}",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _git(self, args: List[str], cwd: Path) -> Tuple[int, str]:
        """Run a git command, return (returncode, stdout)."""
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode, result.stdout.strip()
        except Exception:
            return 1, ""

    def _check_working_tree(self, root: Path) -> Optional[str]:
        """Return a warning string when the working tree is not clean."""
        rc, output = self._git(["status", "--porcelain"], root)
        if rc != 0 or not output:
            return None

        staged: List[str] = []
        unstaged: List[str] = []
        untracked: List[str] = []
        conflicted: List[str] = []

        for line in output.splitlines():
            if len(line) < 4:
                continue
            xy, path = line[:2], line[3:]
            x, y = xy[0], xy[1]

            # Git porcelain v1 merge-conflict codes: DD AU UD UA DU AA UU
            if xy in ("DD", "AU", "UD", "UA", "DU", "AA", "UU"):
                conflicted.append(path)
            elif x != " " and x != "?":
                staged.append(path)
            elif y != " " and y != "?":
                unstaged.append(path)
            elif x == "?" and y == "?":
                untracked.append(path)

        parts: List[str] = []
        if conflicted:
            parts.append(
                f"Merge conflicts in {len(conflicted)} file(s) — resolve before continuing."
            )
        if staged:
            parts.append(
                f"{len(staged)} staged file(s) not yet committed "
                f"({', '.join(staged[:3])}{'...' if len(staged) > 3 else ''}) "
                "— run `git commit`."
            )
        if unstaged:
            parts.append(
                f"{len(unstaged)} modified tracked file(s) "
                f"({', '.join(unstaged[:3])}{'...' if len(unstaged) > 3 else ''}) "
                "— run `git add -p && git commit` or `git add . && git commit`."
            )
        if untracked:
            parts.append(
                f"{len(untracked)} untracked file(s) "
                f"({', '.join(untracked[:3])}{'...' if len(untracked) > 3 else ''}) "
                "— add to git, add to .gitignore, or delete as appropriate."
            )

        return "; ".join(parts) if parts else None

    def _check_push_status(self, root: Path) -> Optional[str]:
        """Return a warning string when there are unpushed commits."""
        # Check if upstream tracking branch exists
        rc, upstream = self._git(
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], root
        )
        if rc != 0:
            # No upstream — branch has never been pushed
            rc2, branch = self._git(["rev-parse", "--abbrev-ref", "HEAD"], root)
            branch = branch or "HEAD"
            if branch == "HEAD":
                return None  # detached HEAD — skip
            return (
                f"Branch '{branch}' has no upstream — "
                f"run `git push -u origin {branch}`."
            )

        # Count commits ahead of upstream
        rc, ahead_str = self._git(["rev-list", f"{upstream}..HEAD", "--count"], root)
        if rc == 0 and ahead_str.isdigit() and int(ahead_str) > 0:
            count = int(ahead_str)
            return f"{count} unpushed commit(s) ahead of {upstream} — run `git push`."
        return None

    def _check_pr_alignment(
        self, root: Path
    ) -> Tuple[Optional[str], Optional[int], Optional[int]]:
        """Check that the configured PR number matches the branch's open PR.

        Returns ``(warning_or_None, configured_pr, branch_pr)``.
        """
        # Read configured PR number
        configured_pr: Optional[int] = None
        try:
            from slopmop.core.config import get_current_pr_number

            configured_pr = get_current_pr_number(root)
        except Exception:
            pass

        # Get current branch name
        _, branch = self._git(["rev-parse", "--abbrev-ref", "HEAD"], root)
        if not branch or branch == "HEAD":
            return None, configured_pr, None

        # Ask GitHub for the PR associated with this branch
        branch_pr: Optional[int] = None
        try:
            result = subprocess.run(
                ["gh", "pr", "view", "--json", "number", "--jq", ".number"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip().isdigit():
                branch_pr = int(result.stdout.strip())
        except Exception:
            pass

        if branch_pr is None and configured_pr is None:
            return None, None, None

        if branch_pr is not None and configured_pr is None:
            return (
                f"PR #{branch_pr} is open for branch '{branch}' but no working PR is "
                f"configured — run `sm config --current-pr-number {branch_pr}`.",
                None,
                branch_pr,
            )

        if (
            branch_pr is not None
            and configured_pr is not None
            and branch_pr != configured_pr
        ):
            return (
                f"Configured PR #{configured_pr} does not match the open PR "
                f"#{branch_pr} for branch '{branch}' — run "
                f"`sm config --current-pr-number {branch_pr}`.",
                configured_pr,
                branch_pr,
            )

        return None, configured_pr, branch_pr

    def _next_action(self, root: Path, pr_number: Optional[int]) -> str:
        """Look up the next action from the state machine."""
        try:
            from slopmop.workflow.state_machine import MACHINE, WorkflowEvent
            from slopmop.workflow.state_store import read_state

            state = read_state(root)
            if state is None:
                # Scour just passed — we're at SCOUR_CLEAN
                from slopmop.workflow.state_machine import WorkflowState

                state = WorkflowState.SCOUR_CLEAN

            result = MACHINE.advance(state, WorkflowEvent.SCOUR_PASSED)
            if result:
                _, action = result
                return action
        except Exception:
            pass

        # Fallback when state machine is unavailable
        if pr_number:
            return action_buff_inspect_pr(pr_number)
        return f"push branch and open or update PR, then run {ACTION_BUFF_INSPECT}"
