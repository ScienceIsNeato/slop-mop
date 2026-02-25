"""Gate-dodging detection — catches loosened quality gate configs.

AI models commonly loosen quality gate thresholds to make checks pass
rather than fixing the underlying issues.  This check compares the
current ``.sb_config.json`` against the merge-target branch (defaults
to ``origin/main``) and warns when any gate setting has become *more
permissive*.

An escape hatch exists for intentional changes: if a PR comment
(resolved or unresolved) contains the prefix ``[gate-change-justified]``
the warning is suppressed and the check passes.

On the ``commit`` profile (no PR context) the check simply warns
without the escape hatch option.
"""

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from slopmop.checks.base import BaseCheck, ConfigField, Flaw, GateCategory
from slopmop.core.result import CheckResult, CheckStatus

logger = logging.getLogger(__name__)

CONFIG_FILE = ".sb_config.json"

# Severity hierarchy for fail_is_stricter comparisons
_SEVERITY_RANK: Dict[str, int] = {"fail": 2, "warn": 1}

# Justification prefix that suppresses the warning
JUSTIFICATION_PREFIX = "[gate-change-justified]"


def _to_str_set(values: object) -> set[str]:
    """Convert a list-like value to a set of strings for comparison."""
    if isinstance(values, list):
        return {str(v) for v in cast(List[object], values)}
    return set()


@dataclass
class PermissivenessChange:
    """A single config field that became more permissive."""

    gate: str  # e.g. "laziness:complexity"
    field: str  # e.g. "max_complexity"
    old_value: Any
    new_value: Any
    description: str  # human-readable explanation


def _get_base_ref() -> str:
    """Resolve the branch to compare against.

    Precedence: COMPARE_BRANCH env → GITHUB_BASE_REF → origin/main.
    """
    return (
        os.environ.get("COMPARE_BRANCH")
        or os.environ.get("GITHUB_BASE_REF")
        or "origin/main"
    )


