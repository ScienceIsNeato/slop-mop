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

---

## 3. `refit` is hard-blocked by patch-level tool drift

`sm refit --start` refused to run: `black found 26.5.0, requires >=26.5.1`
(and autoflake 2.3.1 vs 2.3.3). A user one patch release behind cannot onboard
at all until they chase the exact pin. Preflight should warn, not block, on
patch-level drift.

## 4. `sm init` disables gates, then `sm refit` blocks on init's own choice

`init` shipped `deceptiveness:gate-dodging` and `laziness:silenced-gates`
disabled. `refit --start` then refused to proceed until each was justified with
a bug reference or approved — demanding the user account for a decision the
tool made for them. (Enabling them also dirties the tree, which trips refit's
clean-tree precondition: a second round-trip.)

## 5. Gate fails with zero findings — and the message is unactionable

`overconfidence:missing-annotations.py` reported:

```
Status: failed
Error: 0 type error(s) found
--- Output ---
0 type error(s):
```

Root cause: mypy exits non-zero on a **module-resolution** error
(`Duplicate module named 'llm_api'` — the 7 vendored copies from barnacle #1),
not a type error. The gate treats any non-zero mypy exit as "type errors" and
reports the parsed count (0). A user sees a failing gate with nothing to fix.

**Fix direction:** distinguish "tool failed to run" (→ could-not-run ERROR with
the tool's stderr) from "tool ran and found N issues". The requirements
contract already models this three-state idea for missing tools; it should
extend to tools that run but abort.

## 6. Inconsistent remediation guidance between sibling gates

`laziness:repeated-code` tells you about `exclude_dirs` and prints the exact
`sm config --set` command. `myopia:ambiguity-mines.py` has the *identical*
`exclude_dirs`/`include_dirs` schema but its fix text only says "Consolidate
duplicate function definitions" — the escape hatch is undiscoverable.
`overconfidence:missing-annotations.py` (a mypy gate) suggests
`ruff format . && ruff check --fix` — the wrong tool entirely.

---

## Refit progress log (real run)

| Step | Gate | Outcome |
| --- | --- | --- |
| 1 | `myopia:dependency-risk.py` | fixed: real B310 scheme validation + 7 false-positive placeholders tagged (8 → 0) |
| 2 | `laziness:repeated-code` | config: excluded distributed template packs (49 → 0) |
| 3 | `myopia:ambiguity-mines.py` | config: excluded vendored copies + test helpers (26 → 0) |
| 4 | `overconfidence:missing-annotations.py` | **BLOCKED** — barnacle #5 (fails with 0 findings) |
