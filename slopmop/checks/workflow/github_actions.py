"""GitHub Actions workflow hygiene checks."""

from __future__ import annotations

import ast
import re
import shutil
import time
from pathlib import Path
from typing import ClassVar, Iterable, Iterator, List, Optional, cast

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    GateLevel,
    RemediationChurn,
    ToolContext,
)
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel

_WORKFLOW_EXTENSIONS = frozenset({".yml", ".yaml"})
_PYTHON_HEREDOC_RE = re.compile(
    r"\b(?:python|python3(?:\.\d+)?)\b.*<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?"
)
_ACTIONLINT_RE = re.compile(r"^(.*?):(\d+):(\d+):\s*(.*?)(?:\s+\[(.+)\])?$")
_DEPRECATED_ACTION_MIN_MAJOR = {
    "actions/checkout": (5, "actions/checkout@v5"),
    "actions/setup-python": (6, "actions/setup-python@v6"),
    "actions/setup-node": (6, "actions/setup-node@v6"),
}
_OIDC_ACTIONS = {
    "pypa/gh-action-pypi-publish",
}
_CODECOV_ACTION = "codecov/codecov-action"
WorkflowMap = dict[str, object]
Permissions = dict[str, object] | str | None


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _workflow_files(root: Path, workflow_dirs: Iterable[str]) -> List[Path]:
    files: List[Path] = []
    for directory in workflow_dirs:
        workflow_dir = root / directory
        if not workflow_dir.exists():
            continue
        for path in sorted(workflow_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in _WORKFLOW_EXTENSIONS:
                files.append(path)
    return files


def _load_workflow(path: Path) -> tuple[Optional[WorkflowMap], Optional[Finding]]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return None, Finding(
            message="PyYAML is required to parse GitHub Actions workflow files",
            level=FindingLevel.WARNING,
            file=path.as_posix(),
            fix_strategy="Install slopmop with its runtime dependencies, including PyYAML.",
        )

    try:
        loaded = cast(object, yaml.safe_load(path.read_text(encoding="utf-8")))
        if loaded is None:
            return {}, None
        if not isinstance(loaded, dict):
            return {}, None
        return cast(WorkflowMap, loaded), None
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = getattr(mark, "line", None)
        column = getattr(mark, "column", None)
        return None, Finding(
            message=f"Workflow YAML does not parse: {exc}",
            level=FindingLevel.ERROR,
            file=path.as_posix(),
            line=line + 1 if isinstance(line, int) else None,
            column=column + 1 if isinstance(column, int) else None,
            rule_id="workflow-yaml-parse",
            fix_strategy="Fix the YAML syntax before relying on this workflow in CI.",
        )


def _iter_jobs(workflow: WorkflowMap) -> Iterator[tuple[str, WorkflowMap]]:
    jobs_obj = workflow.get("jobs")
    if not isinstance(jobs_obj, dict):
        return
    jobs = cast(dict[object, object], jobs_obj)
    for job_name_obj, job_obj in jobs.items():
        if isinstance(job_name_obj, str) and isinstance(job_obj, dict):
            yield job_name_obj, cast(WorkflowMap, job_obj)


def _iter_steps(job: WorkflowMap) -> Iterator[WorkflowMap]:
    steps_obj = job.get("steps")
    if not isinstance(steps_obj, list):
        return
    steps = cast(list[object], steps_obj)
    for step_obj in steps:
        if isinstance(step_obj, dict):
            yield cast(WorkflowMap, step_obj)


def _line_for_text(lines: list[str], needle: str) -> Optional[int]:
    for index, line in enumerate(lines, 1):
        if needle in line:
            return index
    return None


def _line_for_uses(lines: list[str], uses_value: str) -> Optional[int]:
    for index, line in enumerate(lines, 1):
        if "uses:" in line and uses_value in line:
            return index
    return None


def _permissions_allow(
    permissions: Permissions,
    permission: str,
    required: str,
) -> bool:
    if permissions == "write-all":
        return True
    if permissions == "read-all":
        return required == "read"
    if not isinstance(permissions, dict):
        return False

    value = permissions.get(permission)
    if required == "read":
        return value in {"read", "write"}
    return value == "write"


def _effective_permissions(workflow: WorkflowMap, job: WorkflowMap) -> Permissions:
    if "permissions" in job:
        return _as_permissions(job.get("permissions"))
    if "permissions" in workflow:
        return _as_permissions(workflow.get("permissions"))
    return None


def _as_permissions(value: object) -> Permissions:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    return None


def _action_ref(uses_value: str) -> tuple[str, str]:
    if "@" not in uses_value:
        return uses_value.lower(), ""
    name, version = uses_value.rsplit("@", 1)
    return name.lower(), version


def _major(version: str) -> Optional[int]:
    match = re.match(r"v(\d+)(?:\b|\.)", version)
    if not match:
        return None
    return int(match.group(1))


def _uses_checkout(step: WorkflowMap) -> bool:
    uses = step.get("uses")
    if not isinstance(uses, str):
        return False
    action, _version = _action_ref(uses)
    return action == "actions/checkout"


def _uses_oidc_publish(step: WorkflowMap) -> bool:
    uses = step.get("uses")
    if isinstance(uses, str):
        action, _version = _action_ref(uses)
        if action in _OIDC_ACTIONS:
            return True
        if action == _CODECOV_ACTION:
            with_block = step.get("with")
            return (
                isinstance(with_block, dict)
                and str(cast(dict[str, object], with_block).get("use_oidc", "")).lower()
                == "true"
            )

    run = step.get("run")
    if not isinstance(run, str):
        return False
    lower_run = run.lower()
    return "npm publish" in lower_run and "--provenance" in lower_run


def _extract_python_heredocs(run_block: str) -> Iterable[tuple[int, str]]:
    lines = run_block.splitlines()
    index = 0
    while index < len(lines):
        match = _PYTHON_HEREDOC_RE.search(lines[index])
        if not match:
            index += 1
            continue

        delimiter = match.group(1)
        code_start = index + 1
        code_lines: list[str] = []
        index += 1
        while index < len(lines) and lines[index].strip() != delimiter:
            code_lines.append(lines[index])
            index += 1
        yield code_start + 1, "\n".join(code_lines)
        index += 1


class GitHubActionsHygieneCheck(BaseCheck):
    """Preflight GitHub Actions workflows before they fail at runtime."""

    tool_context: ClassVar[ToolContext] = ToolContext.PURE
    role = CheckRole.DIAGNOSTIC
    level = GateLevel.SWAB
    remediation_churn = RemediationChurn.DOWNSTREAM_CHANGES_VERY_UNLIKELY

    @property
    def name(self) -> str:
        return "github-actions-hygiene"

    @property
    def display_name(self) -> str:
        return "⚙️ GitHub Actions Hygiene"

    @property
    def gate_description(self) -> str:
        return "Pre-parses GitHub Actions workflows and catches CI runtime traps"

    @property
    def category(self) -> GateCategory:
        return GateCategory.MYOPIA

    @property
    def flaw(self) -> Flaw:
        return Flaw.MYOPIA

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="workflow_dirs",
                field_type="string[]",
                default=[".github/workflows"],
                description="Directories containing GitHub Actions workflow YAML files",
            ),
            ConfigField(
                name="run_actionlint",
                field_type="boolean",
                default=True,
                description="Run actionlint when the executable is available on PATH",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        root = Path(project_root)
        workflow_dirs = self.config.get("workflow_dirs") or [".github/workflows"]
        return bool(_workflow_files(root, workflow_dirs))

    def skip_reason(self, project_root: str) -> str:
        return "No GitHub Actions workflow files found"

    def run(self, project_root: str) -> CheckResult:
        start = time.perf_counter()
        root = Path(project_root)
        workflow_dirs = self.config.get("workflow_dirs") or [".github/workflows"]
        workflows = _workflow_files(root, workflow_dirs)
        findings: list[Finding] = []
        actionlint_available = False

        for path in workflows:
            rel_path = _rel(path, root)
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            workflow, parse_finding = _load_workflow(path)
            if parse_finding:
                findings.append(self._with_repo_relative_file(parse_finding, root))
                continue
            if workflow is None:
                continue

            findings.extend(self._workflow_findings(workflow, rel_path, lines))
            findings.extend(self._actionlint_findings(path, root))
            actionlint_available = (
                actionlint_available or shutil.which("actionlint") is not None
            )

        elapsed = time.perf_counter() - start
        if not findings:
            note = (
                "actionlint checked"
                if actionlint_available
                else "actionlint not installed"
            )
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=elapsed,
                output=f"GitHub Actions hygiene passed ({len(workflows)} workflow files, {note})",
            )

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=elapsed,
            output="\n".join(str(finding) for finding in findings[:30]),
            error=f"Found {len(findings)} GitHub Actions hygiene issue(s)",
            fix_suggestion=(
                "Fix the workflow findings above, then verify with: "
                + self.verify_command
            ),
            findings=findings,
        )

    def _workflow_findings(
        self,
        workflow: WorkflowMap,
        rel_path: str,
        lines: list[str],
    ) -> list[Finding]:
        findings: list[Finding] = []
        for job_name, job in _iter_jobs(workflow):
            permissions = _effective_permissions(workflow, job)
            for step in _iter_steps(job):
                uses = step.get("uses")
                if isinstance(uses, str):
                    findings.extend(
                        self._deprecated_action_findings(uses, rel_path, lines)
                    )
                if _uses_checkout(step):
                    findings.extend(
                        self._checkout_permission_findings(
                            permissions, job_name, rel_path, lines
                        )
                    )
                if _uses_oidc_publish(step):
                    findings.extend(
                        self._id_token_findings(permissions, job_name, rel_path, lines)
                    )
                run = step.get("run")
                if isinstance(run, str):
                    findings.extend(self._python_heredoc_findings(run, rel_path, lines))
        return findings

    def _deprecated_action_findings(
        self,
        uses_value: str,
        rel_path: str,
        lines: list[str],
    ) -> list[Finding]:
        action, version = _action_ref(uses_value)
        policy = _DEPRECATED_ACTION_MIN_MAJOR.get(action)
        major = _major(version)
        if not policy or major is None or major >= policy[0]:
            return []
        replacement = policy[1]
        return [
            Finding(
                message=f"Deprecated GitHub Action runtime: {uses_value}",
                level=FindingLevel.ERROR,
                file=rel_path,
                line=_line_for_uses(lines, uses_value),
                rule_id="deprecated-action-version",
                fix_strategy=f"Upgrade to {replacement} or a newer supported major.",
            )
        ]

    def _checkout_permission_findings(
        self,
        permissions: Permissions,
        job_name: str,
        rel_path: str,
        lines: list[str],
    ) -> list[Finding]:
        if permissions is None or _permissions_allow(permissions, "contents", "read"):
            return []
        return [
            Finding(
                message=(
                    f"Job '{job_name}' uses actions/checkout but effective permissions "
                    "do not grant contents: read"
                ),
                level=FindingLevel.ERROR,
                file=rel_path,
                line=_line_for_text(lines, "permissions:"),
                rule_id="checkout-missing-contents-read",
                fix_strategy="Add contents: read to the workflow or job permissions block.",
            )
        ]

    def _id_token_findings(
        self,
        permissions: Permissions,
        job_name: str,
        rel_path: str,
        lines: list[str],
    ) -> list[Finding]:
        if _permissions_allow(permissions, "id-token", "write"):
            return []
        return [
            Finding(
                message=(
                    f"Job '{job_name}' uses an OIDC publish pattern but effective "
                    "permissions do not grant id-token: write"
                ),
                level=FindingLevel.ERROR,
                file=rel_path,
                line=_line_for_text(lines, "permissions:"),
                rule_id="oidc-publish-missing-id-token-write",
                fix_strategy="Add id-token: write to the publishing job permissions block.",
            )
        ]

    def _python_heredoc_findings(
        self,
        run_block: str,
        rel_path: str,
        lines: list[str],
    ) -> list[Finding]:
        findings: list[Finding] = []
        run_start = self._run_start_line(run_block, lines)
        for offset, code in _extract_python_heredocs(run_block):
            try:
                ast.parse(code)
            except SyntaxError as exc:
                finding_line = run_start + offset + (exc.lineno or 1) - 2
                findings.append(
                    Finding(
                        message=f"Embedded Python heredoc does not parse: {exc.msg}",
                        level=FindingLevel.ERROR,
                        file=rel_path,
                        line=finding_line if run_start else None,
                        column=exc.offset,
                        rule_id="embedded-python-parse",
                        fix_strategy="Fix the embedded Python syntax before the workflow runs.",
                    )
                )
        return findings

    def _actionlint_findings(self, path: Path, root: Path) -> list[Finding]:
        if not self.config.get("run_actionlint", True) or not shutil.which(
            "actionlint"
        ):
            return []
        result = self._runner.run(["actionlint", str(path)], cwd=str(root), timeout=30)
        if result.returncode == 0:
            return []
        findings: list[Finding] = []
        for line in result.output.splitlines():
            match = _ACTIONLINT_RE.match(line)
            if not match:
                continue
            file_path, lineno, column, message, rule = match.groups()
            findings.append(
                Finding(
                    message=message,
                    level=FindingLevel.ERROR,
                    file=(
                        Path(file_path).relative_to(root).as_posix()
                        if Path(file_path).is_absolute()
                        else file_path
                    ),
                    line=int(lineno),
                    column=int(column),
                    rule_id=f"actionlint:{rule or 'workflow'}",
                    fix_strategy="Fix the actionlint workflow diagnostic.",
                )
            )
        if findings:
            return findings
        return [
            Finding(
                message=result.output.strip() or "actionlint failed",
                level=FindingLevel.ERROR,
                file=_rel(path, root),
                rule_id="actionlint",
                fix_strategy="Run actionlint locally and fix the reported workflow issue.",
            )
        ]

    @staticmethod
    def _run_start_line(run_block: str, lines: list[str]) -> int:
        first = next((line for line in run_block.splitlines() if line.strip()), "")
        if not first:
            return 0
        return _line_for_text(lines, first.strip()) or 0

    @staticmethod
    def _with_repo_relative_file(finding: Finding, root: Path) -> Finding:
        if not finding.file:
            return finding
        file_path = Path(finding.file)
        try:
            rel_file = file_path.relative_to(root).as_posix()
        except ValueError:
            rel_file = file_path.as_posix()
        return Finding(
            message=finding.message,
            level=finding.level,
            file=rel_file,
            line=finding.line,
            column=finding.column,
            end_line=finding.end_line,
            end_column=finding.end_column,
            rule_id=finding.rule_id,
            fix_strategy=finding.fix_strategy,
        )