def _load_base_config(project_root: str, base_ref: str) -> Optional[Dict[str, Any]]:
    """Load .sb_config.json from the base branch via git show."""
    try:
        result = subprocess.run(
            ["git", "show", f"{base_ref}:{CONFIG_FILE}"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_root,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)  # type: ignore[no-any-return]
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass
    return None


def _load_current_config(project_root: str) -> Optional[Dict[str, Any]]:
    """Load .sb_config.json from the working tree."""
    config_path = Path(project_root) / CONFIG_FILE
    if not config_path.exists():
        return None
    try:
        return json.loads(config_path.read_text())  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        return None


def _is_more_permissive(
    permissiveness: str,
    old_value: object,
    new_value: object,
) -> bool:
    """Determine if a config change is more permissive.

    Args:
        permissiveness: The permissiveness type from ConfigField
        old_value: Value on the base branch
        new_value: Value in the current config

    Returns:
        True if the change makes the gate looser
    """
    if old_value == new_value:
        return False

    if permissiveness == "higher_is_stricter":
        # Higher = stricter, so new < old = more permissive
        if isinstance(new_value, (int, float)) and isinstance(old_value, (int, float)):
            return new_value < old_value
        if isinstance(new_value, str) and isinstance(old_value, str):
            return new_value < old_value
        return False

    if permissiveness == "lower_is_stricter":
        # Lower = stricter, so new > old = more permissive
        if isinstance(new_value, (int, float)) and isinstance(old_value, (int, float)):
            return new_value > old_value
        # Support ordered string values (e.g. complexity rank "A" < "C" < "F")
        if isinstance(new_value, str) and isinstance(old_value, str):
            return new_value > old_value
        return False

    if permissiveness == "fewer_is_stricter":
        # Fewer list items = stricter.
        # More permissive if new has items not in old (exclusions added).
        new_strs: set[str] = _to_str_set(new_value)
        old_strs: set[str] = _to_str_set(old_value)
        if new_strs or old_strs:
            return bool(new_strs - old_strs)
        return False

    if permissiveness == "more_is_stricter":
        # More list items = stricter.
        # More permissive if old has items not in new (inclusions removed).
        new_strs_m: set[str] = _to_str_set(new_value)
        old_strs_m: set[str] = _to_str_set(old_value)
        if new_strs_m or old_strs_m:
            return bool(old_strs_m - new_strs_m)
        return False

    if permissiveness == "fail_is_stricter":
        old_rank = _SEVERITY_RANK.get(str(old_value).lower(), 0)
        new_rank = _SEVERITY_RANK.get(str(new_value).lower(), 0)
        return new_rank < old_rank

    if permissiveness == "true_is_stricter":
        # True = stricter, so old=True new=False = more permissive
        return bool(old_value) and not bool(new_value)

    return False


def _describe_change(
    permissiveness: str, field_name: str, old_value: object, new_value: object
) -> str:
    """Produce a human-readable description of a permissiveness change."""
    if permissiveness == "true_is_stricter":
        return f"{field_name}: enabled → disabled"

    if permissiveness == "fail_is_stricter":
        return f"{field_name}: {old_value} → {new_value}"

    if permissiveness in ("fewer_is_stricter", "more_is_stricter"):
        new_s: set[str] = _to_str_set(new_value)
        old_s: set[str] = _to_str_set(old_value)
        if new_s or old_s:
            if permissiveness == "fewer_is_stricter":
                added: set[str] = new_s - old_s
                return f"{field_name}: added exclusions {sorted(added)}"
            removed: set[str] = old_s - new_s
            return f"{field_name}: removed entries {sorted(removed)}"

    return f"{field_name}: {old_value} → {new_value}"


def _build_schema_lookup() -> Dict[str, Dict[str, ConfigField]]:
    """Build {gate_full_name: {field_name: ConfigField}} from the registry.

    Imports are deferred to avoid circular imports at module level.
    """
    from slopmop.checks import ensure_checks_registered
    from slopmop.core.registry import get_registry

    ensure_checks_registered()
    registry = get_registry()

    lookup: Dict[str, Dict[str, ConfigField]] = {}
    for full_name, check_class in registry._check_classes.items():
        instance = check_class({})
        fields: Dict[str, ConfigField] = {}
        for cf in instance.get_full_config_schema():
            fields[cf.name] = cf
        lookup[full_name] = fields
    return lookup


def _detect_loosened_gates(
    base_config: Dict[str, Any],
    current_config: Dict[str, Any],
    schema_lookup: Dict[str, Dict[str, ConfigField]],
) -> List[PermissivenessChange]:
    """Compare two configs and return any fields that became more permissive.

    Walks the config structure:
      { category_key: { "enabled": bool, "gates": { gate_name: { ... } } } }
    and checks each field against the schema's permissiveness metadata.
    """
    changes: List[PermissivenessChange] = []

    # Collect all category keys present in either config
    all_categories: set[str] = set(base_config.keys()) | set(current_config.keys())
    # Skip non-category keys
    skip_keys: set[str] = {"version", "default_profile"}

    for cat_key in sorted(all_categories - skip_keys):
        base_cat_raw: object = base_config.get(cat_key, {})
        curr_cat_raw: object = current_config.get(cat_key, {})

        if not isinstance(base_cat_raw, dict) or not isinstance(curr_cat_raw, dict):
            continue

        base_cat: Dict[str, object] = cast(Dict[str, object], base_cat_raw)
        curr_cat: Dict[str, object] = cast(Dict[str, object], curr_cat_raw)

        # Check category-level enabled
        base_enabled: bool = bool(base_cat.get("enabled", True))
        curr_enabled: bool = bool(curr_cat.get("enabled", True))
        if base_enabled and not curr_enabled:
            changes.append(
                PermissivenessChange(
                    gate=cat_key,
                    field="enabled",
                    old_value=True,
                    new_value=False,
                    description=f"entire '{cat_key}' category disabled",
                )
            )

        # Walk gates
        base_gates_raw: object = base_cat.get("gates", {})
        curr_gates_raw: object = curr_cat.get("gates", {})

        if not isinstance(base_gates_raw, dict) or not isinstance(curr_gates_raw, dict):
            continue

        base_gates: Dict[str, object] = cast(Dict[str, object], base_gates_raw)
        curr_gates: Dict[str, object] = cast(Dict[str, object], curr_gates_raw)

        all_gate_names: set[str] = set(base_gates.keys()) | set(curr_gates.keys())

        for gate_name in sorted(all_gate_names):
            full_name: str = f"{cat_key}:{gate_name}"
            base_gate_raw: object = base_gates.get(gate_name, {})
            curr_gate_raw: object = curr_gates.get(gate_name, {})

            if not isinstance(base_gate_raw, dict) or not isinstance(
                curr_gate_raw, dict
            ):
                continue

            base_gate: Dict[str, object] = cast(Dict[str, object], base_gate_raw)
            curr_gate: Dict[str, object] = cast(Dict[str, object], curr_gate_raw)

            # Get schema for this gate
            schema_fields: Dict[str, ConfigField] = schema_lookup.get(full_name, {})

            # Check each field that exists in either base or current gate config
            all_fields: set[str] = set(base_gate.keys()) | set(curr_gate.keys())
            for field_name in sorted(all_fields):
                old_val: object = base_gate.get(field_name)
                new_val: object = curr_gate.get(field_name)

                if old_val == new_val:
                    continue

                # Handle cases where the field wasn't present at all
                if old_val is None or new_val is None:
                    # Field added or removed — skip unless it's 'enabled'
                    if field_name != "enabled":
                        continue

                cf: Optional[ConfigField] = schema_fields.get(field_name)
                if cf is None or cf.permissiveness is None:
                    continue

                if _is_more_permissive(cf.permissiveness, old_val, new_val):
                    changes.append(
                        PermissivenessChange(
                            gate=full_name,
                            field=field_name,
                            old_value=old_val,
                            new_value=new_val,
                            description=_describe_change(
                                cf.permissiveness,
                                field_name,
                                old_val,
                                new_val,
                            ),
                        )
                    )

    return changes


def _detect_pr_number(project_root: str) -> Optional[int]:
    """Detect PR number from env or git branch (mirrors PRCommentsCheck)."""
    for env_var in ["GITHUB_PR_NUMBER", "PR_NUMBER", "PULL_REQUEST_NUMBER"]:
        val = os.environ.get(env_var)
        if val:
            try:
                return int(val)
            except ValueError:
                pass

    github_ref = os.environ.get("GITHUB_REF", "")
    if github_ref.startswith("refs/pull/"):
        try:
            return int(github_ref.split("/")[2])
        except (ValueError, IndexError):
            pass

    try:
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=project_root,
        )
        if branch_result.returncode != 0 or not branch_result.stdout.strip():
            return None

        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--head",
                branch_result.stdout.strip(),
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
                return data[0].get("number")  # type: ignore[no-any-return]
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass

    return None


