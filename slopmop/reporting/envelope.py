"""The slop-mop response envelope — the invariant frame every verb speaks.

Every ``sm`` verb, in ``--format json``, emits the same outer object:

    {"schema", "command", "status", "exit_code", "data",
     "next_steps", "diagnostics"}

Only ``data`` varies between verbs; the rest is identical so an agent can
predict the shape of any response before running the command. The
canonical contract is the packaged JSON Schema at
``slopmop/schemas/v3/envelope.json`` — this module is the Python side
that builds conformant objects, and the conformance test suite validates
real verb output against that schema.

This module is pure-transform: it builds dicts, it does not perform I/O
or decide output format. Callers own ``json.dumps`` and stream choice.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from importlib import resources
from typing import Dict, List, Optional, Sequence, cast

# Bump when the *envelope* shape changes (new required fields, renames).
# Distinct from the legacy flat validation schema, which already shipped
# as "slopmop/v2"; the envelope is a different, breaking shape, so it
# takes the next number rather than colliding with that string.
ENVELOPE_SCHEMA_VERSION = "slopmop/v3"


class Status(str, Enum):
    """Envelope ``status`` values.

    Subclasses ``str`` so the enum members serialise directly to their
    string value in ``json.dumps`` without a custom encoder.
    """

    OK = "ok"  # success condition held (gates passed, no issues)
    FAIL = "fail"  # ran, found blocking problems (gate failures)
    ERROR = "error"  # could not complete (missing dep, bad args, crash)
    INFO = "info"  # observatory verb with no pass/fail (status, schema)


# Closed vocabulary for next-step actions. Kept in sync with the
# ``action`` enum in schemas/v3/envelope.json — the conformance test
# fails if they drift.
_NEXT_STEP_ACTIONS = frozenset(
    {
        "inspect",
        "rerun",
        "fix",
        "advance",
        "install",
        "commit",
        "push",
        "escalate",
        "wait",
    }
)

_DIAGNOSTIC_LEVELS = frozenset({"info", "warn", "error"})


@dataclass(frozen=True)
class NextStep:
    """One machine-actionable follow-up.

    ``command`` is the exact thing to run; it is ``None`` only when the
    step genuinely is not a single command (rare). Prefer a concrete
    command so an agent acts without parsing ``reason``.
    """

    action: str
    command: Optional[str] = None
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        if self.action not in _NEXT_STEP_ACTIONS:
            raise ValueError(
                f"unknown next-step action {self.action!r}; "
                f"allowed: {sorted(_NEXT_STEP_ACTIONS)}"
            )

    def to_dict(self) -> Dict[str, object]:
        out: Dict[str, object] = {"action": self.action}
        # Emit command/reason even when None — the schema allows null and
        # a fixed key set is easier for consumers than presence-probing.
        out["command"] = self.command
        out["reason"] = self.reason
        return out


@dataclass(frozen=True)
class Diagnostic:
    """An execution-context warning, not a gate finding.

    Examples: ``gh`` not installed, no PR detected, results served from
    cache, time-budget skipped checks. Generalises what validation used
    to emit as ``runtime_warnings`` so every verb surfaces context the
    same way.
    """

    code: str
    level: str
    message: str
    suggested_command: Optional[str] = None

    def __post_init__(self) -> None:
        if self.level not in _DIAGNOSTIC_LEVELS:
            raise ValueError(
                f"unknown diagnostic level {self.level!r}; "
                f"allowed: {sorted(_DIAGNOSTIC_LEVELS)}"
            )
        if not self.code:
            raise ValueError("diagnostic code must be non-empty")

    def to_dict(self) -> Dict[str, object]:
        out: Dict[str, object] = {
            "code": self.code,
            "level": self.level,
            "message": self.message,
        }
        if self.suggested_command is not None:
            out["suggested_command"] = self.suggested_command
        return out


def build_envelope(
    *,
    command: str,
    status: Status,
    exit_code: int,
    data: Dict[str, object],
    next_steps: Sequence[NextStep] = (),
    diagnostics: Sequence[Diagnostic] = (),
) -> Dict[str, object]:
    """Build a schema-conformant envelope dict.

    The result is JSON-serialisable; the caller owns ``json.dumps`` and
    chooses the output stream. ``next_steps`` and ``diagnostics`` are
    omitted from the output when empty to keep the common case compact —
    both are optional in the schema.
    """
    envelope: Dict[str, object] = {
        "schema": ENVELOPE_SCHEMA_VERSION,
        "command": command,
        "status": status.value,
        "exit_code": exit_code,
        "data": data,
    }
    if next_steps:
        envelope["next_steps"] = [step.to_dict() for step in next_steps]
    if diagnostics:
        envelope["diagnostics"] = [d.to_dict() for d in diagnostics]
    return envelope


def render_envelope(
    *,
    command: str,
    status: Status,
    exit_code: int,
    data: Dict[str, object],
    next_steps: Sequence[NextStep] = (),
    diagnostics: Sequence[Diagnostic] = (),
) -> str:
    """Build and serialise an envelope to a compact JSON string.

    Compact separators match the existing machine-output convention used
    by ``sm status``; agents parse this, humans read ``--format human``.
    """
    envelope = build_envelope(
        command=command,
        status=status,
        exit_code=exit_code,
        data=data,
        next_steps=next_steps,
        diagnostics=diagnostics,
    )
    return json.dumps(envelope, separators=(",", ":"))


def status_for_exit_code(exit_code: int) -> Status:
    """Map a conventional exit code to an envelope status.

    0 → ok, anything else → fail. Verbs that distinguish ``error`` (could
    not run) from ``fail`` (ran, found problems) or that are ``info``
    observatories should set the status explicitly rather than rely on
    this helper.
    """
    return Status.OK if exit_code == 0 else Status.FAIL


def load_envelope_schema() -> Dict[str, object]:
    """Return the packaged envelope JSON Schema as a dict.

    Resolved via ``importlib.resources`` so it works from an installed
    wheel, not only a source checkout.
    """
    return _load_packaged_schema("envelope.json")


def _load_packaged_schema(filename: str) -> Dict[str, object]:
    """Load a JSON Schema file shipped under ``slopmop/schemas/v3``."""
    resource = resources.files("slopmop.schemas.v3").joinpath(filename)
    parsed: object = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"schema {filename} is not a JSON object")
    return cast(Dict[str, object], parsed)


def available_data_schemas() -> List[str]:
    """Return the verb names that have a packaged ``data`` schema.

    Discovered by listing ``data/<verb>.json`` resources so the catalog
    stays in sync with what actually ships — no hand-maintained list to
    drift.
    """
    data_dir = resources.files("slopmop.schemas.v3").joinpath("data")
    if not data_dir.is_dir():
        return []
    suffix = ".json"
    filenames = [str(entry.name) for entry in data_dir.iterdir()]
    return sorted(
        filename[: -len(suffix)] for filename in filenames if filename.endswith(suffix)
    )


def load_data_schema(verb: str) -> Optional[Dict[str, object]]:
    """Return the packaged ``data`` schema for one verb, or None.

    None means the verb has no declared data schema yet (it has not been
    migrated onto the envelope). Callers treat that as "shape not yet
    guaranteed" rather than an error.
    """
    if verb not in available_data_schemas():
        return None
    return _load_packaged_schema(f"data/{verb}.json")
