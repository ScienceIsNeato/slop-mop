"""JavaScript/TypeScript dead code detection using knip."""

import json
import os
import time
from typing import Any, Dict, List, Optional, cast

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    ToolContext,
)
from slopmop.checks.mixins import JavaScriptCheckMixin
from slopmop.constants import NPM_INSTALL_FAILED
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel


class JavaScriptDeadCodeCheck(BaseCheck, JavaScriptCheckMixin):
    """Dead code and unused export detection via knip.

    Finds unused files, exports, types, enum members, class members,
    and unresolved imports. Runs knip with JSON output for structured
    findings.

    Level: swab

    Configuration:
      knip_config: path to knip config file (relative to project root).
          Knip auto-discovers knip.json, knip.ts, etc. when not set.

    Common failures:
      Unused exports: remove the export or add a consumer.
      Unused files: delete or import them somewhere.
      Unresolved imports: fix the import path or add the dependency.

    Re-check:
      sm swab -g laziness:dead-code.js --verbose
    """

    tool_context = ToolContext.NODE
    role = CheckRole.FOUNDATION

    @property
    def name(self) -> str:
        return "dead-code.js"

    @property
    def display_name(self) -> str:
        return "🧹 Dead Code (JS/TS)"

    @property
    def gate_description(self) -> str:
        return "🧹 Dead code detection — unused exports, files, and imports (knip)"

    @property
    def category(self) -> GateCategory:
        return GateCategory.LAZINESS

    @property
    def flaw(self) -> Flaw:
        return Flaw.LAZINESS

    @property
    def depends_on(self) -> List[str]:
        return ["laziness:sloppy-formatting.js"]

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="knip_config",
                field_type="string",
                default="",
                description=(
                    "Path to knip config file relative to project root "
                    "(e.g., 'knip.json'). Leave empty for knip auto-discovery."
                ),
                required=False,
            ),
            ConfigField(
                name="ignore_patterns",
                field_type="string[]",
                default=[],
                description=(
                    "Glob patterns for files knip should ignore "
                    "(e.g., ['.detoxrc.js', '.maestro/**', 'scripts/internal/**']). "
                    "Only used when knip_config is not set."
                ),
                required=False,
            ),
            ConfigField(
                name="ignore_dependencies",
                field_type="string[]",
                default=[],
                description=(
                    "Dependency names knip should treat as used "
                    "(e.g., ['@jest/globals', 'geojson']). "
                    "Only used when knip_config is not set."
                ),
                required=False,
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        return self.is_javascript_project(project_root)

    def skip_reason(self, project_root: str) -> str:
        return "No package.json found (not a JavaScript/TypeScript project)"

    def run(self, project_root: str) -> CheckResult:
        """Run knip dead code detection."""
        start_time = time.time()

        if not self.has_node_modules(project_root):
            npm_cmd = self._get_npm_install_command(project_root)
            npm_result = self._run_command(npm_cmd, cwd=project_root, timeout=120)
            if not npm_result.success:
                return self._create_result(
                    status=CheckStatus.ERROR,
                    duration=time.time() - start_time,
                    error=NPM_INSTALL_FAILED,
                    output=npm_result.output,
                )

        cmd = ["npx", "--yes", "knip", "--reporter", "json"]
        knip_config = self.config.get("knip_config", "")
        tmp_config_path: Optional[str] = None

        if knip_config:
            cmd.extend(["--config", knip_config])
        else:
            ignore_patterns: List[str] = self.config.get("ignore_patterns", [])
            ignore_deps: List[str] = self.config.get("ignore_dependencies", [])
            if ignore_patterns or ignore_deps:
                tmp_cfg: Dict[str, Any] = {}
                # Extend any existing repo knip config so entry points and
                # plugins are preserved; without this, knip skips auto-discovery.
                _KNIP_CFG_FILES = ["knip.json", "knip.ts", ".knip.json", ".knip.ts"]
                for _f in _KNIP_CFG_FILES:
                    if os.path.exists(os.path.join(project_root, _f)):
                        tmp_cfg["extends"] = f"./{_f}"
                        break
                if ignore_patterns:
                    tmp_cfg["ignore"] = ignore_patterns
                if ignore_deps:
                    tmp_cfg["ignoreDependencies"] = ignore_deps
                tmp_config_path = os.path.join(project_root, "_sm_knip.json")
                with open(tmp_config_path, "w") as f:
                    json.dump(tmp_cfg, f)
                cmd.extend(["--config", "_sm_knip.json"])

        try:
            result = self._run_command(cmd, cwd=project_root, timeout=120)
        finally:
            if tmp_config_path and os.path.exists(tmp_config_path):
                os.unlink(tmp_config_path)
        duration = time.time() - start_time

        if result.timed_out:
            msg = "Dead code check timed out after 2 minutes"
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=result.output,
                error=msg,
                findings=[Finding(message=msg, level=FindingLevel.ERROR)],
            )

        if result.success:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=result.output,
            )

        findings = self._parse_knip_output(result.stdout)
        if not findings:
            # Non-JSON error (missing package.json, config parse error, etc.)
            err = result.output.strip() or "knip exited with errors"
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                output=result.output,
                error=err,
                findings=[Finding(message=err, level=FindingLevel.ERROR)],
            )

        msg = f"{len(findings)} dead code issue(s) found"
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=result.output,
            error=msg,
            fix_suggestion=(
                "Remove unused exports/files or add consumers. "
                "For tooling entry points (jest configs, .detoxrc.js, scripts/), "
                "add them to ignore_patterns via: "
                "sm config laziness:dead-code.js set ignore_patterns "
                "['<glob>,...']. "
                "For deps used via config (not imports), use ignore_dependencies. "
                "Re-check: sm swab -g laziness:dead-code.js --verbose"
            ),
            findings=findings,
        )

    def _parse_knip_output(self, stdout: str) -> List[Finding]:
        """Parse knip --reporter json output into Finding objects.

        Handles both legacy bare-array format (knip <5) and the
        {"issues": [...]} envelope format used by knip 5+/6+.
        """
        if not stdout.strip():
            return []

        try:
            raw: Any = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            return []

        # knip 5+/6+ wraps the array: {"issues": [...]}
        if isinstance(raw, dict):
            raw = cast(Dict[str, Any], raw).get("issues") or []

        if not isinstance(raw, list):
            return []

        findings: List[Finding] = []
        raw_entry: Any
        for raw_entry in cast(List[Any], raw):
            if not isinstance(raw_entry, dict):
                continue
            file_entry = cast(Dict[str, Any], raw_entry)
            filepath: str = file_entry.get("file") or ""

            if file_entry.get("files") is True:
                findings.append(
                    Finding(
                        message=f"Unused file: {filepath}",
                        level=FindingLevel.WARNING,
                        file=filepath,
                    )
                )
                continue

            findings.extend(self._parse_symbol_findings(file_entry, filepath))
            findings.extend(self._parse_member_findings(file_entry, filepath))

        return findings

    def _parse_symbol_findings(
        self, file_entry: Dict[str, Any], filepath: str
    ) -> List[Finding]:
        """Parse flat symbol-level knip issues (exports, types, duplicates, unresolved)."""
        findings: List[Finding] = []
        for issue_type in ("exports", "types", "unresolved", "duplicates"):
            raw_symbols: Any = file_entry.get(issue_type)
            if not raw_symbols:
                continue
            symbols: List[Any]
            if issue_type == "duplicates":
                flat: List[Any] = []
                for group in raw_symbols:
                    if isinstance(group, list):
                        flat.extend(cast(List[Any], group))
                    else:
                        flat.append(group)
                symbols = flat
            else:
                symbols = raw_symbols
            for raw_sym in symbols:
                if not isinstance(raw_sym, dict):
                    continue
                sym = cast(Dict[str, Any], raw_sym)
                name: str = sym.get("name") or ""
                line: Optional[int] = sym.get("line")
                col: Optional[int] = sym.get("col")
                findings.append(
                    Finding(
                        message=f"Unused {issue_type.rstrip('s')}: {name}",
                        level=FindingLevel.WARNING,
                        file=filepath,
                        line=line,
                        column=col,
                    )
                )
        return findings

    def _parse_member_findings(
        self, file_entry: Dict[str, Any], filepath: str
    ) -> List[Finding]:
        """Parse nested member knip issues (enumMembers, classMembers)."""
        findings: List[Finding] = []
        for issue_type in ("enumMembers", "classMembers"):
            raw_members_map: Any = file_entry.get(issue_type)
            if not isinstance(raw_members_map, dict):
                continue
            members_map = cast(Dict[str, Any], raw_members_map)
            for parent_name, raw_members in members_map.items():
                if not isinstance(raw_members, list):
                    continue
                raw_member: Any
                for raw_member in cast(List[Any], raw_members):
                    if not isinstance(raw_member, dict):
                        continue
                    sym = cast(Dict[str, Any], raw_member)
                    name: str = sym.get("name") or ""
                    line: Optional[int] = sym.get("line")
                    col: Optional[int] = sym.get("col")
                    findings.append(
                        Finding(
                            message=f"Unused {issue_type[:-1]}: {parent_name}.{name}",
                            level=FindingLevel.WARNING,
                            file=filepath,
                            line=line,
                            column=col,
                        )
                    )
        return findings
