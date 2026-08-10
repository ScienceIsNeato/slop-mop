"""Collapse findings that are the same issue seen in duplicated files.

Repos that distribute templates, vendor a tool into a subdirectory, or ship
starter packs contain byte-identical copies of the same source file. Every
gate then reports the same defect once per copy, and the first-run finding
count is inflated several-fold — ``botingw/rulebook-ai`` ships 7 identical
copies of ``tool_starters/llm_api.py``, which turned 1 unused import into 5
findings, 1 oversized function into 7, and 1 placeholder string into 7
"potential secrets".

Nobody fixes the same line seven times: they fix it once and re-copy. So the
noise is pure cost, and it lands on exactly the first-run impression that
decides whether someone keeps using the tool.

The collapse is deliberately conservative — it only merges findings whose
files are **byte-identical** (same size, same sha256) AND that sit at the
same line with the same message. Two different bugs that merely share a line
number are never merged, and a file that has diverged even by a byte is
treated as its own file.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from slopmop.core.result import Finding

# Files above this size are never hashed — a duplicate multi-MB asset is not
# what this is for, and hashing them on every gate would cost more than the
# noise it saves.
_MAX_HASH_BYTES = 2_000_000


def _content_key(path: Path) -> Optional[str]:
    """Return ``size:sha256`` for *path*, or None if it can't be read."""
    try:
        size = path.stat().st_size
        if size > _MAX_HASH_BYTES:
            return None
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, ValueError):
        return None
    return f"{size}:{digest}"


def collapse_duplicate_file_findings(
    findings: Sequence[Finding],
    project_root: str,
) -> Tuple[List[Finding], int]:
    """Merge findings that repeat across byte-identical copies of a file.

    Returns ``(findings, collapsed_count)`` where ``collapsed_count`` is how
    many findings were absorbed into a survivor. The survivor keeps the
    shortest path (the most canonical-looking location) and its message gains
    a note naming how many other copies share the issue, so the information
    isn't lost — only the repetition.
    """
    if len(findings) < 2:
        return list(findings), 0

    root = Path(project_root)
    hash_cache: Dict[str, Optional[str]] = {}

    def file_key(rel: Optional[str]) -> Optional[str]:
        if not rel:
            return None
        if rel not in hash_cache:
            candidate = Path(rel)
            if not candidate.is_absolute():
                candidate = root / rel
            hash_cache[rel] = _content_key(candidate)
        return hash_cache[rel]

    # Group by (identical-content, line, message) — the same defect, same
    # place, in copies of the same file.
    groups: Dict[Tuple[str, Optional[int], str], List[Finding]] = {}
    passthrough: List[Finding] = []
    for f in findings:
        key = file_key(f.file)
        if key is None:
            # No file, unreadable, or too large to hash — never merged.
            passthrough.append(f)
            continue
        groups.setdefault((key, f.line, f.message), []).append(f)

    out: List[Finding] = []
    collapsed = 0
    for group in groups.values():
        if len(group) == 1:
            out.append(group[0])
            continue
        # Prefer the shortest path: 'tools/llm_api.py' reads better as the
        # canonical location than a deeply nested vendored copy.
        survivor = min(group, key=lambda f: (len(f.file or ""), f.file or ""))
        others = len(group) - 1
        collapsed += others
        copies = "copy" if others == 1 else "copies"
        out.append(
            Finding(
                message=(
                    f"{survivor.message} "
                    f"[also in {others} identical {copies} of this file]"
                ),
                level=survivor.level,
                file=survivor.file,
                line=survivor.line,
                column=survivor.column,
                end_line=survivor.end_line,
                end_column=survivor.end_column,
                rule_id=survivor.rule_id,
                fix_strategy=survivor.fix_strategy,
            )
        )

    out.extend(passthrough)
    # Preserve the caller's ordering as closely as possible.
    order = {id(f): i for i, f in enumerate(findings)}
    out.sort(key=lambda f: order.get(id(f), len(findings)))
    return out, collapsed
