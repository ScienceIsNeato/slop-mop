"""Shared JSONC parsing for config files (pyright, knip, ...).

Several gates read config files that are JSON-with-comments: pyright's
``pyrightconfig.json`` and knip's ``knip.jsonc`` both allow ``//`` line
comments, ``/* */`` block comments, and trailing commas — none of which
``json.loads`` accepts. Each gate used to strip those with its own regex, and
those regexes kept reintroducing the same bug: a naive ``//`` or ``/* */``
regex doesn't respect string boundaries, so glob values like ``"src/**"`` or a
path containing ``//`` get treated as comment markers and silently corrupt the
document. This module is the single, string-aware implementation everyone
shares so that bug class stays fixed in one place.
"""

from __future__ import annotations

import json
from typing import Any, List


def strip_jsonc(text: str) -> str:
    """Return ``text`` with JSONC comments and trailing commas removed.

    Handles ``//`` line comments, ``/* */`` block comments, and trailing commas
    before ``}``/``]``. Scans character by character and never inspects the
    contents of a double-quoted, escape-aware JSON string, so values such as
    ``"src/**"``, ``"packages/*/dist"``, or ``"http://example"`` survive intact.
    """
    out: List[str] = []
    i = 0
    n = len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:  # keep escaped char verbatim
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":  # line comment
            i += 2
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":  # block comment
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if ch in "}]":  # drop a trailing comma already emitted before this
            k = len(out) - 1
            while k >= 0 and out[k] in " \t\r\n":
                k -= 1
            if k >= 0 and out[k] == ",":
                del out[k]
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def loads_jsonc(text: str) -> Any:
    """Parse a JSONC document (comments + trailing commas tolerated)."""
    return json.loads(strip_jsonc(text))
