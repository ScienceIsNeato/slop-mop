"""User-defined custom gates (issue #53).

Custom gates let users define project-specific checks directly in
``.sb_config.json`` without writing Python.  This is the primary
mechanism for supporting languages slop-mop doesn't ship native gates
for (Go, Rust, C, Ruby, …).

Spec (per issue #53)::

    {
      "custom_gates": [
        {
          "name": "go-vet",
          "description": "Go static analysis",
          "category": "overconfidence",
          "command": "go vet ./...",
          "level": "swab",
          "timeout": 120
        }
      ]
    }

Semantics:
    * ``command`` runs in a shell (``/bin/sh -c``) with ``cwd=project_root``.
    * Exit 0 → PASSED, non-zero → FAILED.
    * stdout+stderr captured and shown on failure.
    * Custom gate commands are **user-trusted by definition** — they live
      in a file the user owns, in a repo the user controls.  We therefore
      bypass :class:`CommandValidator` (which blocks ``|``, ``&&``, etc.)
      and invoke ``subprocess.run`` directly.
    * Registry keyed on ``category:name`` just like built-ins, so custom
      gates appear in ``sm status`` inventory, ``sm swab`` / ``sm scour``
      runs, and can be disabled via ``disabled_gates``.
"""

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Set, Type, cast

from slopmop.checks.base import (
    BaseCheck,
    Flaw,
    GateCategory,
    GateLevel,
    ToolContext,
)
from slopmop.core.registry import get_registry
from slopmop.core.result import CheckResult, CheckStatus

logger = logging.getLogger(__name__)

# Keep per-process record of which custom gates we've registered so
# repeated CLI invocations in tests (or re-entrant status calls) don't
# log "already registered" warnings.
_registered_custom: Set[str] = set()

# Sane ceiling — a single gate shouldn't lock the terminal for longer
# than the whole scour is expected to take.
DEFAULT_CUSTOM_TIMEOUT = 120
MAX_CUSTOM_TIMEOUT = 600

_REQUIRED_FIELDS = ("name", "command")

# Flaw only has the four core values; categories 'general'/'pr' don't
# map 1:1.  Pick the least-surprising fallback so users don't have to
# care about the Flaw enum at all.
_FLAW_FALLBACK: Dict[str, Flaw] = {
    "overconfidence": Flaw.OVERCONFIDENCE,
    "deceptiveness": Flaw.DECEPTIVENESS,
    "laziness": Flaw.LAZINESS,
    "myopia": Flaw.MYOPIA,
    "general": Flaw.LAZINESS,
    "pr": Flaw.MYOPIA,
}


class CustomGateError(ValueError):
    """Raised for malformed custom-gate specs in ``.sb_config.json``."""


def _validate_spec(spec: Dict[str, Any], index: int) -> None:
    """Raise ``CustomGateError`` with a precise pointer if ``spec`` is bad."""
    for field in _REQUIRED_FIELDS:
        if field not in spec or not spec[field]:
            raise CustomGateError(
                f"custom_gates[{index}]: missing required field '{field}'"
            )

    name = spec["name"]
    if not isinstance(name, str) or ":" in name or "/" in name:
        raise CustomGateError(
            f"custom_gates[{index}]: 'name' must be a plain string "
            f"(no ':' or '/'), got {name!r}"
        )

    if not isinstance(spec["command"], str):
        raise CustomGateError(
            f"custom_gates[{index}] ({name}): 'command' must be a string"
        )

    category_key = spec.get("category", "general")
    if GateCategory.from_key(category_key) is None:
        valid = ", ".join(c.key for c in GateCategory)
        raise CustomGateError(
            f"custom_gates[{index}] ({name}): unknown category "
            f"{category_key!r}. Valid: {valid}"
        )

    level_key = spec.get("level", "swab")
    if level_key not in ("swab", "scour"):
        raise CustomGateError(
            f"custom_gates[{index}] ({name}): 'level' must be 'swab' or "
            f"'scour', got {level_key!r}"
        )

    timeout = spec.get("timeout", DEFAULT_CUSTOM_TIMEOUT)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise CustomGateError(
            f"custom_gates[{index}] ({name}): 'timeout' must be a "
            f"positive number, got {timeout!r}"
        )


