"""Config debt detection — surfaces stale, disabled, or scoped-out config.

LLM agents commonly adjust configuration to make gates pass rather than
fixing the underlying issues, or run ``sm init`` once and never revisit
the config as the project evolves.  This check audits the current
``.sb_config.json`` for three classes of configuration debt:

1. **Stale applicability** — Language-specific gates (``py-*``, ``js-*``)
   are disabled but the project now contains markers for that language.
   This typically happens when ``sm init`` ran before the language was
   added.

2. **Disabled gates** — Gates explicitly turned off via
   ``sm config --disable`` (the top-level ``disabled_gates`` list).
   Disabling is legitimate short-term, but the intent should be to
   re-enable once the underlying debt is addressed.

3. **Scope drift** — The current config's ``include_dirs`` /
   ``exclude_dirs`` differ from the baseline that ``sm init`` would
   generate.  Extra excludes or missing includes suggest someone
   narrowed the scope to make gates pass rather than fixing issues.

The check always returns WARNED (never FAILED).  Its purpose is to
nudge toward addressing config debt over time, not to block work.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, cast

from slopmop.checks.base import BaseCheck, Flaw, GateCategory, ToolContext
from slopmop.core.result import CheckResult, CheckStatus

logger = logging.getLogger(__name__)

CONFIG_FILE = ".sb_config.json"

# Gate-name prefixes that imply a specific language.
_LANGUAGE_PREFIXES: Dict[str, str] = {
    "py-": "python",
    "js-": "javascript",
}


def _has_python_markers(root: Path) -> bool:
    """Quick check for Python project markers (no full file scan)."""
    for marker in ("setup.py", "pyproject.toml", "requirements.txt", "Pipfile"):
        if (root / marker).exists():
            return True
    return False


def _has_javascript_markers(root: Path) -> bool:
    """Quick check for JavaScript/TypeScript project markers."""
    for marker in ("package.json", "tsconfig.json"):
        if (root / marker).exists():
            return True
    return False


_LANGUAGE_DETECTORS: Dict[str, Callable[[Path], bool]] = {
    "python": _has_python_markers,
    "javascript": _has_javascript_markers,
}


# ── Public helpers (exposed for testing) ──────────────────────────────


def check_stale_applicability(
    root: Path,
    config: Dict[str, Any],
    explicitly_disabled: Set[str],
) -> List[str]:
    """Detect language gates disabled in config but applicable to project.

    Returns one finding per language, not per gate, to keep output
    concise.  Gates already in *explicitly_disabled* are skipped
    because they are reported separately.
    """
    # Detect which languages the project currently has
    detected: Set[str] = {
        lang for lang, detector in _LANGUAGE_DETECTORS.items() if detector(root)
    }
    if not detected:
        return []

    # Walk flaw-based categories in config
    flaw_keys = {cat.key for cat in GateCategory}
    stale_by_lang: Dict[str, List[str]] = {}

    for cat_key in flaw_keys:
        cat_val_raw = config.get(cat_key)
        if not isinstance(cat_val_raw, dict):
            continue
        cat_val: Dict[str, Any] = cast(Dict[str, Any], cat_val_raw)

        cat_enabled: bool = bool(cat_val.get("enabled", False))
        gates_raw = cat_val.get("gates", {})
        if not isinstance(gates_raw, dict):
            continue
        gates: Dict[str, Any] = cast(Dict[str, Any], gates_raw)

        for gate_name, gate_cfg_raw in gates.items():
            if not isinstance(gate_cfg_raw, dict):
                continue
            gate_cfg: Dict[str, Any] = cast(Dict[str, Any], gate_cfg_raw)

            full_name = f"{cat_key}:{gate_name}"

            # Skip gates already in disabled_gates list (handled separately)
            if full_name in explicitly_disabled:
                continue

            # Is this gate effectively disabled?
            gate_on: bool = bool(gate_cfg.get("enabled", False))
            if cat_enabled and gate_on:
                continue  # Gate is active — no debt

            # Does it match a language present in the project?
            for prefix, lang in _LANGUAGE_PREFIXES.items():
                if gate_name.startswith(prefix) and lang in detected:
                    stale_by_lang.setdefault(lang, []).append(full_name)
                    break

    findings: List[str] = []
    for lang in sorted(stale_by_lang):
        lang_gates = stale_by_lang[lang]
        names = ", ".join(sorted(lang_gates))
        findings.append(
            f"{len(lang_gates)} {lang} gate(s) disabled but {lang} "
            f"code detected — consider re-running sm init ({names})"
        )
    return findings


def check_disabled_gates(explicitly_disabled: Set[str]) -> List[str]:
    """Report gates in the disabled_gates top-level list."""
    if not explicitly_disabled:
        return []
    return [
        f"{g}: explicitly disabled — consider re-enabling"
        for g in sorted(explicitly_disabled)
    ]


def check_scope_drift(
    config: Dict[str, Any],
    baseline: Dict[str, Any],
) -> List[str]:
    """Compare include/exclude dirs against the generated baseline.

    Flags two forms of drift:

    * **Extra excludes** — entries in ``exclude_dirs`` that are not in
      the baseline (someone added dirs to hide from gates).
    * **Missing includes** — entries in the baseline ``include_dirs``
      that are absent from the current config (someone narrowed scope).

    *baseline* is the config that ``generate_base_config()`` would
    produce for this project right now.
    """
    findings: List[str] = []
    flaw_keys = {cat.key for cat in GateCategory}

    for cat_key in flaw_keys:
        cur_raw = config.get(cat_key)
        base_raw = baseline.get(cat_key)
        if not isinstance(cur_raw, dict) or not isinstance(base_raw, dict):
            continue
        cur_cat: Dict[str, Any] = cast(Dict[str, Any], cur_raw)
        base_cat: Dict[str, Any] = cast(Dict[str, Any], base_raw)

        # --- Extra excludes ------------------------------------------------
        cur_excludes: Set[str] = _str_set(cur_cat.get("exclude_dirs", []))
        base_excludes: Set[str] = _str_set(base_cat.get("exclude_dirs", []))
        added_excludes = sorted(cur_excludes - base_excludes)
        if added_excludes:
            dirs = ", ".join(added_excludes)
            findings.append(
                f"{cat_key}: {len(added_excludes)} extra exclude_dirs "
                f"beyond baseline — {dirs}"
            )

        # --- Missing includes ----------------------------------------------
        cur_includes: Set[str] = _str_set(cur_cat.get("include_dirs", []))
        base_includes: Set[str] = _str_set(base_cat.get("include_dirs", []))
        missing_includes = sorted(base_includes - cur_includes)
        if missing_includes:
            dirs = ", ".join(missing_includes)
            findings.append(
                f"{cat_key}: {len(missing_includes)} include_dirs removed "
                f"from baseline — {dirs}"
            )

    return findings


def _str_set(val: object) -> Set[str]:
    """Coerce an unknown value to a set of strings."""
    if not isinstance(val, list):
        return set()
    return {str(item) for item in cast(List[object], val) if isinstance(item, str)}


# ── Check class ───────────────────────────────────────────────────────


class ConfigDebtCheck(BaseCheck):
    """Config debt detection — surfaces stale, disabled, or scoped-out config.

    Detects three forms of configuration debt:

    1. **Stale applicability** — Language-specific gates (``py-*``,
       ``js-*``) disabled but the project now has that language.
    2. **Disabled gates** — Gates in the ``disabled_gates`` top-level
       list (set via ``sm config --disable``).
    3. **Scope drift** — ``include_dirs`` / ``exclude_dirs`` differ
       from the generated baseline (extra excludes or missing includes).

    Always returns WARNED (never FAILED) — this is a nudge, not a
    blocker.

    Re-check:
      ./sm swab -g laziness:config-debt
    """

    tool_context = ToolContext.PURE

    @property
    def name(self) -> str:
        return "config-debt"

    @property
    def display_name(self) -> str:
        return "🧹 Config Debt"

    @property
    def category(self) -> GateCategory:
        return GateCategory.LAZINESS

    @property
    def flaw(self) -> Flaw:
        return Flaw.LAZINESS

    def is_applicable(self, project_root: str) -> bool:
        """Applicable whenever a config file exists."""
        return (Path(project_root) / CONFIG_FILE).exists()

    def skip_reason(self, project_root: str) -> str:
        return "No .sb_config.json found"

    def run(self, project_root: str) -> CheckResult:
        start = time.time()
        root = Path(project_root)

        config = _load_config(root)
        if config is None:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=time.time() - start,
                output="Could not parse config — skipping debt check",
            )

        # Collect disabled_gates first so stale-applicability can skip them
        disabled_val: object = config.get("disabled_gates")
        explicitly_disabled: Set[str] = (
            {str(item) for item in cast(List[object], disabled_val)}
            if isinstance(disabled_val, list)
            else set()
        )

        findings: List[str] = []
        findings.extend(check_stale_applicability(root, config, explicitly_disabled))
        findings.extend(check_disabled_gates(explicitly_disabled))
        from slopmop.utils.generate_base_config import generate_base_config

        baseline = generate_base_config()
        findings.extend(check_scope_drift(config, baseline))

        duration = time.time() - start

        if not findings:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output="Config is healthy — no debt detected",
            )

        lines = [f"{len(findings)} config debt item(s):"]
        for f in findings:
            lines.append(f"  • {f}")

        return self._create_result(
            status=CheckStatus.WARNED,
            duration=duration,
            output="\n".join(lines),
            error=f"{len(findings)} config debt item(s)",
        )


def _load_config(root: Path) -> Optional[Dict[str, Any]]:
    """Load .sb_config.json from project root."""
    try:
        return json.loads((root / CONFIG_FILE).read_text())
    except (json.JSONDecodeError, OSError):
        return None
