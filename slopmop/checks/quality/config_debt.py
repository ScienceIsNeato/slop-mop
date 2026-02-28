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

3. **Exclude drift** — ``exclude_dirs`` entries that point at real
   directories containing source code, which hides those files from
   quality gates.

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

# Directories commonly excluded for good reasons — not config debt.
_BENIGN_EXCLUDES: frozenset[str] = frozenset(
    {
        # Build / dependency artifacts
        "node_modules",
        ".venv",
        "venv",
        ".env",
        "env",
        "__pycache__",
        "dist",
        "build",
        ".tox",
        ".nox",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "htmlcov",
        ".coverage",
        ".eggs",
        # VCS
        ".git",
        ".hg",
        ".svn",
        # Meta / documentation / tooling
        "slop-mop",
        "cursor-rules",
        "docs",
        "doc",
        "documentation",
        "migrations",
    }
)

# Source-file extensions used to gauge whether an excluded dir matters.
_SOURCE_EXTENSIONS = ("*.py", "*.js", "*.ts", "*.jsx", "*.tsx")

# If an excluded dir has at least this many source files, flag it.
_EXCLUDE_FILE_THRESHOLD = 5


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


def check_exclude_drift(
    root: Path,
    config: Dict[str, Any],
) -> List[str]:
    """Find exclude_dirs entries that contain source files.

    Skips well-known benign directories, dot-prefixed names, and
    glob patterns.  Only flags directories with at least
    ``_EXCLUDE_FILE_THRESHOLD`` source files.
    """
    findings: List[str] = []
    seen: Set[str] = set()

    flaw_keys = {cat.key for cat in GateCategory}
    for cat_key in flaw_keys:
        cat_val_raw = config.get(cat_key)
        if not isinstance(cat_val_raw, dict):
            continue
        cat_val: Dict[str, Any] = cast(Dict[str, Any], cat_val_raw)

        excl_dirs_raw: object = cat_val.get("exclude_dirs", [])
        if not isinstance(excl_dirs_raw, list):
            continue
        exclude_dirs: List[str] = [
            str(item)
            for item in cast(List[object], excl_dirs_raw)
            if isinstance(item, str)
        ]

        for excl in exclude_dirs:
            if excl in seen:
                continue
            seen.add(excl)

            # Skip well-known benign dirs, dot-dirs, and globs
            if excl in _BENIGN_EXCLUDES or excl.startswith("."):
                continue
            if any(c in excl for c in ("*", "?", "[")):
                continue

            excl_path = root / excl
            if not excl_path.is_dir():
                continue

            # Count source files (cap quickly for speed)
            count = 0
            for ext in _SOURCE_EXTENSIONS:
                for _ in excl_path.rglob(ext):
                    count += 1
                    if count >= _EXCLUDE_FILE_THRESHOLD:
                        break
                if count >= _EXCLUDE_FILE_THRESHOLD:
                    break

            if count >= _EXCLUDE_FILE_THRESHOLD:
                findings.append(
                    f"exclude_dirs '{excl}' contains {count}+ source "
                    f"files — verify this exclusion is intentional "
                    f"({cat_key})"
                )

    return findings


# ── Check class ───────────────────────────────────────────────────────


class ConfigDebtCheck(BaseCheck):
    """Config debt detection — surfaces stale, disabled, or scoped-out config.

    Detects three forms of configuration debt:

    1. **Stale applicability** — Language-specific gates (``py-*``,
       ``js-*``) disabled but the project now has that language.
    2. **Disabled gates** — Gates in the ``disabled_gates`` top-level
       list (set via ``sm config --disable``).
    3. **Exclude drift** — ``exclude_dirs`` entries that contain real
       source code.

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
        findings.extend(check_exclude_drift(root, config))

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