def _run_custom_command(
    check: BaseCheck,
    project_root: str,
    command: str,
    gate_name: str,
    timeout_s: float,
) -> CheckResult:
    """Execute a user-authored shell command as a gate.

    Pulled out of the generated class so ``make_custom_gate_class``
    stays under the 100-line sprawl threshold — closures are cheap,
    135-line factories are not.

    IMPORTANT: bypasses the validated runner.  The validator rejects
    ``|``, ``&&``, ``;`` etc., but shell idioms are the whole point of
    custom gates.  The user wrote this command into a file they own —
    same trust level as a Makefile target or an npm script.
    """
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            ["/bin/sh", "-c", command],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return check._create_result(
            status=CheckStatus.FAILED,
            duration=time.perf_counter() - start,
            output=f"Command: {command}",
            error=(
                f"Custom gate timed out after {timeout_s:.0f}s.\n"
                f"Bump 'timeout' in .sb_config.json if this is "
                f"expected for a repo of this size."
            ),
            fix_suggestion=(
                f"Increase custom_gates[].timeout for "
                f"'{gate_name}' in .sb_config.json"
            ),
        )
    except FileNotFoundError as e:
        # /bin/sh itself missing — exotic, but give a clear error
        # rather than a raw traceback.
        return check._create_result(
            status=CheckStatus.ERROR,
            duration=time.perf_counter() - start,
            error=f"Shell unavailable for custom gate: {e}",
        )

    elapsed = time.perf_counter() - start
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    combined = (stdout + ("\n" + stderr if stderr else "")).strip()

    if completed.returncode == 0:
        return check._create_result(
            status=CheckStatus.PASSED,
            duration=elapsed,
            output=combined or f"`{command}` exited 0",
        )

    return check._create_result(
        status=CheckStatus.FAILED,
        duration=elapsed,
        output=f"$ {command}\n{combined}" if combined else f"$ {command}",
        error=(f"Custom gate '{gate_name}' failed " f"(exit {completed.returncode})"),
        fix_suggestion=(
            f"Run `{command}` manually in the repo root to "
            f"reproduce. Disable via disabled_gates if this gate "
            f"is noise for this branch."
        ),
    )


def make_custom_gate_class(spec: Dict[str, Any]) -> Type[BaseCheck]:
    """Manufacture a ``BaseCheck`` subclass for a single custom-gate spec.

    The registry instantiates check classes with ``check_class({})`` to
    read ``full_name``, so the spec is baked into *class attributes*
    rather than passed through ``__init__``.
    """
    gate_name: str = spec["name"]
    command: str = spec["command"]
    description: str = spec.get("description") or gate_name
    category_key: str = spec.get("category", "general")
    level_key: str = spec.get("level", "swab")
    timeout_s: float = min(
        float(spec.get("timeout", DEFAULT_CUSTOM_TIMEOUT)),
        MAX_CUSTOM_TIMEOUT,
    )

    gate_category = GateCategory.from_key(category_key)
    # _validate_spec already checked this — assert for type narrowing.
    assert gate_category is not None
    gate_flaw = _FLAW_FALLBACK[category_key]
    gate_level = GateLevel.SCOUR if level_key == "scour" else GateLevel.SWAB

    class CustomGate(BaseCheck):
        # Marker for `sm status` to badge these distinctly.
        is_custom = True

        # PURE because we handle the subprocess ourselves; the
        # framework shouldn't go hunting for tools on our behalf.
        tool_context = ToolContext.PURE
        level = gate_level

        @property
        def name(self) -> str:
            return gate_name

        @property
        def display_name(self) -> str:
            return f"⚙️  {description}"

        @property
        def gate_description(self) -> str:
            return f"⚙️  [custom] {description}"

        @property
        def category(self) -> GateCategory:
            return gate_category

        @property
        def flaw(self) -> Flaw:
            return gate_flaw

        def is_applicable(self, project_root: str) -> bool:
            # User defined it in this project's config → user wants it.
            # Fine-grained disabling still works via `disabled_gates`.
            return True

        def skip_reason(self, project_root: str) -> str:
            return "custom gate never auto-skips"

        def run(self, project_root: str) -> CheckResult:
            return _run_custom_command(
                self, project_root, command, gate_name, timeout_s
            )

    # Give the generated class a stable, debuggable name.
    CustomGate.__name__ = f"CustomGate_{gate_name.replace('-', '_')}"
    CustomGate.__qualname__ = CustomGate.__name__
    return CustomGate


def load_custom_gate_specs(project_root: str) -> List[Dict[str, Any]]:
    """Read and validate ``custom_gates`` from ``.sb_config.json``.

    Returns an empty list if no config file, no ``custom_gates`` key,
    or the key is not a list.  Raises ``CustomGateError`` only when
    a spec *is* present but malformed — silence on absence, loudness
    on brokenness.
    """
    config_path = Path(project_root) / ".sb_config.json"
    if not config_path.exists():
        return []

    try:
        config = json.loads(config_path.read_text())
    except json.JSONDecodeError:
        # load_config already logs this; don't double-warn.
        return []

    raw = config.get("custom_gates")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CustomGateError(
            f"'custom_gates' must be a list, got {type(raw).__name__}"
        )
    # ``isinstance(raw, list)`` narrows to ``list[Unknown]`` under
    # pyright strict; cast to List[Any] so the loop variable and the
    # inner dict-guard both narrow cleanly instead of poisoning every
    # downstream arg with Unknown.
    validated: List[Dict[str, Any]] = []
    for i, spec in enumerate(cast(List[Any], raw)):
        if not isinstance(spec, dict):
            raise CustomGateError(
                f"custom_gates[{i}] must be an object, got {type(spec).__name__}"
            )
        spec_d = cast(Dict[str, Any], spec)
        _validate_spec(spec_d, i)
        validated.append(spec_d)

    return validated


