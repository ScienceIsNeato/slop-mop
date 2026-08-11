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

```text
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


## 7. `string-duplication` reported paths relative to nothing

`_format_findings` called `os.path.relpath(file_path)` with no start
directory, so paths resolved against the *process* cwd rather than the
project root. Underneath it, the scanner ran in a tempdir: on macOS
`tempfile` hands back `/var/folders/...` while the scanner reports the
resolved `/private/var/folders/...`, so replacing only the unresolved
spelling matched the suffix and left `/private` glued to the front of every
path. Findings pointed at files that did not exist.

**Fixed** — the remap now tries both spellings longest-first, and the
formatter is passed the project root.

## 8. `dangling-references` could not tell code from prose

Python subscript-then-call — indexing a dict of handlers, then calling the
result — is byte-identical to markdown link syntax. A code sample using that
form inside a fenced python block was reported as a broken link, with the
call's argument name as the supposed target. The scanner walked every line
with no notion of code blocks.

On this repo it was the *only* remaining "broken link" after 12 genuine ones
were repaired — the single finding standing between the gate and green was
not a defect at all.

**Fixed** — fenced blocks are skipped and inline code spans are blanked
(preserving line length, so a link whose *text* is code still gets checked).

## 9. A security scanner that never ran was reported as a finding

`_scanner_failed_to_start()` existed, with a comment naming this exact
failure mode: *"Reporting 'No module named detect_secrets' as SLOP DETECTED
tells a user they have a leaked secret when they have a broken install."*

It was never called from anywhere.

So on a repo whose venv lacked pip-audit, `dependency-risk` failed with
"1 security scanner(s) found issues" and a single finding of "pip-audit
found issues" — naming a vulnerability that does not exist, while hiding
that nothing had been audited at all.

**Fixed** — bandit, semgrep and pip-audit now route startup failures to a
warned result naming the install command. A scanner that ran and genuinely
errored still fails.

## 10. `refit --iterate` named the wrong failing gate

A targeted scour runs the requested gate *plus its dependencies*, so when a
dependency fails the run stops on a different gate than the one being
iterated. The block message named the iterated gate anyway, and pointed at
that gate's log — which had not been rewritten, so it showed the previous
run's output.

In this run: iterating `missing-annotations` while `sloppy-formatting`
failed reported *"stopped on failing gate: missing-annotations"* next to a
stale 13-error mypy log, with the real one-line ruff failure nowhere in
sight. The artifact's own `first_to_fix` had it right the whole time.

**Fixed** — the failing gate and log now come from `first_to_fix`, and the
summariser describes the failed result instead of `results[0]`.

## Refit progress log (real run)

| Step | Gate | Outcome |
| --- | --- | --- |
| 1 | `myopia:dependency-risk.py` | fixed: real B310 scheme validation + 7 false-positive placeholders tagged (8 → 0) |
| 2 | `laziness:repeated-code` | config: excluded distributed template packs (49 → 0) |
| 3 | `myopia:ambiguity-mines.py` | config: excluded vendored copies + test helpers (26 → 0) |
| 4 | `overconfidence:missing-annotations.py` | fixed: 13 mypy errors incl. 2 latent crashes; duplicate-module abort excluded (13 → 0) |
| 5 | `myopia:string-duplication.py` | config + barnacles #7 (2 path bugs fixed in slop-mop) |
| 6 | `myopia:code-sprawl` | fixed: `create_parser()` split into per-group builders; vendored mirror excluded (3 → 0) |
| 7 | `overconfidence:dangling-references` | fixed: 12 real broken links; 13th was barnacle #8 (13 → 0) |
| 8 | `myopia:dependency-risk.py` | barnacle #9 — missing scanner reported as a finding |
| 9 | `overconfidence:type-blindness.py` | fixed: 18 real pyright errors via a typed yaml boundary (555 → 18 → 0) |
| 10 | `overconfidence:untested-code.py` | fixed: a regression *I* introduced — scheme validation broke `file:` index URLs (3 failing tests → 0) |
| 11 | `myopia:just-this-once.py` | fixed: 25 tests covering the changed lines |
| 12 | `overconfidence:coverage-gaps.py` | baselined at measured 40%; changed-line ratchet enforces improvement |

**Final: A+ — shipshape, 0 findings, 21 gates passing.** (Baseline: 8 failing.)

Their own suite: **56 passing at the merge-base, 81 passing at the end** (25 added). An earlier draft of this line read "53 passing / 3 failing → 81 passing", which implied we inherited three broken tests. We did not — those three were *our* regression, from the scheme validation in step 1, and the `git stash` baseline that appeared to clear us only removed *uncommitted* work. See barnacle 10's neighbours in the ledger.
