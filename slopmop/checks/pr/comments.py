"""PR comments check - fails if unresolved PR comments exist.

This check is designed to help AI agents systematically address PR feedback
before pushing or completing a PR. When unresolved comments exist, it provides
clear guidance on the strategic process for addressing them.
"""

import json
import os
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

from slopmop.checks.base import BaseCheck, ConfigField, Flaw, GateCategory
from slopmop.core.result import CheckResult, CheckStatus


class PRCommentsCheck(BaseCheck):
    """PR comment resolution enforcement.

    Wraps the GitHub CLI (gh) to detect unresolved PR review
    threads. Fails if any threads are still open, ensuring all
    reviewer feedback is addressed before merge.

    Profiles: pr

    Configuration:
      fail_on_unresolved: True — fail the gate if unresolved
          comments exist. Set to False to make advisory-only.

    Common failures:
      Unresolved comments: Address each comment thread, then
          resolve it via the GitHub UI or gh CLI. Follow the
          PR closing protocol for systematic resolution.
      No PR context: This gate only runs on PR branches. If
          you're on main or a non-PR branch, it skips.
      gh CLI not available: Install GitHub CLI:
          https://cli.github.com/

    Re-validate:
      ./sm validate pr:comments --verbose
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
    def flaw(self) -> Flaw:
        return Flaw.LAZINESS

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="fail_on_unresolved",
                field_type="bool",
                default=True,
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
            unresolved: List[Dict[str, Any]] = []
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

    def _format_guidance(
        self,
        threads: List[Dict[str, Any]],
        pr_number: int,
        owner: str,
        repo: str,
    ) -> str:
        """Format actionable guidance for resolving PR comments."""
        lines: List[str] = []
        lines.append("=" * 80)
        lines.append("🔀 PR COMMENT RESOLUTION PROTOCOL")
        lines.append("=" * 80)
        lines.append("")
        lines.append(f"PR #{pr_number} has {len(threads)} unresolved comment(s).")
        lines.append(f"Repository: {owner}/{repo}")
        lines.append("")

        # Group comments by category
        categorized: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
        for i, thread in enumerate(threads, 1):
            category = self._categorize_comment(thread["body"])
            if category not in categorized:
                categorized[category] = []
            categorized[category].append((i, thread))

        # Priority order for categories (most critical first)
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

        lines.append("━" * 80)
        lines.append(
            "📋 COMMENTS BY CATEGORY (work top-to-bottom, most critical first)"
        )
        lines.append("━" * 80)

        for category in priority_order:
            if category not in categorized:
                continue

            lines.append("")
            lines.append(f"┌─ {category} ({len(categorized[category])} comment(s))")
            lines.append("│")

            for idx, thread in categorized[category]:
                body = thread["body"]
                # Show full comment, just normalize whitespace
                body = " ".join(body.split())

                lines.append(f"│  [{idx}] {thread['thread_id']}")
                lines.append(f"│      Author: @{thread['author']}")
                if thread["path"]:
                    location = thread["path"]
                    if thread["line"]:
                        location += f":{thread['line']}"
                    lines.append(f"│      Location: {location}")
                if thread["is_outdated"]:
                    lines.append("│      ⚠️  OUTDATED (code has changed)")
                lines.append(f"│      Comment: {body}")
                lines.append("│")

            lines.append("└" + "─" * 79)

        lines.append("")
        lines.append("━" * 80)
        lines.append("🤖 AI AGENT WORKFLOW")
        lines.append("━" * 80)
        lines.append("")
        lines.append("STEP 1: TRIAGE (do this first for ALL comments)")
        lines.append("─" * 40)
        lines.append("For each comment, determine its status:")
        lines.append("")
        lines.append(
            "  ✅ ALREADY FIXED  → Resolve immediately (code already addresses this)"
        )
        lines.append("  📝 NEEDS FIX      → Plan the fix, implement it")
        lines.append("  ❓ NEEDS CLARITY  → Ask reviewer before implementing")
        lines.append("  🚫 WONT_RESOLVE   → Open-ended question or out of scope")
        lines.append("")
        lines.append("STEP 2: WORK TOP-TO-BOTTOM BY CATEGORY")
        lines.append("─" * 40)
        lines.append("Categories are ordered by risk/impact. Start with Security,")
        lines.append("then Logic/Correctness, etc. Lower-level fixes often resolve")
        lines.append("related comments automatically.")
        lines.append("")
        lines.append("STEP 3: FOR EACH FIX")
        lines.append("─" * 40)
        lines.append("1. Make the code change")
        lines.append("2. Commit with descriptive message")
        lines.append("3. Resolve the thread using the command below")
        lines.append("4. Move to next comment")
        lines.append("")

        lines.append("━" * 80)
        lines.append("🔧 RESOLUTION COMMANDS (copy-paste ready)")
        lines.append("━" * 80)
        lines.append("")

        for i, thread in enumerate(threads, 1):
            thread_id = thread["thread_id"]
            body_preview = " ".join(thread["body"].split())[:60]
            if len(thread["body"]) > 60:
                body_preview += "..."

            lines.append(f"# [{i}] {body_preview}")
            lines.append(f"# Location: {thread['path'] or 'N/A'}")
            lines.append("")

            # Resolve command
            lines.append("# To RESOLVE (after fixing):")
            lines.append(
                f"gh api graphql -f query='mutation {{ resolveReviewThread(input: {{threadId: \"{thread_id}\"}}) {{ thread {{ id isResolved }} }} }}'"
            )
            lines.append("")

            # Reply with fix explanation
            lines.append("# To REPLY with fix explanation:")
            lines.append(
                f"echo 'Fixed in commit $(git rev-parse --short HEAD). [YOUR EXPLANATION]' | gh pr comment {pr_number} --body-file -"
            )
            lines.append("")

            # WONT_RESOLVE option
            lines.append("# To mark as WONT_RESOLVE (for questions/out-of-scope):")
            lines.append(
                f"echo '[WONT_RESOLVE] [YOUR REASON - e.g., open-ended question, out of PR scope, deferred to issue #X]' | gh pr comment {pr_number} --body-file -"
            )
            lines.append("")
            lines.append("─" * 40)
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
        lines.append("./sm validate pr:comments")
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

        # We have unresolved threads - generate full report and save to file
        fail_on_unresolved = self.config.get("fail_on_unresolved", True)
        full_report = self._format_guidance(threads, pr_number, owner, repo)

        # Save full report to temp file
        report_file = self._save_report_to_file(full_report, pr_number)

        # Create concise summary for gate output
        summary = self._format_summary(threads, pr_number, report_file)

        if fail_on_unresolved:
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=summary,
                error=f"{len(threads)} unresolved PR comment(s)",
                fix_suggestion=f"Read full report: cat {report_file}",
            )
        else:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"⚠️ {len(threads)} unresolved comments (check disabled)\n\n"
                + summary,
            )

    def _save_report_to_file(self, report: str, pr_number: int) -> str:
        """Save the full PR comments report to a temp file.

        Args:
            report: Full report content
            pr_number: PR number for filename

        Returns:
            Path to the saved report file
        """
        # Use a consistent location so agents can find it
        report_dir = tempfile.gettempdir()
        report_path = os.path.join(report_dir, f"pr_{pr_number}_comments_report.md")

        with open(report_path, "w") as f:
            f.write(report)

        return report_path

    def _format_summary(
        self, threads: List[Dict[str, Any]], pr_number: int, report_file: str
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
        lines.append("")
        lines.append("To view: cat " + report_file)
        lines.append("")
        lines.append("Quick start:")
        lines.append("  1. Read the full report above")
        lines.append("  2. Address comments by category (most complex first)")
        lines.append("  3. Use provided commands to resolve each thread")
        lines.append("  4. Re-run: ./sm validate pr:comments")

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
            "🏗️ Architecture/Design",
            "⚡ Performance",
            "🧪 Testing",
            "📝 Documentation",
            "🎨 Style/Formatting",
            "❓ Other",
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
