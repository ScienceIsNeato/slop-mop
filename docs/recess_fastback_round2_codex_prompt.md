# Codex Agent: recess-fastback Round-2 Refit Starting Prompt

> **Context for the human reading this:** This prompt is for a Codex agent that will run
> the complete slop-mop refit rail on `recess-fastback` from scratch using the latest
> unreleased version of slop-mop. It was written to be comprehensive and self-contained.
> The "friction packet → slop-mop agent" escalation path at the bottom is critical — do
> not strip that section.

---

## Mission

You are performing a **round-2 slop-mop refit** of the `recess-fastback` repository
from a clean `main` branch. Round-1 (PR #75) happened months ago with an older version
of slop-mop and is now reference material, not a target state. You are re-running the
entire remediation rail from scratch.

Why from scratch?
- slop-mop has changed substantially since round-1 (new gates, better detection, Deno
  hybrid workflow, off-rail guards, `myopia:interactive-assumptions`)
- `main` has diverged from the PR #75 branch
- Some round-1 fixes may need to be re-applied; others may be obsolete or different

**Your job is to follow the slop-mop refit rail exactly**, using PR #75 as an
orientation reference (not a recipe) and fast-forwarding through known work where the
fix is identical.

---

## Step 0: Install slop-mop From Source

The current stable PyPI release (v0.13.x) does **not** have all the features you need.
Install from the development repository:

```bash
# Install slop-mop from the local dev repo
pip install -e /path/to/slop-mop

# Verify the version has the new features
sm --version
sm refit --help   # should show --start, --iterate, --skip, --finish
sm config --help  # should show --set, --unset, --show
```

If the `sm` binary is not on `PATH` after install, use `python -m slopmop` as the
fallback or add the pip scripts dir to `PATH`.

---

## Step 1: Set Up a Clean Branch

```bash
# From inside the recess-fastback repo
git fetch origin
git checkout main
git pull origin main

# Create a new refit branch — do NOT reuse the PR #75 branch
git checkout -b refit/round-2-$(date +%Y%m%d)
```

**Important**: You will be committing directly to this branch as the rail advances.
Never commit to `main`.

---

## Step 2: Orientation — Read PR #75 Context

Before touching any code, read these files from the **currently checked-out main** to
orient yourself:

```bash
# What was done in round-1 (gate-by-gate narrative)
cat docs/REMEDIATION_REPORT.md

# What the current slop-mop config looks like (if it survived into main)
cat .sb_config.json 2>/dev/null || echo "(no config yet)"

# What the project structure is
ls supabase/functions/
ls -la deno.json deno.lock package.json 2>/dev/null
```

**What to extract from this reading:**
- Which gates were addressed in round-1 so you know what to expect in round-2
- Whether a `.sb_config.json` is already committed to main (if so, `sm init` will pick
  it up) or needs to be generated fresh
- Confirm the hybrid structure: `src/` (Node/TS) + `supabase/functions/` (Deno edge fns)

---

## Step 3: Init slop-mop Config

```bash
# Non-interactive init seeded for this project type
sm init --non-interactive
```

`sm init` now auto-detects Deno-backed Supabase Edge Functions if it finds
`supabase/functions/`. If the auto-detection worked, it will seed a Deno-aware
test and coverage config. Verify:

```bash
sm config --show
```

Look for these Deno-specific config fields being present:
- `overconfidence:untested-code.js` → `test_command` pointing to
  `deno test --allow-all --no-check 'supabase/functions/**/*.unit.test.ts'`
- `overconfidence:coverage-gaps.js` → `coverage_format = "deno"` or a
  `coverage_command` pointing to a Deno coverage workflow

If they are **not** auto-seeded, set them manually:

```bash
sm config --set overconfidence:untested-code.js test_command \
  "deno test --allow-all --no-check 'supabase/functions/**/*.unit.test.ts'"

sm config --set overconfidence:coverage-gaps.js coverage_format deno
sm config --set overconfidence:coverage-gaps.js coverage_command \
  "deno test --allow-all --no-check --coverage=coverage/deno 'supabase/functions/**/*.unit.test.ts'"
sm config --set overconfidence:coverage-gaps.js coverage_report_path \
  "coverage/deno"
```

The Node/npm side (if `package.json` exists with jest config) should auto-detect
without intervention.

---

## Step 4: Doctor Preflight

```bash
sm doctor
```

`sm refit --start` will also run a doctor preflight internally, but running it
explicitly first gives you a clean view of any tool-inventory problems before the
refit plan is generated. Fix any `FAIL` items before proceeding. `WARN` items are
non-blocking but worth noting.

Common things to fix:
- Missing `deno` binary → install Deno and ensure it's on `PATH`
- Missing `npm` deps → `npm install`
- Missing `jscpd` → the gate will auto-install via npx if it isn't global

---

## Step 5: Start the Refit

```bash
sm refit --start
```

This runs `sm scour` to capture all failing gates and generates a deterministic
one-gate-at-a-time plan at `.slopmop/refit/plan.json`. It will print a gate list
and a summary.

**What to expect on the plan:**
- `myopia:interactive-assumptions` — NEW gate (not in round-1). Catches `npx <tool>`
  without `--yes` and `apt-get install` without `-y` in shell scripts, CI YAML,
  Dockerfiles. High priority. PR #75 applied some of these fixes manually inside
  slop-mop itself; your job is to apply the same class of fix to **recess-fastback**
  sources.
- `laziness:sloppy-formatting.py` / JS formatting — PR #75 addressed these. The same
  fixes probably apply; fast-forward with direct file copies where appropriate.
- `myopia:code-sprawl` — files over the line-count threshold. PR #75 split some files;
  check if those are still too large or if new sprawl has appeared.
- `myopia:repeated-code.py` / `myopia:string-duplication.py` — PR #75 deduplicated
  several patterns. Expect new ones in main if code has grown since round-1.
- `overconfidence:type-blindness.py` — TypeScript `any` and unsafe casts.
- `overconfidence:untested-code.js` and `overconfidence:coverage-gaps.js` — Deno unit
  tests and lcov coverage. PR #75 added a large Deno test suite. Round-2 may have more
  uncovered code.
- Security gates — may catch new issues in recently added code.

If `sm refit --start` fails with a precheck review prompt (gate-runnability issues or
config questions), read the prompt carefully. If a gate shows as `pending_fidelity`
(configuration questions), answer or approve: `sm refit --start --approve-gate <gate>`.
If it shows as `blocked_runnability`, either fix the tooling or record the blocker:
`sm refit --start --record-blocker <gate> --blocker-issue <one-line-description>
--blocker-reason <why-it-cant-run>`.

---

## Step 6: The Iterate Loop

This is the main work loop. Run it repeatedly until the plan completes:

```bash
sm refit --iterate
```

**Returns:**
- Exit code `2` (CONTINUE_LOOP): gate passed and committed, more gates remain → run
  `--iterate` again immediately
- Exit code `0` (DONE): plan complete or current gate has a blocker for you to fix
- Exit code `1` (BLOCKED): a non-gate error stopped the rail → read the output, act on
  it, then re-run `--iterate`

**Normal flow when a gate fails:**
1. `--iterate` runs the scour gate
2. Gate fails → `--iterate` exits with its output showing what to fix
3. **You fix the code** following the gate's guidance
4. **Ensure the worktree is clean ONLY with the gate-fix changes** (see dirty-entry
   guard below)
5. Re-run `sm refit --iterate`
6. Gate now passes → `--iterate` auto-commits with a generated commit message and
   advances the plan
7. Continue

**Exit code 2 means keep going immediately.** Do not pause between consecutive
exit-2 invocations.

---

## Step 7: Gate-by-Gate Behavior and Fast-Forward Rules

### Fast-Forward Rule

If `--iterate` tells you to fix a gate, and PR #75's fix for that same pattern is:
1. Identical content (e.g. adding `--yes` to a specific `npx` call in a specific file)
2. The file still exists in main and the line is still wrong

→ **Copy the fix directly from PR #75's diff** and stage it. Don't rewrite what you
  already know works.

If the file was added new in PR #75 (e.g. a new `.ts` test file) and that file also
exists in main → **copy the whole file**, verify it still applies, stage it.

If the codebase has changed such that PR #75's fix no longer applies cleanly → work it
fresh based on the gate's current output.

### Formatting gates (`laziness:sloppy-formatting.*`)

auto-fix is on by default. `--iterate` will auto-fix and commit these. If auto-fix
fails to fully pass the gate, check for syntax errors that block the formatter.

### Interactive-assumptions gate (`myopia:interactive-assumptions`)

New gate added after PR #75. Looks for:
- `npx <tool>` without `--yes` in `.sh`, `.yml`, `.yaml`, Dockerfile, Makefile
- `apt-get install` / `apt install` without `-y` in same files

Fix: add `--yes` to each `npx` call and `-y` to each `apt-get install`. These are
mechanical changes. Check `.github/workflows/`, `scripts/`, `supabase/config.toml`
(if it has install steps).

### Type-blindness gate (`overconfidence:type-blindness.py`)

Look at the TypeScript files the gate flags. Replace `any` with proper types or
`unknown` where a type cannot be inferred. Do not suppress the gate with `// eslint-
disable` or `@ts-ignore` — that will just reveal a new gate failure for suppression
count.

### Deno tests / coverage gates

The gate will tell you which files have zero coverage or no tests. Deno unit tests live
in `supabase/functions/<name>/*.unit.test.ts`. Pattern from PR #75:
```typescript
// supabase/functions/<name>/<module>.unit.test.ts
import { assertEquals } from "https://deno.land/std/testing/asserts.ts";
import { myFunction } from "./<module>.ts";

Deno.test("<module> - <scenario>", () => {
  assertEquals(myFunction(input), expected);
});
```

Use the lcov coverage output to identify which lines need coverage, not just which
files the gate names.

### Code-sprawl gate (`myopia:code-sprawl`)

The gate will name specific files over the threshold. Extract coherent conceptual
chunks — don't just blindly chop by line count. Each extracted module should be a
meaningful unit with a clear name.

---

## Step 8: Guardrails — Things That Will Block You

### `blocked_on_dirty_entry` (new in current slop-mop)

`--iterate` fires this when your worktree has uncommitted changes **before** the gate
runs and the current plan item is in a fresh (not already-blocked) state. Meaning:
you have staged/unstaged changes that didn't come from the gate's auto-fix.

**Resolution:**
```bash
git status   # see what's dirty
# Either:
git stash    # stash unrelated changes
# Or:
git add -A && git commit -m "wip: stash before refit iteration"
# Then re-run --iterate
```

Never let unrelated changes ride through a gate-fix commit. The plan's commit
messages must map 1:1 to gate fixes.

### `blocked_on_dirty_worktree`

Fired *after* the gate runs when auto-commit fails because the worktree has unexpected
staged content. Same resolution as above — clean up the worktree before re-running.

### `warn_config_drift` (new in current slop-mop)

Appears in `--iterate` output when `.sb_config.json` has changed since `--start` ran.
This is **non-blocking** — `--iterate` continues, it's just a warning.

**If you see this:** Note it, then continue iterating. The plan may have a stale gate
list (e.g., newly-enabled gates won't appear until `--start` re-runs), but existing
plan items are still valid. Only file a friction packet if the drift causes a gate
behavior you genuinely cannot explain.

### `blocked_on_head_drift`

`--iterate` stores the expected HEAD commit and checks it each iteration. If HEAD
changed unexpectedly (you committed something outside the rail), you'll see this.

**Resolution if the extra commit was intentional:**
```bash
sm refit --skip "manual fix applied outside rail: <brief reason>"
```

This parks the current gate as skipped and advances to the next. Use sparingly and
document why.

**Resolution if the extra commit was accidental:**
Don't try to undo the commit. File a friction packet — this is trickier than it looks.

### `blocked_on_failure` (normal)

This is NOT an error — it means the gate ran, failed, and is waiting for you to fix
the code. The output will tell you exactly what to fix. This is the expected iteration
loop.

---

## Step 9: Finishing the Refit

When all gates are either `completed` or `skipped`:

```bash
sm refit --finish
```

This transitions the repo from remediation to maintenance mode. After this:

```bash
sm scour --no-auto-fix   # final full sweep — should be clean
git push origin refit/round-2-<date>
gh pr create \
  --title "refactor: slop-mop round-2 remediation rail" \
  --body-file /tmp/refit_pr_body.md
```

---

## Step 10: The Friction Protocol — CRITICAL

**This section is mandatory.** Do NOT skip it.

A "friction packet" is a structured report you generate when slop-mop itself behaves
unexpectedly. You hand it to the **slop-mop development agent** (a separate
conversation from yours) and wait for a resolution packet before continuing.

### WHEN to generate a friction packet

Generate one immediately if ANY of the following occur:

1. `sm refit --iterate` exits with status other than 0, 1, or 2 (unexpected exit code)
2. `sm refit --iterate` crashes with a Python traceback
3. `sm refit --start` fails with an error that doesn't match a known precheck blocker
4. A gate's prescribed fix makes no sense (e.g. "fix X in file Y" but Y doesn't have X)
5. `sm` produces output that appears inconsistent with what the plan says the current
   gate should be
6. A gate passes locally (`sm swab -g <gate>`) but `--iterate` says it failed
7. Any gate auto-fix corrupts a file (produces syntax errors / crashes the gate next
   time)

### WHEN NOT to generate a friction packet

- Gate fails because the project code has the problem the gate detects → fix the code
- `blocked_on_failure` → normal gate failure → fix the code
- `blocked_on_dirty_entry` → you have uncommitted changes → clean up
- `blocked_on_dirty_worktree` → same

### Friction packet format

```
FRICTION PACKET
===============
Date: <date>
Command: <exact command you ran>
Exit code: <code>
Expected behavior: <what you expected>
Actual behavior: <what happened>

Terminal output (verbatim, no truncation):
---
<paste output here>
---

Repo state:
  Branch: <git branch>
  HEAD: <git rev-parse HEAD>
  Plan status: <cat .slopmop/refit/plan.json | python3 -c "import sys,json; p=json.load(sys.stdin); print(p.get('status'), p.get('current_gate'), p.get('current_index'))">
  Config hash: <sha256sum .sb_config.json 2>/dev/null | cut -c1-16>

What I tried / what I ruled out:
  <brief list if any>

Blocker type: blocking | non-blocking
```

### Where to send it

Post the friction packet to the **slop-mop development conversation** (not this one).
That agent will:
1. Diagnose the issue in the slop-mop codebase
2. Produce a fix (with commit SHA)
3. Return a **resolution packet** with:
   - What changed in slop-mop
   - How to re-install the fix
   - The exact command to run next to resume your refit

**Do not work around friction.** Working around it (e.g. manually committing the gate
fix to bypass the rail) creates a harder-to-diagnose mess later. Stop, report, wait.

---

## Project Characteristics Reference

| Property | Value |
|----------|-------|
| Language (primary) | TypeScript / Node.js |
| Language (edge fns) | Deno (TypeScript) |
| Supabase edge functions | `supabase/functions/<name>/index.ts` |
| Deno unit tests | `supabase/functions/**/*.unit.test.ts` |
| Deno test command | `deno test --allow-all --no-check 'supabase/functions/**/*.unit.test.ts'` |
| Node test framework | Jest (via `npm run test`) |
| Coverage (Deno) | lcov via `deno coverage --lcov` |
| Coverage (Node) | Jest JSON summary |
| Package manager | npm |
| Deno config | `deno.json` at repo root |
| CI workflows | `.github/workflows/` |

**Known hybrid quirks:**
- `deno.json` and `package.json` coexist at root — don't let Node gates try to run
  Deno tests and vice versa; the config seeding in Step 3 handles this
- Supabase edge functions use Deno's import-map URL scheme; TypeScript strict mode
  violations are common in these files
- `supabase/functions/_broken_tests/` exists with `.broken` extension — these are
  intentionally disabled and should stay that way

---

## Files to Copy Verbatim from PR #75 (Fast-Forward Candidates)

These files were added/substantially rewritten in PR #75 and likely still apply to
main without modification. Verify each before staging:

| File | What it does | Copy if |
|------|-------------|---------|
| `.github/workflows/slop-check.yml` | CI quality gate workflow | File doesn't exist in main or is stale |
| `docs/CONVENTIONS.md` | Coding conventions (PR added this) | Main has an older version |
| `scripts/run-function-tests.sh` | Deno test runner script | Doesn't exist or is stale |
| `eslint.config.js` | ESLint flat config added by PR | Doesn't exist |

For test files added by PR #75 (the large Deno unit test suite), do NOT blindly copy
— the gate's coverage output will tell you what's actually untested in the current
codebase. Use the PR #75 test files as templates/patterns, not wholesale copies.

---

## Commit Hygiene

The refit rail auto-generates commit messages for each gate. Do not modify them. Each
commit message follows the pattern:

```
fix(<gate-slug>): <gate short description>

Gate: <gate-id>
Refit plan: .slopmop/refit/plan.json
```

If auto-commit fails (`blocked_on_commit`), check `git status` first — if the gate's
fix produced no actual changes (already passed), run `sm refit --skip "gate already
clean"`. If there are changes but the commit genuinely failed, file a friction packet.

---

## Iteration Cheatsheet

```bash
# Normal run — just keep re-running this
sm refit --iterate

# Gate is blocked, you've fixed the code, re-run:
sm refit --iterate

# Gate already passes (no changes needed), advance:
# (--iterate handles this automatically: "advanced without commit")

# Skip a gate (only when you have a good reason + HEAD drift escape):
sm refit --skip "reason: <one line>"

# Check plan state at any time:
cat .slopmop/refit/plan.json | python3 -c \
  "import sys, json; p = json.load(sys.stdin); \
   print('status:', p.get('status')); \
   print('current gate:', p.get('current_gate')); \
   print('idx:', p.get('current_index'), 'of', len(p.get('items', [])))"

# Check config:
sm config --show

# Tune gate config post-init:
sm config --set <gate-id> <field> <value>
sm config --unset <gate-id> <field>

# Doctor check:
sm doctor

# Pre-push full sweep:
sm scour --no-auto-fix
```

---

## Summary of What's New Since Round-1

These slop-mop capabilities did not exist when PR #75 was created. They will affect
your run:

1. **`myopia:interactive-assumptions` gate** — new SCOUR gate, will appear in your
   plan. Catches `npx` without `--yes` and `apt-get` without `-y`.

2. **Native Deno coverage** — `coverage_format = "deno"` is now a first-class config
   field. You don't need the shell-wrapper workaround from PR #75.

3. **`sm config --set/--unset`** — post-init gate-field editing without touching the
   JSON directly.

4. **Off-rail guards** (new in current dev):
   - `blocked_on_dirty_entry` — prevents accidental change bundling
   - `warn_config_drift` — warns when `.sb_config.json` changes after plan generation
   - `blocked_on_head_drift` now includes a `sm refit --skip` recovery hint

5. **`stdin=DEVNULL`** on all subprocesses — no gate will hang waiting for interactive
   input. Any gate that previously hung should flow cleanly now.

---

*End of Codex starting prompt. Good luck. When in doubt, stop and file a friction packet.*
