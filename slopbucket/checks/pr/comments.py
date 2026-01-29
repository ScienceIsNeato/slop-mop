"""PR comments check - fails if unresolved PR comments exist.

This check is designed to help AI agents systematically address PR feedback
before pushing or completing a PR. When unresolved comments exist, it provides
clear guidance on the strategic process for addressing them.
"""

import json
import os
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from slopbucket.checks.base import BaseCheck, ConfigField, GateCategory
from slopbucket.core.result import CheckResult, CheckStatus


class PRCommentsCheck(BaseCheck):
    """Check for unresolved PR comments.

    This check:
    1. Detects if we're in a PR context (via branch or environment)
    2. Fetches unresolved comment threads from GitHub
    3. Fails with actionable guidance if comments exist

    The guidance is specifically designed for AI agents following
    the PR closing protocol.
    """

    @property
    def name(self) -> str:
        return "comments"

    @property
    def display_name(self) -> str:
        return "💬 PR Comments"

    @property
    def category(self) -> GateCategory:
        return GateCategory.PR

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="fail_on_unresolved",
                field_type="bool",
                default=True,
                description="Whether to fail if unresolved comments exist",
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
            )
            if result.returncode != 0:
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

        # Try to detect if we're in a PR context
        pr_number = self._detect_pr_number(project_root)
        return pr_number is not None

    def _detect_pr_number(self, project_root: str) -> Optional[int]:
        """Detect PR number from current context.

        Checks:
        1. Environment variable (CI context)
        2. Current branch has an open PR
        """
        # Check CI environment variables
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

        # Try to detect from current branch
        try:
            result = subprocess.run(
                ["gh", "pr", "view", "--json", "number"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=project_root,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return data.get("number")
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            pass

        return None

    def _get_repo_info(self, project_root: str) -> Tuple[str, str]:
        """Get repository owner and name."""
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
                return owner, name
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
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
            unresolved = []
            for thread in threads:
                if not thread.get("isResolved", True):
                    comments = thread.get("comments", {}).get("nodes", [])
                    if comments:
                        first_comment = comments[0]
                        unresolved.append(
                            {
                                "thread_id": thread.get("id"),
                                "is_outdated": thread.get("isOutdated", False),
                                "body": first_comment.get("body", ""),
                                "author": first_comment.get("author", {}).get(
                                    "login", "unknown"
                                ),
                                "path": first_comment.get("path"),
                                "line": first_comment.get("line"),
                                "created_at": first_comment.get("createdAt"),
                            }
                        )

            return unresolved

        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            return []

    def _format_guidance(
        self,
        threads: List[Dict[str, Any]],
        pr_number: int,
        owner: str,
        repo: str,
    ) -> str:
        """Format actionable guidance for resolving PR comments."""
        lines = []
        lines.append("=" * 70)
        lines.append("🔀 PR COMMENT RESOLUTION PROTOCOL")
        lines.append("=" * 70)
        lines.append("")
        lines.append(f"PR #{pr_number} has {len(threads)} unresolved comment(s).")
        lines.append("")
        lines.append("━" * 70)
        lines.append("📋 UNRESOLVED COMMENTS")
        lines.append("━" * 70)

        for i, thread in enumerate(threads, 1):
            body = thread["body"]
            # Truncate long comments
            if len(body) > 200:
                body = body[:200] + "..."
            # Replace newlines with spaces for compact display
            body = " ".join(body.split())

            lines.append("")
            lines.append(f"[{i}] Thread: {thread['thread_id']}")
            lines.append(f"    Author: @{thread['author']}")
            if thread["path"]:
                location = thread["path"]
                if thread["line"]:
                    location += f":{thread['line']}"
                lines.append(f"    Location: {location}")
            if thread["is_outdated"]:
                lines.append("    ⚠️  OUTDATED (code has changed)")
            lines.append(f"    Comment: {body}")

        lines.append("")
        lines.append("━" * 70)
        lines.append("🤖 AI AGENT INSTRUCTIONS")
        lines.append("━" * 70)
        lines.append("")
        lines.append("Follow the PR Closing Protocol:")
        lines.append("")
        lines.append("1. ANALYZE: Group comments by underlying concept, not by file")
        lines.append("   - Security issues")
        lines.append("   - Logic/correctness")
        lines.append("   - Code quality/style")
        lines.append("   - Performance")
        lines.append("")
        lines.append("2. TRIAGE: For each comment, determine:")
        lines.append("   - Is it already fixed? → Resolve immediately")
        lines.append("   - Is it outdated/stale? → Resolve with explanation")
        lines.append("   - Needs clarification? → Ask before implementing")
        lines.append("   - Needs fix? → Plan the fix")
        lines.append("")
        lines.append("3. PRIORITIZE: Address highest-risk changes first")
        lines.append("   - Lower-level fixes often obviate related comments")
        lines.append("   - Group related fixes into thematic commits")
        lines.append("")
        lines.append("4. IMPLEMENT: For each fix:")
        lines.append("   - Make the change")
        lines.append("   - Commit with descriptive message")
        lines.append("   - Immediately resolve the thread:")
        lines.append("")
        lines.append("     gh api graphql -f query='mutation {")
        lines.append('       resolveReviewThread(input: {threadId: "THREAD_ID"}) {')
        lines.append("         thread { id isResolved }")
        lines.append("       }")
        lines.append("     }'")
        lines.append("")
        lines.append("5. ITERATE: Re-run this check until all comments resolved")
        lines.append("")
        lines.append("━" * 70)
        lines.append("⚠️  DO NOT push until all comments are resolved!")
        lines.append("━" * 70)

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

        # We have unresolved threads - fail with guidance
        fail_on_unresolved = self.config.get("fail_on_unresolved", True)

        guidance = self._format_guidance(threads, pr_number, owner, repo)

        if fail_on_unresolved:
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=guidance,
                error=f"{len(threads)} unresolved PR comment(s)",
                fix_suggestion="Address all unresolved comments following the protocol above",
            )
        else:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"⚠️ {len(threads)} unresolved comments (check disabled)\n\n"
                + guidance,
            )
