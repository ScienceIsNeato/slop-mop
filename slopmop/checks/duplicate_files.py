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

#: What makes two findings "the same defect": identical file content, plus the
#: same position and rule. Column and rule_id are part of the identity because
#: two distinct diagnostics can share a line and message text.
_GroupKey = Tuple[str, Optional[int], Optional[int], Optional[str], str]


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

    try:
        root_resolved = root.resolve()
    except OSError:
        return list(findings), 0

    def file_key(rel: Optional[str]) -> Optional[str]:
        if not rel:
            return None
        if rel not in hash_cache:
            candidate = Path(rel)
            if not candidate.is_absolute():
                candidate = root / rel
            # Findings come from external tools, which can report absolute
            # paths or ones containing "..". Never read outside the project.
            try:
                resolved = candidate.resolve()
                resolved.relative_to(root_resolved)
            except (OSError, ValueError):
                hash_cache[rel] = None
                return None
            hash_cache[rel] = _content_key(resolved)
        return hash_cache[rel]

    # Group by (identical-content, line, message) — the same defect, same
    # place, in copies of the same file.
    groups: Dict[_GroupKey, List[Finding]] = {}
    passthrough: List[Finding] = []
    for f in findings:
        key = file_key(f.file)
        if key is None:
            # No file, unreadable, or too large to hash — never merged.
            passthrough.append(f)
            continue
        # Column and rule_id are part of the identity: two distinct
        # diagnostics can share a line and message text.
        groups.setdefault((key, f.line, f.column, f.rule_id, f.message), []).append(f)

    order = {id(f): i for i, f in enumerate(findings)}
    positioned: List[Tuple[int, Finding]] = []
    collapsed = 0
    for group in groups.values():
        if len(group) == 1:
            positioned.append((order[id(group[0])], group[0]))
            continue
        # Prefer the shortest path: 'tools/llm_api.py' reads better as the
        # canonical location than a deeply nested vendored copy.
        survivor = min(group, key=lambda f: (len(f.file or ""), f.file or ""))
        others = len(group) - 1
        collapsed += others
        copies = "copy" if others == 1 else "copies"
        # The merged Finding is a NEW object, so its identity is absent from
        # `order`. Carry the earliest original position of the group forward
        # or every collapsed survivor sinks to the bottom of the report.
        first_position = min(order[id(f)] for f in group)
        positioned.append(
            (
                first_position,
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
                ),
            )
        )

    positioned.extend((order[id(f)], f) for f in passthrough)
    positioned.sort(key=lambda pair: pair[0])
    return [f for _, f in positioned], collapsed
