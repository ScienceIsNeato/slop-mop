"""Code duplication detection using jscpd.

Detects copy-paste code across multiple languages.
Reports specific file pairs and line ranges for deduplication.
"""

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

from slopbucket.checks.base import BaseCheck
from slopbucket.core.result import CheckResult, CheckStatus

DEFAULT_THRESHOLD = 5.0  # Percent duplication allowed
MIN_TOKENS = 50
MIN_LINES = 5


class DuplicationCheck(BaseCheck):
    """Cross-language code duplication detection via jscpd."""

    def __init__(self, config: Dict, threshold: float = DEFAULT_THRESHOLD):
        super().__init__(config)
        self.threshold = config.get("threshold", threshold)

    @property
    def name(self) -> str:
        return "duplication"

    @property
    def display_name(self) -> str:
        return f"📋 Code Duplication (max {self.threshold}%)"

    def is_applicable(self, project_root: str) -> bool:
        # Applicable to any project with code
        for ext in [".py", ".js", ".ts", ".jsx", ".tsx"]:
            for root, _, files in os.walk(project_root):
                if any(f.endswith(ext) for f in files):
                    return True
        return False

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()

        # Check jscpd availability
        result = self._run_command(["npx", "jscpd", "--version"], cwd=project_root, timeout=30)
        if result.returncode != 0:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=time.time() - start_time,
                error="jscpd not available",
                fix_suggestion="Install jscpd: npm install -g jscpd",
            )

        # Run jscpd
        cmd = [
            "npx", "jscpd",
            "--min-tokens", str(MIN_TOKENS),
            "--min-lines", str(MIN_LINES),
            "--threshold", str(self.threshold),
            "--reporters", "json",
            "--output", "/tmp/jscpd-report",
            "--ignore", "node_modules,dist,build,.git,__pycache__,.venv,venv",
            ".",
        ]

        result = self._run_command(cmd, cwd=project_root, timeout=300)
        duration = time.time() - start_time

        # Parse results
        report_path = "/tmp/jscpd-report/jscpd-report.json"
        if not os.path.exists(report_path):
            if result.returncode == 0:
                return self._create_result(
                    status=CheckStatus.PASSED,
                    duration=duration,
                    output="No duplication detected",
                )
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                error=result.error or "jscpd failed to produce report",
            )

        try:
            with open(report_path) as f:
                report = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                error=f"Failed to parse jscpd report: {e}",
            )

        duplicates = report.get("duplicates", [])
        stats = report.get("statistics", {})
        total_percentage = stats.get("total", {}).get("percentage", 0)

        if total_percentage <= self.threshold and not duplicates:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"Duplication: {total_percentage:.1f}% (within {self.threshold}% limit)",
            )

        # Format violation details
        violations = self._format_duplicates(duplicates)
        detail = f"Duplication: {total_percentage:.1f}% exceeds {self.threshold}% limit\n\n"
        detail += "Duplicate blocks:\n" + "\n".join(violations[:10])
        if len(violations) > 10:
            detail += f"\n... and {len(violations) - 10} more"

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=detail,
            error=f"{total_percentage:.1f}% duplication ({len(duplicates)} blocks)",
            fix_suggestion="Extract duplicated code into shared functions or modules.",
        )

    def _format_duplicates(self, duplicates: List[Dict[str, Any]]) -> List[str]:
        """Format duplicate entries for display."""
        violations = []
        for dup in duplicates:
            first = dup.get("firstFile", {})
            second = dup.get("secondFile", {})
            lines = dup.get("lines", 0)
            violations.append(
                f"  {first.get('name', '?')}:{first.get('startLoc', {}).get('line', '?')}-"
                f"{first.get('endLoc', {}).get('line', '?')} ↔ "
                f"{second.get('name', '?')}:{second.get('startLoc', {}).get('line', '?')}-"
                f"{second.get('endLoc', {}).get('line', '?')} ({lines} lines)"
            )
        return violations
