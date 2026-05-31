"""`sm schema` — emit the machine-interface JSON Schema.

Self-description without execution: an agent runs ``sm schema`` to learn
the invariant response envelope before driving any other verb. With a
verb argument, it returns that verb's full output schema (the envelope
with its ``data`` slot resolved to the verb's data schema), so the agent
can predict a specific command's shape without running it.
"""

from __future__ import annotations

import argparse
import json
from typing import Dict, cast

from slopmop.reporting.envelope import (
    available_data_schemas,
    load_data_schema,
    load_envelope_schema,
)


def _compose_output_schema(
    verb: str, data_schema: Dict[str, object]
) -> Dict[str, object]:
    """Return the envelope schema with ``data`` replaced by the verb's schema.

    The result is a standalone document describing exactly what ``sm
    <verb> --format json`` emits: the invariant frame plus that verb's
    payload. The envelope's other properties are left untouched.
    """
    envelope = load_envelope_schema()
    properties = envelope.get("properties")
    if isinstance(properties, dict):
        props = cast(Dict[str, object], properties)
        props["data"] = data_schema
    envelope["title"] = f"slop-mop {verb} response"
    envelope["$id"] = f"https://slopmop.dev/schemas/v3/output/{verb}.json"
    return envelope


def cmd_schema(args: argparse.Namespace) -> int:
    """Print the envelope schema, or a verb's full output schema."""
    verb = getattr(args, "schema_verb", None)

    if not verb:
        print(json.dumps(load_envelope_schema(), indent=2))
        return 0

    data_schema = load_data_schema(verb)
    if data_schema is None:
        known = available_data_schemas()
        print(
            f"No data schema for '{verb}'. "
            f"Verbs with a declared data schema: {', '.join(known) or '(none yet)'}.",
        )
        print(
            "The envelope shape still applies — run `sm schema` for the "
            "invariant frame.",
        )
        return 1

    print(json.dumps(_compose_output_schema(verb, data_schema), indent=2))
    return 0
