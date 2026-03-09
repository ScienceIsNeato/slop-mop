"""PR comments check - fails if unresolved PR comments exist.

This check is designed to help AI agents systematically address PR feedback
before pushing or completing a PR. When unresolved comments exist, it provides
clear guidance on the strategic process for addressing them.
"""

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    GateLevel,
)
from slopmop.core.result import CheckResult, CheckStatus, Finding


class PRCommentsCheck(BaseCheck):
    """PR comment resolution enforcement.

    Wraps the GitHub CLI (gh) to detect unresolved PR review
    threads. Fails if any threads are still open, ensuring all
    reviewer feedback is addressed before merge.

    Level: scour (PR readiness context required)

    Configuration:
      fail_on_unresolved: False (default) — warn when unresolved
          comments exist. Set to True to fail the gate instead.

    Common failures:
      Unresolved comments: Address each comment thread, then
          resolve it via the GitHub UI or gh CLI. Follow the
          PR closing protocol for systematic resolution.
      No PR context: This gate only runs on PR branches. If
          you're on main or a non-PR branch, it skips.
      gh CLI not available: Install GitHub CLI:
          https://cli.github.com/

    Re-check:
      sm scour -g myopia:ignored-feedback --verbose
    """

    level = GateLevel.SCOUR
    role = CheckRole.DIAGNOSTIC

    PROTOCOL_VERSION = "pr-feedback-v1"
    RESOLUTION_REASON_PRIORITY = [
        "fixed_in_code",
        "invalid_with_explanation",
        "no_longer_applicable",
        "out_of_scope_ticketed",
        "needs_human_feedback",
    ]
    RESOLUTION_PRIORITY_RANK = {
        scenario: i + 1 for i, scenario in enumerate(RESOLUTION_REASON_PRIORITY)
    }
    CATEGORY_IMPACT_SCORES = {
        "🔐 Security": (95, 90),
        "🐛 Logic/Correctness": (90, 95),
        "🏗️ Architecture": (88, 92),
        "⚡ Performance": (80, 78),
        "🧪 Testing": (70, 72),
        "📚 Documentation": (35, 25),
        "🎨 Style": (20, 15),
        "❓ Question": (50, 55),
        "💭 General": (45, 45),
    }

    @property
    def name(self) -> str:
        return "ignored-feedback"

    @property
    def display_name(self) -> str:
        return "💬 Unresolved PR Comments"

    @property
    def gate_description(self) -> str:
        return "💬 Checks for unresolved PR review threads"

    @property
    def category(self) -> GateCategory:
        return GateCategory.MYOPIA

    @property
    def flaw(self) -> Flaw:
        return Flaw.LAZINESS

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="fail_on_unresolved",
                field_type="bool",
                default=False,
                description="Whether to fail if unresolved comments exist",
                permissiveness="true_is_stricter",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        """Check is applicable if we can detect a PR context."""
        # Check if we're in a git repo
        git_dir = os.path.join(project_root, ".git")
        if not os.path.isdir(git_dir):
            return False

        # Check if gh CLI is available
        try:
            result = subprocess.run(
                ["gh", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=project_root,
            )
            if result.returncode != 0:
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

        # Try to detect if we're in a PR context
        pr_number = self._detect_pr_number(project_root)
        return pr_number is not None

    def skip_reason(self, project_root: str) -> str:
        """Return skip reason when git or PR context is unavailable."""
        git_dir = os.path.join(project_root, ".git")
        if not os.path.isdir(git_dir):
            return "Not a git repository"

        try:
            result = subprocess.run(
                ["gh", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=project_root,
            )
            if result.returncode != 0:
                return "GitHub CLI (gh) not available"
        except FileNotFoundError:
            return "GitHub CLI (gh) not installed"
        except subprocess.TimeoutExpired:
            return "GitHub CLI check timed out"

        pr_number = self._detect_pr_number(project_root)
        if pr_number is None:
            return "No PR context detected (not on a PR branch)"

        return "PR comments check not applicable"

    def _detect_pr_number(self, project_root: str) -> Optional[int]:
        """Detect PR number from current context.

        Checks:
        1. Environment variable (CI context)
        2. GitHub Actions GITHUB_REF (refs/pull/N/merge format)
        3. GitHub event payload file (GITHUB_EVENT_PATH)
        4. Current branch has an open PR (via gh pr list --head <branch>)
        """
        # Check explicit CI environment variables first
        for env_var in [
            "GITHUB_PR_NUMBER",
            "PR_NUMBER",
            "PULL_REQUEST_NUMBER",
        ]:
            pr_num = os.environ.get(env_var)
            if pr_num:
                try:
                    return int(pr_num)
                except ValueError:
                    pass

        # Check GitHub Actions GITHUB_REF (format: refs/pull/N/merge)
        github_ref = os.environ.get("GITHUB_REF", "")
        if github_ref.startswith("refs/pull/"):
            try:
                # Extract number from refs/pull/N/merge
                parts = github_ref.split("/")
                if len(parts) >= 3:
                    return int(parts[2])
            except (ValueError, IndexError):
                pass

        # Check GitHub Actions event payload
        event_path = os.environ.get("GITHUB_EVENT_PATH")
        if event_path and os.path.exists(event_path):
            try:
                with open(event_path) as f:
                    event_data = json.load(f)
                    # pull_request event
                    if "pull_request" in event_data:
                        return event_data["pull_request"].get("number")
                    # issue_comment on a PR
                    if "issue" in event_data and event_data.get("issue", {}).get(
                        "pull_request"
                    ):
                        return event_data["issue"].get("number")
            except (json.JSONDecodeError, IOError, KeyError):
                pass

        # Try to detect from current branch using gh CLI
        try:
            # First, get the current branch name
            branch_result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=project_root,
            )
            if branch_result.returncode != 0 or not branch_result.stdout.strip():
                return None

            current_branch = branch_result.stdout.strip()

            # Use gh pr list --head to find the PR for THIS specific branch
            # (gh pr view can return PRs from other branches)
            result = subprocess.run(
                [
                    "gh",
                    "pr",
                    "list",
                    "--head",
                    current_branch,
                    "--json",
                    "number",
                    "--limit",
                    "1",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=project_root,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if data and len(data) > 0:
                    return data[0].get("number")
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            pass

        return None

    def _get_repo_info(self, project_root: str) -> Tuple[str, str]:
        """Get repository owner and name.

        Checks (in order):
        1. GITHUB_REPOSITORY env var (always set in GitHub Actions, no auth needed)
        2. gh repo view CLI (requires gh auth, works locally)
        3. Git remote URL parsing (works for any cloned repo, no auth needed)
        """
        # Check GITHUB_REPOSITORY env var first (format: "owner/repo")
        github_repo = os.environ.get("GITHUB_REPOSITORY", "")
        if "/" in github_repo:
            parts = github_repo.split("/", 1)
            if len(parts) == 2 and parts[0] and parts[1]:
                return parts[0], parts[1]

        # Try gh CLI (works when user has gh auth configured)
        try:
            result = subprocess.run(
                ["gh", "repo", "view", "--json", "owner,name"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=project_root,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                owner = data.get("owner", {}).get("login", "")
                name = data.get("name", "")
                if owner and name:
                    return owner, name
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            pass

        # Fall back to parsing git remote URL (works for public repos, no auth)
        return self._parse_repo_from_git_remote(project_root)

    @staticmethod
    def _parse_repo_from_git_remote(project_root: str) -> Tuple[str, str]:
        """Extract owner/repo from the git remote 'origin' URL.

        Handles both HTTPS and SSH formats:
          https://github.com/owner/repo.git
          git@github.com:owner/repo.git
        """
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=project_root,
            )
            if result.returncode != 0:
                return "", ""

            url = result.stdout.strip()
            # Match HTTPS: https://github.com/owner/repo(.git)
            # Match SSH:   git@github.com:owner/repo(.git)
            match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", url)
            if match:
                return match.group(1), match.group(2)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return "", ""

    def _get_unresolved_threads(
        self, project_root: str, pr_number: int, owner: str, repo: str
    ) -> List[Dict[str, Any]]:
        """Fetch unresolved comment threads from GitHub."""
        graphql_query = """
        query($owner: String!, $name: String!, $number: Int!) {
          repository(owner: $owner, name: $name) {
            pullRequest(number: $number) {
              reviewThreads(first: 100) {
                nodes {
                  id
                  isResolved
                  isOutdated
                  comments(first: 5) {
                    nodes {
                      body
                      path
                      line
                      author { login }
                      createdAt
                    }
                  }
                }
              }
            }
          }
        }
        """

        try:
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    "graphql",
                    "-F",
                    f"owner={owner}",
                    "-F",
                    f"name={repo}",
                    "-F",
                    f"number={pr_number}",
                    "-f",
                    f"query={graphql_query}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=project_root,
            )

            if result.returncode != 0:
                return []

            data = json.loads(result.stdout)
            threads = (
                data.get("data", {})
                .get("repository", {})
                .get("pullRequest", {})
                .get("reviewThreads", {})
                .get("nodes", [])
            )

            # Filter to unresolved threads
            unresolved: List[Dict[str, Any]] = []
            for thread in threads:
                if not thread.get("isResolved", True):
                    comments = thread.get("comments", {}).get("nodes", [])
                    if comments:
                        first_comment = comments[0]
                        author = first_comment.get("author", {}).get("login", "unknown")
                        # github-advanced-security threads are Code
                        # Scanning alerts surfaced as PR comments.  Those
                        # are already tracked in the Security tab — and
                        # when slop-mop's own SARIF output is the source,
                        # re-flagging them here creates a feedback loop:
                        # we flag the comment → new SARIF alert → new
                        # gh-adv-sec comment → next run flags that.
                        if author == "github-advanced-security":
                            continue
                        unresolved.append(
                            {
                                "thread_id": thread.get("id"),
                                "is_outdated": thread.get("isOutdated", False),
                                "body": first_comment.get("body", ""),
                                "author": author,
                                "path": first_comment.get("path"),
                                "line": first_comment.get("line"),
                                "created_at": first_comment.get("createdAt"),
                            }
                        )

            return unresolved

        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            return []

    # Category keyword mappings for comment classification
    _COMMENT_CATEGORIES = [
        (
            "🔐 Security",
            [
                "security",
                "vulnerability",
                "injection",
                "xss",
                "auth",
                "password",
                "secret",
                "credential",
                "permission",
                "sanitize",
                "escape",
                "unsafe",
            ],
        ),
        (
            "🐛 Logic/Correctness",
            [
                "bug",
                "incorrect",
                "wrong",
                "error",
                "fix",
                "broken",
                "fail",
                "crash",
                "exception",
                "null",
                "undefined",
                "race condition",
                "deadlock",
            ],
        ),
        (
            "🏗️ Architecture",
            [
                "architecture",
                "design",
                "pattern",
                "refactor",
                "abstract",
                "interface",
                "coupling",
                "dependency",
                "solid",
                "separation",
            ],
        ),
        (
            "🧪 Testing",
            ["test", "coverage", "mock", "assert", "spec", "edge case"],
        ),
        (
            "📚 Documentation",
            ["document", "comment", "docstring", "readme", "explain", "clarify"],
        ),
        (
            "🎨 Style",
            ["style", "format", "naming", "convention", "lint", "whitespace", "indent"],
        ),
        (
            "⚡ Performance",
            [
                "performance",
                "slow",
                "optimize",
                "cache",
                "memory",
                "efficient",
                "complexity",
                "o(n)",
            ],
        ),
    ]

    def _categorize_comment(self, body: str) -> str:
        """Categorize a comment by its likely type."""
        body_lower = body.lower()

        # Check against keyword categories
        for category, keywords in self._COMMENT_CATEGORIES:
            if any(kw in body_lower for kw in keywords):
                return category

        # Questions/clarifications
        question_keywords = ["why", "what", "how", "could you", "can you"]
        if "?" in body or any(kw in body_lower for kw in question_keywords):
            return "❓ Question"

        return "💭 General"

    def _classify_resolution_scenario(
        self, thread: Dict[str, Any]
    ) -> Tuple[str, str, List[str]]:
        """Classify a thread into locked protocol scenarios."""
        body = str(thread.get("body", ""))
        body_lower = body.lower()
        is_outdated = bool(thread.get("is_outdated", False))

        anti_pattern_flags: List[str] = []
        if "wont_resolve" in body_lower or "won't resolve" in body_lower:
            anti_pattern_flags.append("contains_wont_resolve_marker")
        if "just ignore" in body_lower or "ignore this" in body_lower:
            anti_pattern_flags.append("contains_ignore_language")

        if is_outdated or "outdated" in body_lower:
            return (
                "no_longer_applicable",
                "Thread is marked outdated or superseded by later code changes.",
                anti_pattern_flags,
            )

        if any(
            token in body_lower
            for token in ["already fixed", "resolved by", "fixed in", "addressed in"]
        ):
            return (
                "fixed_in_code",
                "Comment indicates resolution likely exists in code and should be verified+resolved.",
                anti_pattern_flags,
            )

        if any(
            token in body_lower
            for token in [
                "false positive",
                "not accurate",
                "incorrect",
                "invalid",
                "not applicable",
            ]
        ):
            return (
                "invalid_with_explanation",
                "Comment appears invalid or stale and should be answered with evidence.",
                anti_pattern_flags,
            )

        if any(
            token in body_lower
            for token in [
                "out of scope",
                "separate issue",
                "follow-up",
                "follow up",
                "file an issue",
            ]
        ):
            return (
                "out_of_scope_ticketed",
                "Comment is outside PR scope and should be redirected to a tracked issue.",
                anti_pattern_flags,
            )

        if "?" in body or any(
            token in body_lower
            for token in ["clarify", "can you", "could you", "why", "what", "how"]
        ):
            return (
                "needs_human_feedback",
                "Comment requests clarification and should remain open pending reviewer response.",
                anti_pattern_flags,
            )

        return (
            "fixed_in_code",
            "Default to fixed_in_code so agent verifies implementation and resolves deterministically.",
            anti_pattern_flags,
        )

    def _classify_and_order_threads(
        self, threads: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Attach protocol metadata and order threads deterministically."""
        classified: List[Dict[str, Any]] = []

        for thread in threads:
            category = self._categorize_comment(str(thread.get("body", "")))
            blast_radius_score, dependency_impact_score = (
                self.CATEGORY_IMPACT_SCORES.get(category, (40, 40))
            )
            scenario, scenario_reason, anti_pattern_flags = (
                self._classify_resolution_scenario(thread)
            )

            rank = self.RESOLUTION_PRIORITY_RANK.get(scenario)
            if rank is None:
                raise ValueError(
                    "UNCLASSIFIED_THREAD_PROTOCOL_BLOCK: "
                    f"Unknown scenario '{scenario}' for thread {thread.get('thread_id')}."
                )

            classified.append(
                {
                    **thread,
                    "category": category,
                    "resolution_scenario": scenario,
                    "resolution_priority_rank": rank,
                    "resolution_priority_reason": scenario_reason,
                    "blast_radius_score": blast_radius_score,
                    "dependency_impact_score": dependency_impact_score,
                    "anti_pattern_flags": anti_pattern_flags,
                }
            )

        return sorted(
            classified,
            key=lambda t: (
                int(t["resolution_priority_rank"]),
                -max(int(t["blast_radius_score"]), int(t["dependency_impact_score"])),
                str(t.get("thread_id", "")),
            ),
        )

    def _next_protocol_loop_dir(self, project_root: str, pr_number: int) -> Path:
        """Create and return the next persistent protocol loop directory."""
        root = (
            Path(project_root)
            / ".slopmop"
            / "buff-persistent-memory"
            / f"pr-{pr_number}"
        )
        root.mkdir(parents=True, exist_ok=True)

        max_loop = 0
        for child in root.iterdir():
            if not child.is_dir():
                continue
            match = re.fullmatch(r"loop-(\d+)", child.name)
            if not match:
                continue
            max_loop = max(max_loop, int(match.group(1)))

        loop_dir = root / f"loop-{max_loop + 1:03d}"
        loop_dir.mkdir(parents=True, exist_ok=False)
        return loop_dir

    def _build_commands_script(
        self,
        ordered_threads: List[Dict[str, Any]],
        pr_number: int,
        owner: str,
        repo: str,
    ) -> str:
        """Build deterministic command pack for all protocol scenarios."""

        def resolve_thread_command(thread_id: str) -> str:
            mutation = (
                "mutation { resolveReviewThread(input: {threadId: "
                f'\\"{thread_id}\\"'
                "}) { thread { id isResolved } } }"
            )
            return f"gh api graphql -f query='{mutation}'"

        lines: List[str] = []
        lines.append("#!/usr/bin/env bash")
        lines.append("set -euo pipefail")
        lines.append("")
        lines.append(f"# Protocol: {self.PROTOCOL_VERSION}")
        lines.append(f"# PR: {pr_number}")
        lines.append("")

        for idx, thread in enumerate(ordered_threads, 1):
            thread_id = str(thread.get("thread_id", ""))
            scenario = str(thread.get("resolution_scenario", ""))
            reason = str(thread.get("resolution_priority_reason", ""))
            lines.append(f"# [{idx}] {thread_id}")
            lines.append(
                f"# Scenario={scenario} rank={thread.get('resolution_priority_rank')}"
            )
            lines.append(f"# Reason: {reason}")

            if scenario == "fixed_in_code":
                lines.append(
                    f"echo 'Fixed in commit $(git rev-parse --short HEAD). [explain the code change]' | gh pr comment {pr_number} --body-file -"
                )
                lines.append(resolve_thread_command(thread_id))
            elif scenario == "invalid_with_explanation":
                lines.append(
                    f"echo '[invalid with explanation] [state why this comment no longer applies with evidence]' | gh pr comment {pr_number} --body-file -"
                )
                lines.append(resolve_thread_command(thread_id))
            elif scenario == "no_longer_applicable":
                lines.append(
                    f"echo '[no longer applicable] Code has changed and this thread is outdated; adding explicit note for reviewer.' | gh pr comment {pr_number} --body-file -"
                )
                lines.append(resolve_thread_command(thread_id))
            elif scenario == "out_of_scope_ticketed":
                lines.append(
                    "echo 'Create follow-up issue first, capture URL, then comment with [out of scope ticketed] and issue link.'"
                )
                lines.append(
                    f"echo '[out of scope ticketed] Tracking in issue #[ISSUE_NUMBER]: [URL]. Not part of this PR scope.' | gh pr comment {pr_number} --body-file -"
                )
                lines.append(resolve_thread_command(thread_id))
            elif scenario == "needs_human_feedback":
                lines.append(
                    f"echo '[needs human feedback] Please clarify expected behavior or acceptance criteria before implementation.' | gh pr comment {pr_number} --body-file -"
                )
                lines.append("# Intentionally do not resolve this thread yet.")
            else:
                lines.append(
                    "echo 'UNCLASSIFIED_THREAD_PROTOCOL_BLOCK: unexpected scenario; abort and fix classifier.'"
                )
                lines.append("exit 1")

            lines.append("")

        lines.append(
            "# Final verification: unresolved thread count should be 0 for completion"
        )
        lines.append(
            "gh api graphql -f query='query { repository(owner: \""
            + owner
            + '", name: "'
            + repo
            + '") { pullRequest(number: '
            + str(pr_number)
            + ") { reviewThreads(first: 100) { nodes { isResolved } } } } }' --jq '[.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)] | length'"
        )
        return "\n".join(lines) + "\n"

    def _write_protocol_artifacts(
        self,
        project_root: str,
        pr_number: int,
        owner: str,
        repo: str,
        threads: List[Dict[str, Any]],
        ordered_threads: List[Dict[str, Any]],
        guidance: str,
    ) -> Dict[str, str]:
        """Write deterministic protocol artifacts for this PR loop."""
        loop_dir = self._next_protocol_loop_dir(project_root, pr_number)

        report_md = loop_dir / f"pr_{pr_number}_comments_report.md"
        protocol_json = loop_dir / "protocol.json"
        raw_threads_json = loop_dir / "threads_raw.json"
        classified_json = loop_dir / "classified_threads.json"
        commands_sh = loop_dir / "commands.sh"
        execution_log = loop_dir / "execution_log.md"
        outcomes_json = loop_dir / "outcomes.json"

        report_md.write_text(guidance, encoding="utf-8")
        raw_threads_json.write_text(json.dumps(threads, indent=2), encoding="utf-8")
        classified_json.write_text(
            json.dumps(ordered_threads, indent=2), encoding="utf-8"
        )
        commands_sh.write_text(
            self._build_commands_script(ordered_threads, pr_number, owner, repo),
            encoding="utf-8",
        )
        os.chmod(commands_sh, 0o700)
        execution_log.write_text(
            "# Buff Protocol Execution Log\n\n"
            f"- protocol_version: {self.PROTOCOL_VERSION}\n"
            f"- pr_number: {pr_number}\n"
            f"- loop_dir: {loop_dir}\n",
            encoding="utf-8",
        )
        outcomes_json.write_text(
            json.dumps(
                {
                    "protocol_version": self.PROTOCOL_VERSION,
                    "status": "in_progress",
                    "unresolved_threads": len(ordered_threads),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        protocol_json.write_text(
            json.dumps(
                {
                    "protocol_version": self.PROTOCOL_VERSION,
                    "pr_number": pr_number,
                    "owner": owner,
                    "repo": repo,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "loop_dir": str(loop_dir),
                    "ordered_threads": ordered_threads,
                    "commands_file": str(commands_sh),
                    "report_file": str(report_md),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        return {
            "loop_dir": str(loop_dir),
            "report_md": str(report_md),
            "protocol_json": str(protocol_json),
            "raw_threads_json": str(raw_threads_json),
            "classified_json": str(classified_json),
            "commands_sh": str(commands_sh),
            "execution_log": str(execution_log),
            "outcomes_json": str(outcomes_json),
        }

    def _format_guidance(
        self,
        threads: List[Dict[str, Any]],
        pr_number: int,
        owner: str,
        repo: str,
        ordered_threads: Optional[List[Dict[str, Any]]] = None,
        artifact_paths: Optional[Dict[str, str]] = None,
    ) -> str:
        """Format actionable guidance for resolving PR comments."""
        ordered = ordered_threads or self._classify_and_order_threads(threads)
        lines: List[str] = []
        lines.append("=" * 80)
        lines.append("🔀 PR COMMENT RESOLUTION PROTOCOL")
        lines.append("=" * 80)
        lines.append("")
        lines.append(f"Protocol Version: {self.PROTOCOL_VERSION}")
        lines.append(f"PR #{pr_number} has {len(threads)} unresolved comment(s).")
        lines.append(f"Repository: {owner}/{repo}")
        if artifact_paths:
            lines.append(f"Loop dir: {artifact_paths['loop_dir']}")
        lines.append("")

        lines.append("━" * 80)
        lines.append("📋 LOCKED RESOLUTION ORDER (follow exactly)")
        lines.append("━" * 80)
        lines.append("Priority scenarios (high→low):")
        for scenario in self.RESOLUTION_REASON_PRIORITY:
            lines.append(f"  {self.RESOLUTION_PRIORITY_RANK[scenario]}. {scenario}")
        lines.append("")

        for idx, thread in enumerate(ordered, 1):
            body = " ".join(str(thread.get("body", "")).split())
            lines.append(
                f"[{idx}] {thread.get('thread_id')} :: {thread.get('category')}"
            )
            lines.append(
                "  - scenario: "
                f"{thread.get('resolution_scenario')} "
                f"(rank {thread.get('resolution_priority_rank')})"
            )
            lines.append(
                "  - impact: "
                f"blast={thread.get('blast_radius_score')} "
                f"dependency={thread.get('dependency_impact_score')}"
            )
            lines.append("  - reason: " f"{thread.get('resolution_priority_reason')}")
            if thread.get("path"):
                location = str(thread["path"])
                if thread.get("line"):
                    location += f":{thread['line']}"
                lines.append(f"  - location: {location}")
            if thread.get("anti_pattern_flags"):
                flags = ", ".join(thread.get("anti_pattern_flags", []))
                lines.append(f"  - anti_pattern_flags: {flags}")
            lines.append(f"  - comment: {body}")
            lines.append("")

        lines.append("")
        lines.append("━" * 80)
        lines.append("🤖 AI AGENT WORKFLOW (protocol is locked)")
        lines.append("━" * 80)
        lines.append("")
        lines.append("STEP 1: DO NOT INVENT A WORKFLOW")
        lines.append("─" * 40)
        lines.append(
            "Use scenario+ordering from this report. Do not re-triage protocol."
        )
        lines.append("")
        lines.append("STEP 2: EXECUTE IN ORDER")
        lines.append("─" * 40)
        lines.append("Address each thread exactly once in listed order.")
        lines.append("Higher impact items are intentionally first to reduce churn.")
        lines.append("")
        lines.append("STEP 3: USE COMMAND PACK")
        lines.append("─" * 40)
        if artifact_paths:
            lines.append(f"Run: bash {artifact_paths['commands_sh']}")
        else:
            lines.append("Run generated commands for each scenario in strict order.")
        lines.append("")

        lines.append("━" * 80)
        lines.append("🔧 SCENARIO COMMAND MAPPING")
        lines.append("━" * 80)
        lines.append("")
        lines.append("fixed_in_code: comment with commit evidence, then resolve thread")
        lines.append(
            "invalid_with_explanation: comment with evidence, then resolve thread"
        )
        lines.append(
            "no_longer_applicable: comment stale/outdated rationale, then resolve"
        )
        lines.append(
            "out_of_scope_ticketed: file/link issue, comment with URL, then resolve"
        )
        lines.append("needs_human_feedback: request clarification, do not resolve yet")
        lines.append("")
        if artifact_paths:
            lines.append(f"Commands file: {artifact_paths['commands_sh']}")
            lines.append(f"Classified threads: {artifact_paths['classified_json']}")
            lines.append(f"Protocol record: {artifact_paths['protocol_json']}")
            lines.append("")

        lines.append("━" * 80)
        lines.append("📊 VERIFY ALL RESOLVED")
        lines.append("━" * 80)
        lines.append("")
        lines.append("# Check remaining unresolved count (should return 0):")
        lines.append(
            f"gh api graphql -f query='query {{ repository(owner: \"{owner}\", name: \"{repo}\") {{ pullRequest(number: {pr_number}) {{ reviewThreads(first: 100) {{ nodes {{ isResolved }} }} }} }} }}' --jq '[.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)] | length'"
        )
        lines.append("")
        lines.append("# Re-run this check:")
        lines.append("sm scour -g myopia:ignored-feedback")
        lines.append("")
        lines.append("━" * 80)
        lines.append(
            "⚠️  DO NOT push until all comments are resolved or marked WONT_RESOLVE!"
        )
        lines.append("━" * 80)

        return "\n".join(lines)

    def run(self, project_root: str) -> CheckResult:
        """Run the PR comments check."""
        start_time = time.time()

        # Detect PR number
        pr_number = self._detect_pr_number(project_root)
        if not pr_number:
            duration = time.time() - start_time
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=duration,
                output="No PR context detected (not on a PR branch)",
            )

        # Get repo info
        owner, repo = self._get_repo_info(project_root)
        if not owner or not repo:
            duration = time.time() - start_time
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                error="Could not determine repository owner/name",
            )

        # Fetch unresolved threads
        threads = self._get_unresolved_threads(project_root, pr_number, owner, repo)
        duration = time.time() - start_time

        if not threads:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"✅ PR #{pr_number} has no unresolved comment threads",
            )

        return self._result_with_unresolved_threads(
            project_root=project_root,
            pr_number=pr_number,
            owner=owner,
            repo=repo,
            threads=threads,
            duration=duration,
        )

    def _result_with_unresolved_threads(
        self,
        project_root: str,
        pr_number: int,
        owner: str,
        repo: str,
        threads: List[Dict[str, Any]],
        duration: float,
    ) -> CheckResult:
        """Build check result when unresolved PR threads exist."""

        # We have unresolved threads - classify/order by locked protocol
        fail_on_unresolved = self.config.get("fail_on_unresolved", False)
        try:
            ordered_threads = self._classify_and_order_threads(threads)
        except ValueError as exc:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                error=str(exc),
                output="UNCLASSIFIED_THREAD_PROTOCOL_BLOCK: this should never happen; fix classifier mapping.",
            )

        # Build report once, write persistent artifacts, then rebuild with paths
        bootstrap_report = self._format_guidance(
            threads,
            pr_number,
            owner,
            repo,
            ordered_threads=ordered_threads,
            artifact_paths=None,
        )
        artifact_paths = self._write_protocol_artifacts(
            project_root,
            pr_number,
            owner,
            repo,
            threads,
            ordered_threads,
            bootstrap_report,
        )
        full_report = self._format_guidance(
            threads,
            pr_number,
            owner,
            repo,
            ordered_threads=ordered_threads,
            artifact_paths=artifact_paths,
        )
        report_file = artifact_paths["report_md"]
        Path(report_file).write_text(full_report, encoding="utf-8")

        # Create concise summary for gate output
        summary = self._format_summary(
            ordered_threads,
            pr_number,
            report_file,
            commands_file=artifact_paths["commands_sh"],
            protocol_file=artifact_paths["protocol_json"],
        )

        count = len(threads)
        detail = f"{count} unresolved"

        # One SARIF finding per unresolved thread — anchored at the
        # file/line the reviewer commented on (when the GraphQL API
        # returned one; issue-level comments have neither).
        structured: List[Finding] = []
        for t in ordered_threads:
            body = " ".join(str(t.get("body", "")).split())[:200]
            structured.append(
                Finding(
                    message=f"unresolved comment from @{t.get('author', '?')}: {body}",
                    file=t.get("path") or None,
                    line=t.get("line") if isinstance(t.get("line"), int) else None,
                )
            )

        if fail_on_unresolved:
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=summary,
                error=f"{count} unresolved PR comment(s)",
                fix_suggestion=f"Read full report: cat {report_file}",
                status_detail=detail,
                findings=structured,
            )
        else:
            return self._create_result(
                status=CheckStatus.WARNED,
                duration=duration,
                output=f"⚠️ {count} unresolved comment(s) — "
                f"set fail_on_unresolved: true to block on this\n\n" + summary,
                status_detail=detail,
                findings=structured,
            )

    def _format_summary(
        self,
        threads: List[Dict[str, Any]],
        pr_number: int,
        report_file: str,
        commands_file: Optional[str] = None,
        protocol_file: Optional[str] = None,
    ) -> str:
        """Format a concise summary for gate output.

        Args:
            threads: List of unresolved thread data
            pr_number: PR number
            report_file: Path to full report file

        Returns:
            Concise summary string
        """
        # Group by category
        grouped = self._group_threads_by_category(threads)

        lines: List[str] = []
        lines.append(f"PR #{pr_number}: {len(threads)} unresolved comment(s)")
        lines.append("")
        lines.append("By category:")
        for category, cat_threads in grouped.items():
            lines.append(f"  • {category}: {len(cat_threads)}")
        lines.append("")
        lines.append(f"📄 Full report with commands: {report_file}")
        if commands_file:
            lines.append(f"🧪 Command pack: {commands_file}")
        if protocol_file:
            lines.append(f"🧠 Protocol state: {protocol_file}")
        lines.append("")
        lines.append("To view: cat " + report_file)
        lines.append("")
        lines.append("Quick start:")
        lines.append("  1. Read the full report above")
        if commands_file:
            lines.append(f"  2. Execute protocol commands: bash {commands_file}")
            lines.append("  3. Re-run: sm scour -g myopia:ignored-feedback")
        else:
            lines.append("  2. Address comments by category (most complex first)")
            lines.append("  3. Use provided commands to resolve each thread")
            lines.append("  4. Re-run: sm scour -g myopia:ignored-feedback")

        return "\n".join(lines)

    def _group_threads_by_category(
        self, threads: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group threads by their category.

        Args:
            threads: List of thread data

        Returns:
            Dict mapping category name to list of threads
        """
        grouped: Dict[str, List[Dict[str, Any]]] = {}

        for thread in threads:
            category = self._categorize_comment(thread.get("body", ""))
            if category not in grouped:
                grouped[category] = []
            grouped[category].append(thread)

        # Sort by priority (security first, then logic, etc.)
        priority_order = [
            "🔐 Security",
            "🐛 Logic/Correctness",
            "🏗️ Architecture",
            "⚡ Performance",
            "🧪 Testing",
            "📚 Documentation",
            "🎨 Style",
            "❓ Question",
            "💭 General",
        ]

        sorted_grouped: Dict[str, List[Dict[str, Any]]] = {}
        for category in priority_order:
            if category in grouped:
                sorted_grouped[category] = grouped[category]

        # Add any categories not in priority order
        for category in grouped:
            if category not in sorted_grouped:
                sorted_grouped[category] = grouped[category]

        return sorted_grouped
