# Barnacles found onboarding `botingw/rulebook-ai`

Two product problems surfaced by running slop-mop cold on a stranger's repo
(MIT, ~8k LOC Python, already using ruff + mypy + pytest + CI).

## 1. Vendored/template copies multiply identical findings (5–7×)

rulebook-ai distributes "tool starter" templates, so `tool_starters/llm_api.py`
exists as **7 byte-identical copies** (md5 `bb48320808699b61cc42b293a4c2d30b`).
Every gate reports the same issue once per copy:

| Gate | Reported | Actually unique |
| --- | --- | --- |
| `laziness:dead-code.py` | 5 | **1** (`llm_api.py:12 unused import Union`) |
| `myopia:code-sprawl` | 9 | **3** (`query_llm()` counted 7×) |
| `detect-secrets` (via dependency-risk) | 7 | **1** |
| `laziness:repeated-code` | fails | duplication **is the design** |

A first-time user sees ~57 findings where ~20 distinct problems exist. This is
the wall that makes people bounce.

**Fix direction:** dedupe findings by content-hash of the containing file, and/or
detect vendored/template directories and scan one representative copy.

## 2. The hull grade has no resolution where new users live

Full quality pass on this repo:

- gates failing: **8 → 6**  (cleared dead-code, sloppy-formatting, github-actions-hygiene)
- findings: **~57 → ~20** (−65%)
- `myopia:github-actions-hygiene`: **23 → 0**
- **hull grade: F → F** (unchanged)

Grade F is "4+ gates failing", so every legacy repo starts at F and *stays* F
through substantial real improvement. For the inherited-codebase user that
`sm refit` explicitly targets, the scoreboard never moves — which is precisely
the audience most likely to quit.

**Fix direction:** a finding-count or trend component beneath the letter (e.g.
"F · 20 findings, ↓65% this pass"), so progress is visible before the letter
changes.

## Bonus: the gate was right about their CI

`myopia:github-actions-hygiene` flagged `actions/upload-artifact@v3` (retired by
GitHub) and `checkout@v3`/`setup-python@v4` (deprecated). rulebook-ai's CI has
been red on `main` since 2025-09; the `build` job (which uses upload-artifact@v3)
and `lint` both fail while `test` passes. Logs are expired so causation isn't
provable, but the gate identified a real, live breakage in one run.