def _check_justification_comment(project_root: str, pr_number: int) -> bool:
    """Check if any PR comment contains the justification prefix."""
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--comments",
                "--json",
                "comments",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=project_root,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            for comment in data.get("comments", []):
                body = comment.get("body", "")
                if JUSTIFICATION_PREFIX in body:
                    return True

        # Also check review comments (inline)
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--json",
                "reviews",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=project_root,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            for review in data.get("reviews", []):
                body = review.get("body", "")
                if JUSTIFICATION_PREFIX in body:
                    return True

    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass

    return False


class GateDodgingCheck(BaseCheck):
    """Detect loosened quality gate configurations.

    Compares the current ``.sb_config.json`` against the merge-target
    branch (defaults to ``origin/main``) using each gate's schema-
    declared ``permissiveness`` metadata. Warns when any setting has
    become more permissive.

    AI models frequently loosen thresholds, raise limits, or add
    exclusion patterns to make checks pass instead of addressing the
    root cause. This check catches that pattern early.

    Profiles: commit, pr

    Configuration:
      base_ref: "" — branch to compare against. Empty string
          uses automatic detection (COMPARE_BRANCH env,
          GITHUB_BASE_REF env, or origin/main).

    Escape hatch:
      Add a PR comment containing ``[gate-change-justified]``
      followed by your reasoning. The check will pass once the
      justification comment exists.

    Common failures:
      Loosened thresholds: Revert the config change and fix the
          underlying issue instead.
      Added exclusions: If legitimate, add a justification comment.
      Disabled gate: Re-enable the gate and fix the failing code.

    Re-validate:
      ./sm validate deceptiveness:gate-dodging --verbose
    """

    @property
    def name(self) -> str:
        return "gate-dodging"

    @property
    def display_name(self) -> str:
        return "🎭 Gate Dodging"

    @property
    def category(self) -> GateCategory:
        return GateCategory.DECEPTIVENESS

    @property
    def flaw(self) -> Flaw:
        return Flaw.DECEPTIVENESS

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="base_ref",
                field_type="string",
                default="",
                description=(
                    "Branch to compare against. Empty = auto-detect "
                    "(COMPARE_BRANCH env, GITHUB_BASE_REF, or origin/main)"
                ),
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        """Applicable when project is a git repo with a config file."""
        git_dir = Path(project_root) / ".git"
        config_path = Path(project_root) / CONFIG_FILE
        return git_dir.is_dir() and config_path.exists()

    def skip_reason(self, project_root: str) -> str:
        git_dir = Path(project_root) / ".git"
        if not git_dir.is_dir():
            return "Not a git repository"
        config_path = Path(project_root) / CONFIG_FILE
        if not config_path.exists():
            return f"No {CONFIG_FILE} found (project uses defaults)"
        return "Gate-dodging check not applicable"

    def run(self, project_root: str) -> CheckResult:
        """Compare current config against base branch for loosened gates."""
        start = time.monotonic()

        # Determine base ref
        configured_ref = self.config.get("base_ref", "")
        base_ref = configured_ref if configured_ref else _get_base_ref()

        # Load configs
        current_config = _load_current_config(project_root)
        if current_config is None:
            return self._create_result(
                CheckStatus.PASSED,
                time.monotonic() - start,
                output=f"No {CONFIG_FILE} found or unreadable — nothing to compare",
            )

        base_config = _load_base_config(project_root, base_ref)
        if base_config is None:
            # Config file is new (doesn't exist on base branch) — initial setup
            return self._create_result(
                CheckStatus.PASSED,
                time.monotonic() - start,
                output=(
                    f"{CONFIG_FILE} not found on {base_ref} — "
                    "initial config setup (not gate-dodging)"
                ),
            )

        # Build schema lookup from registry
        schema_lookup = _build_schema_lookup()

        # Detect loosened gates
        changes = _detect_loosened_gates(base_config, current_config, schema_lookup)

        if not changes:
            return self._create_result(
                CheckStatus.PASSED,
                time.monotonic() - start,
                output=f"No permissiveness changes detected vs {base_ref}",
            )

        # We found loosened gates — check for justification on PR
        pr_number = _detect_pr_number(project_root)
        if pr_number is not None:
            if _check_justification_comment(project_root, pr_number):
                lines = [
                    f"Config loosened vs {base_ref} (justified via PR comment):",
                ]
                for c in changes:
                    lines.append(f"  {c.gate} — {c.description}")
                return self._create_result(
                    CheckStatus.PASSED,
                    time.monotonic() - start,
                    output="\n".join(lines),
                )

        # Build warning output
        lines = [
            f"⚠️  Gate configuration loosened vs {base_ref}:",
            "",
        ]
        for c in changes:
            lines.append(f"  {c.gate} — {c.description}")

        lines.extend(
            [
                "",
                "AI models often loosen quality gates to avoid fixing actual",
                "issues. If this change is intentional, justify it with a PR",
                "comment containing the prefix:",
                "",
                f'  gh pr comment --body "{JUSTIFICATION_PREFIX} <your reasoning>"',
            ]
        )

        return self._create_result(
            CheckStatus.WARNED,
            time.monotonic() - start,
            output="\n".join(lines),
            fix_suggestion=(
                "Revert the config change and fix the underlying issue, "
                "or add a justification comment with the prefix: "
                f"{JUSTIFICATION_PREFIX}"
            ),
        )