def register_custom_gates(project_root: str) -> List[str]:
    """Load, manufacture and register all custom gates for ``project_root``.

    Idempotent across calls within the same process.  Returns the list
    of ``full_name`` strings registered (useful for ``sm status`` to
    badge them).
    """
    specs = load_custom_gate_specs(project_root)
    if not specs:
        return []

    registry = get_registry()
    registered: List[str] = []

    for spec in specs:
        cls = make_custom_gate_class(spec)
        full_name = cls({}).full_name

        if full_name in _registered_custom:
            registered.append(full_name)
            continue

        registry.register(cls)
        _registered_custom.add(full_name)
        registered.append(full_name)

    return registered


def custom_gate_names(project_root: str) -> Set[str]:
    """Return the set of ``full_name`` strings that are custom for this root.

    Cheap lookup for status-dashboard badging — does NOT register.
    """
    try:
        specs = load_custom_gate_specs(project_root)
    except CustomGateError:
        return set()

    names: Set[str] = set()
    for spec in specs:
        cat = spec.get("category", "general")
        names.add(f"{cat}:{spec['name']}")
    return names


# ── Scaffolding for `sm init` ───────────────────────────────────────────

# Per-ecosystem default custom gates.  `sm init` drops these in when it
# detects a language slop-mop doesn't natively support.  Each gate is
# the single most-universal linter for that ecosystem — the thing you'd
# expect to find in that repo's CI.
SCAFFOLD_GO: List[Dict[str, Any]] = [
    {
        "name": "go-vet",
        "description": "Go static analysis (vet)",
        "category": "overconfidence",
        "command": "go vet ./...",
        "level": "swab",
        "timeout": 180,
    },
    {
        "name": "go-build",
        "description": "Go compilation check",
        "category": "overconfidence",
        "command": "go build ./...",
        "level": "swab",
        "timeout": 300,
    },
    {
        "name": "gofmt-drift",
        "description": "Unformatted Go source",
        "category": "laziness",
        # ``gofmt -l`` lists offending files on stdout and exits 0 even
        # when files need formatting.  We want BOTH a non-zero exit AND
        # the file list in the failure output — the earlier
        # ``test -z "$(gofmt -l .)"`` swallowed the list, leaving the
        # user with "exit 1" and nothing to act on.
        "command": 'out="$(gofmt -l .)"; '
        'if [ -n "$out" ]; then echo "$out"; exit 1; fi',
        "level": "swab",
        "timeout": 60,
    },
]

SCAFFOLD_RUST: List[Dict[str, Any]] = [
    {
        "name": "cargo-check",
        "description": "Rust compilation check",
        "category": "overconfidence",
        "command": "cargo check --all-targets",
        "level": "swab",
        "timeout": 300,
    },
    {
        "name": "cargo-clippy",
        "description": "Rust linting (clippy)",
        "category": "laziness",
        "command": "cargo clippy --all-targets -- -D warnings",
        "level": "scour",
        "timeout": 300,
    },
    {
        "name": "cargo-fmt-drift",
        "description": "Unformatted Rust source",
        "category": "laziness",
        "command": "cargo fmt --all -- --check",
        "level": "swab",
        "timeout": 60,
    },
]

SCAFFOLD_C: List[Dict[str, Any]] = [
    {
        "name": "make-check",
        "description": "Run the project's own test suite",
        "category": "overconfidence",
        # Many C projects need ./configure first; prefer `make check`
        # when already configured, otherwise this is a warn-and-disable
        # situation on first init.
        "command": "make -n check >/dev/null 2>&1 && make check",
        "level": "scour",
        "timeout": 600,
    },
]


def scaffold_for_detected(detected: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build a ``custom_gates`` list for languages detected but unsupported.

    Returns specs ready to drop into ``.sb_config.json``.  Empty list
    when the project is pure Python/JS (built-in gates cover it).
    """
    out: List[Dict[str, Any]] = []
    if detected.get("has_go"):
        out.extend(SCAFFOLD_GO)
    if detected.get("has_rust"):
        out.extend(SCAFFOLD_RUST)
    if detected.get("has_c"):
        out.extend(SCAFFOLD_C)
    return out
