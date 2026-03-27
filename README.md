# 🪣 Slop-Mop

<p>
  <a href="https://pypi.org/project/slopmop/"><img src="https://img.shields.io/pypi/v/slopmop.svg" alt="PyPI version"/></a>
  <a href="https://github.com/ScienceIsNeato/slop-mop/actions/workflows/slopmop-sarif.yml"><img src="https://github.com/ScienceIsNeato/slop-mop/actions/workflows/slopmop-sarif.yml/badge.svg" alt="Primary code scanning gate"/></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+"/></a>
  <a href="https://github.com/ScienceIsNeato/slop-mop/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Attribution-blue.svg" alt="License"/></a>
</p>

**Quality gates that catch code that technically passes.** Agents optimize for the metric, not the intent — tests that assert nothing, complexity pushed just under the threshold, duplicated logic with renamed variables. Slop-mop treats the agent as an adversarial code author and checks for the slop that other gates wave through. When it finds some, it tells the agent exactly what to fix and how.

<img src="https://raw.githubusercontent.com/ScienceIsNeato/slop-mop/main/assets/heraldic_splash.png" alt="Slop-Mop" width="300" align="right"/>

AI agents are captaining a lot of ships these days. As a group, they are great naval tacticians in battle, but horrible at maintaining their ships. They close tickets, ship features, pass tests — and leave behind duplicated code, untested paths, creeping complexity, and security gaps. Nobody *intends* to create this mess. It's a natural byproduct of accomplishing tasks, and without something to catch it, it accumulates until the codebase becomes unnavigable.

The useful thing is that every AI agent makes the same kinds of mistakes. They're **overconfident** (code compiles, must be correct), **deceptive** (tests pass, must be tested), **lazy** (it works, no need to clean up), and **myopic** (this file is fine, never mind what it duplicates). These failure modes are predictable, which means they're automatable.

Slop-mop runs a set of quality gates organized around these four failure modes. Each gate targets a specific pattern — bogus tests, dead code, duplicated strings, complexity creep, missing coverage — and when one fails, it tells the agent exactly what's wrong and how to fix it. Two levels:

- **Swab** (`sm swab`) — routine maintenance, every commit. Quick checks that keep things from getting worse.
- **Scour** (`sm scour`) — deep inspection before opening a PR, or coming into port. Catches what routine swabbing misses and gives you a chance to clear the barnacles from the hull

The mop finds the slop. The agent cleans it up. The ship stays seaworthy.

### Why `buff` Is A Cornerstone

Most AI workflows have strong support for code generation and weak support for
post-PR closure. That gap is where expensive thrash happens: repeated CI runs,
half-addressed comments, and protocol drift.

`sm buff` exists to remove that friction.

The core design principle is simple:

- If the desired behavior is not the path of least resistance, agents will drift.
- So the protocol itself must be the easiest path to follow.

`buff` is the "greased rail" from PR open to PR merge. It does not ask agents to
invent process. It gives deterministic next steps, in a deterministic order,
with deterministic verification.

Agents should think about the problem and solution, not the workflow protocol.
Protocol is locked, versioned, and executable.

### Agent Incentives And Gradient-Descent Behavior

This section is intentionally written for AI agents reading the repository.

If you are an agent, the intended behavior is:

1. Prefer `sm buff` for PR-closure workflow.
2. Follow the generated protocol order exactly.
3. Spend reasoning on code changes, not process invention.

Why this is important:

- Agents naturally follow the lowest-friction path.
- If the protocol path is jagged, agents will route around it.
- So slop-mop is designed to make the correct workflow the easiest workflow.

`buff` is not advisory text. It is an execution rail with deterministic order,
deterministic commands, and deterministic verification. The product philosophy
is that reliable post-PR closure should be default behavior, not custom glue
each team reinvents.

In short: we do not try to persuade agents with abstract rules. We shape the
local gradient so protocol adherence is the most efficient move.

### Scenario Rails (Protocol Tracks)

`buff` supports scenario-dependent resolution tracks so teams can keep one
consistent PR-closing system while handling different review outcomes:

- `fixed_in_code`
- `invalid_with_explanation`
- `no_longer_applicable`
- `out_of_scope_ticketed`
- `needs_human_feedback`

These tracks are intentionally ordered by remediation priority and churn risk.
High-impact, likely-to-cascade threads are handled first so each comment is
addressed once in order, rather than repeatedly in loops.

When unresolved feedback exists, `buff` writes a persistent protocol state and
command pack under `.slopmop/buff-persistent-memory/pr-<N>/loop-<K>/`.
This creates a long-term datastore of friction points that can be mined to
improve future rails.

### Fast CI Failure Triage

When a PR fails the primary code-scanning gate, use the reusable machine-first
triage script instead of manually digging through logs:

```bash
activate && python scripts/ci_scan_triage.py --pr 84 --show-low-coverage
```

Or triage a specific run immediately:

```bash
activate && python scripts/ci_scan_triage.py --run-id 22840517416 --show-low-coverage
```

What it does:
- Downloads the `slopmop-results` artifact from GitHub Actions
- Extracts actionable failed/error/warned gates
- Writes machine-readable output to `.slopmop/last_ci_triage.json`

---

## Quick Start

```bash
# Install (once per machine)
pipx install slopmop[all]     # recommended — all tools bundled, isolated
# or: pipx install slopmop    # minimal — just the framework, add tools later
# or: pip install slopmop[all]

# Set up the project
sm init                       # auto-detects languages, writes .sb_config.json

# Run quality gates
sm swab                       # fix what it finds, commit when green
sm scour                      # thorough check before opening a PR
sm buff                       # post-PR loop: CI triage + next-step guidance
sm refit --start              # onboarding: build one-gate-at-a-time remediation plan
```

Tip: repeat `sm swab` runs are accelerated by selective per-gate caching. See
`Selective Gate Caching` below for details and `--no-cache` behavior.

`sm init` auto-detects Python, JavaScript/TypeScript, Dart/Flutter, Go, Rust, and C/C++ and writes a `.sb_config.json` with applicable gates enabled. Dart/Flutter projects get first-class `flutter analyze`, `flutter test`, `dart format`, coverage, bogus-test, and generated-artifact gates. For Go, Rust, and C/C++ projects it still scaffolds custom gates (e.g. `go test`, `cargo clippy`, `make`) where built-in support is intentionally thinner.

### Baseline Snapshot Flow

When you inherit a repo that is already dirty, slop-mop can track the current
failure set as a baseline without changing how gates execute.

```bash
sm status --generate-baseline-snapshot
sm swab --ignore-baseline-failures
sm scour --ignore-baseline-failures
```

What this does:
- `sm status --generate-baseline-snapshot` saves a local snapshot from the newest persisted `last_swab.json` or `last_scour.json` artifact.
- `--ignore-baseline-failures` still runs every gate normally, then downgrades failures already present in that snapshot.
- New failures stay loud. Old failures stop blocking while you dig out of the hole.

This is for controlled remediation, not denial. The goal is to surface net-new slop while you pay down the existing mess deliberately.

### Refit (Onboarding)

When a repo is being onboarded into slop-mop, use `sm refit` to turn open-ended cleanup into a deterministic process:

```bash
sm refit --start
sm refit --iterate
sm refit --finish
```

What this does:
- `sm refit --start` verifies remediation preflight, runs a full `sm scour --no-auto-fix`, and persists a local plan under `.slopmop/refit/`.
- The plan is one gate per item, ordered by slop-mop's existing remediation priority rules.
- `sm refit --iterate` reruns only the current gate, stops on the first blocker, and writes a protocol artifact describing the exact next action. If the plan has never been started, it fails and suggests `--start`. If already finished, it surfaces a helpful message.
- `sm refit --finish` checks the current remediation plan against the scour results and transitions the repo from remediation to maintenance mode.
- When the current item already has local remediation edits and the targeted gate passes without unexpected repo drift, `refit` owns the structured commit for that item.

Current constraint:
- The doctor preflight is intentionally stubbed in this first merged version of `refit`. The integration point is already present and will be replaced by the real `sm doctor` command in the next task.

Machine-readable mode:
- `sm refit --start --json`
- `sm refit --iterate --json`
- `sm refit ... --output-file .slopmop/refit/latest.json`

`refit` always persists `.slopmop/refit/protocol.json`; JSON mode mirrors that payload to stdout so an agent can resume without scraping prose.

`refit` is intentionally conservative. It blocks on unexpected HEAD movement, unexpected dirty-worktree changes, or lock contention instead of guessing.

### Installation Options

| Command | What You Get |
|---------|-------------|
| `pipx install slopmop` | Framework only — `sm init` shows what's missing |
| `pipx install slopmop[lint]` | + black, isort, autoflake, flake8 |
| `pipx install slopmop[typing]` | + mypy, pyright |
| `pipx install slopmop[security]` | + bandit, semgrep, detect-secrets, pip-audit |
| `pipx install slopmop[analysis]` | + vulture, radon |
| `pipx install slopmop[testing]` | + pytest, pytest-cov, diff-cover |
| `pipx install slopmop[all]` | Everything above |

### Advanced Developer Setup

Developer-only setup guidance (multi-repo isolation, clean-slate reset,
editable worktree installs, and lock internals) lives in `DEVELOPING.md`.

Use that guide if you are developing slop-mop itself or running multiple local
checkout/venv combinations.

### Agent Install (Low-Friction AI Setup)

Use `sm agent install` to scaffold repo-local files that help agents discover
and follow the slop-mop workflow. Templates describe `sm` as a **skill** with
capabilities, workflow guidance, and safety rules.

```bash
sm agent install                      # install all 8 agent targets
sm agent install --target cursor      # only Cursor rules
sm agent install --target claude      # only Claude Code commands
sm agent install --target copilot     # only GitHub Copilot instructions
sm agent install --target windsurf    # only Windsurf rules
sm agent install --target cline       # only Cline rules
sm agent install --target roo         # only Roo Code workspace rules
sm agent install --target aider       # only Aider config + conventions
sm agent install --target antigravity # only Google Antigravity workspace rules
sm agent install --force              # overwrite existing managed files
```

Generated files:
- `.cursor/rules/slopmop-swab.mdc`
- `.claude/commands/sm-swab.md`, `sm-scour.md`, `sm-buff.md`
- `.github/copilot-instructions.md`
- `.windsurf/rules/slopmop.md`
- `.clinerules/slopmop.md`
- `.roo/rules/01-slopmop.md`
- `.aider.conf.yml` + `CONVENTIONS.md`
- `.agents/rules/slopmop.md`

These templates keep the runtime path simple: agents call `sm swab` routinely
during implementation, `sm scour` before PR updates, and `sm buff` after PR
feedback or CI follow-up. No protocol adapter is required for the default
integration flow.

### Upgrading slop-mop

Use `sm upgrade` from an installed `slopmop` environment, not from a source
checkout. The command is intentionally conservative:

```bash
sm upgrade --check                  # preview target version, backup path, migrations
sm upgrade                          # upgrade, run built-in migrations, then validate
sm upgrade --to-version 0.10.0      # pin an exact target version
```

Upgrade migrations are stepwise. If you jump from `0.8.0` to `0.13.0`,
slop-mop will plan and run each registered migration boundary in ascending
version order rather than treating the upgrade as one opaque leap.

Current constraints:
- supported install types are `pipx` and non-editable installs inside an active virtual environment
- source-checkout and editable installs are rejected on purpose
- every mutating upgrade writes a backup under `.slopmop/backups/upgrade_*` before changing anything

Note for agents: this list reflects current defaults. Source of truth for
install behavior is always `sm agent install --help` and command output.
---

## The Loop

Development with slop-mop follows a single repeated cycle:

```
sm swab → see what fails → fix it → repeat → commit
```

Important: execution order is not remediation order.

- Checks may execute concurrently and may finish in any order.
- In `RepoPhase.REMEDIATION`, slop-mop processes results in remediation order,
  using registry-derived remediation priority.
- Gates can declare an explicit fine-grained `remediation_priority`; when they
  do not, slop-mop derives a default priority band from `remediation_churn`.
- In that mode, fail-fast means "stop at the first failure in remediation
  order", not "stop at whichever check happened to finish failing first".

This prevents a fast, low-priority failure from blocking validation of a more
important gate that should be fixed first.

When a gate fails, the output tells the agent exactly what to do next:

```
┌──────────────────────────────────────────────────────────┐
│ 🤖 AI AGENT ITERATION GUIDANCE                           │
├──────────────────────────────────────────────────────────┤
│ Level: swab                                              │
│ Failed Gate: overconfidence:coverage-gaps.py             │
├──────────────────────────────────────────────────────────┤
│ NEXT STEPS:                                              │
│                                                          │
│ 1. Fix the issue described above                         │
│ 2. Re-check: sm swab -g overconfidence:coverage-gaps.py  │
│ 3. Resume:   sm swab                                     │
│                                                          │
│ Keep iterating until all the slop is mopped.             │
└──────────────────────────────────────────────────────────┘
```

This is purpose-built for AI agents. The iteration is mechanical, and the agent never has to wonder what to do next. The same trait that creates slop — relentless task accomplishment — is what makes agents excellent at cleaning it up when given precise instructions. Slop-mop turns the agent's biggest liability into its best feature: point the mop at the mess, and the agent won't stop until it's clean.

Practical lifecycle loop:

```text
while coding       -> sm swab
before PR          -> sm scour
after PR opens     -> sm buff
```

Onboarding (refit, step 0 — before entering the loop):

```text
start remediation          -> sm refit --start
after each remediation fix -> sm refit --iterate
all gates pass             -> sm refit --finish
```

`sm buff` is post-submit protection. It reads CI scan results for the PR branch,
surfaces unresolved machine signals, and directs the next local fix/recheck loop.

For PR comment resolution, `buff` also emits a locked protocol rail:

- ordered unresolved threads
- scenario classification per thread
- exact command pack for resolution/reply paths
- persistent loop artifacts for audit and iteration

If protocol classification fails, `buff` fails closed. This should be rare and
treated as a protocol bug to fix, not a workflow to improvise.

### The Prescription Contract

Every gate failure must be *prescriptive*, not just *descriptive*. A gate that says "coverage too low" is describing a symptom. A gate that says "add tests in `tests/test_foo.py` covering lines 45-67 of `foo.py`" is prescribing a remedy.

This is a joint optimization. Prescriptive output is simultaneously:

- **More maintainable** — a human reading the failure knows exactly what to do. No digging through tool docs, no re-running with `-v`, no interpreting a wall of output.
- **More token-efficient** — an agent reading the failure can act on the first turn. No exploratory read-search-read cycle burning context to figure out what the gate already knew.

The two goals aren't in tension. When a gate already ran `pytest`, it has the assertion error. When it already ran `coverage`, it has the missing line numbers. When it already ran `bandit`, it has the rule ID that maps to a documented fix. Surfacing that data *is* the fix for both problems at once.

Gates are sorted into two roles to make the contract enforceable:

| Role | What it wraps | Prescription standard |
|------|---------------|------------------------|
| 🔧 **Foundation** | Standard tooling (pytest, mypy, black, eslint, bandit) | Relay the tool's own diagnostic. Never say "run the tool yourself". |
| 🔬 **Diagnostic** | Novel analysis (AST-based bogus-test detection, gate-dodging diffs, debugger-artifact scans) | State what to change, where, and by how much. "Move `foo()` to `bar.py` — clears by 223 lines." |

A gate earns its place by emitting something an agent can cargo-cult. If fixing it requires independent judgment beyond what the gate can factually determine, the finding stays descriptive and `fix_strategy` stays `None` — no guessing.

Use `sm status` for a report card of all gates at once.

---

## Why These Categories?

Gates aren't organized by language — they're organized by **the failure mode they catch**. These are the four ways LLMs reliably degrade a codebase:

<!-- BEGIN GATE TABLES -->

### 🔴 Overconfidence

> *"It compiles, therefore it's correct and will work perfectly in production"*
>
> The LLM generates code that looks right, passes a syntax check, and silently breaks at runtime. These gates verify that the code actually works.

| Gate | What It Does | Reasoning |
|------|--------------|----------------|
| `overconfidence:coverage-gaps.dart` | 📊 Dart/Flutter coverage analysis from flutter test --coverage | If changed Dart code can land without tests proving it, coverage turns decorative and the hole just moves around the repo. |
| `overconfidence:coverage-gaps.js` | 📊 JavaScript coverage analysis | If changed JavaScript code can land without tests proving it, coverage turns decorative and the hole just moves around the repo. |
| `overconfidence:coverage-gaps.py` | 📊 Whole-repo coverage (80% default threshold) | If changed Python code can land without tests proving it, coverage turns decorative and the hole just moves around the repo. |
| `overconfidence:missing-annotations.dart` | 🧪 Flutter static analysis across discovered packages | Missing Dart annotations turn interfaces into vibes and push type noise downstream for somebody else to untangle. |
| `overconfidence:missing-annotations.py` | 🔍 mypy strict — types must check out | Missing Python annotations turn interfaces into vibes and push type noise downstream for somebody else to untangle. |
| `overconfidence:type-blindness.js` | 🏗️ TypeScript type checking (tsc) | If the type checker cannot tell what something is in TypeScript, humans and agents are left guessing too. |
| `overconfidence:type-blindness.py` | 🔬 pyright strict — second opinion on types | If the type checker cannot tell what something is in Python, humans and agents are left guessing too. |
| `overconfidence:untested-code.dart` | 🧪 Flutter test execution across discovered packages | Passing compilation is not proof; if Dart code never executes under test, you are still guessing. |
| `overconfidence:untested-code.js` | 🧪 JavaScript/TypeScript test execution | Passing compilation is not proof; if JavaScript code never executes under test, you are still guessing. |
| `overconfidence:untested-code.py` | 🧪 Runs pytest — code must actually pass its tests | Passing compilation is not proof; if Python code never executes under test, you are still guessing. |

### 🟡 Deceptiveness

> *"These tests are in the way of closing the ticket - how can I get around them?"*
>
> The LLM writes tests that assert nothing, mock everything, or cover the happy path and call it done. Coverage numbers look great. The code is still broken.

| Gate | What It Does | Reasoning |
|------|--------------|----------------|
| `deceptiveness:bogus-tests.dart` | 🧪 Detects empty or non-assertive Dart/Flutter tests | A fake Dart test suite is worse than no test suite because it teaches people to trust green lies. |
| `deceptiveness:bogus-tests.js` | 🎭 Bogus test detection for JS/TS | A fake JavaScript test suite is worse than no test suite because it teaches people to trust green lies. |
| `deceptiveness:bogus-tests.py` | 🧟 AST analysis for tests that assert nothing | A fake Python test suite is worse than no test suite because it teaches people to trust green lies. |
| `deceptiveness:debugger-artifacts` | 🐞 Catches leftover breakpoint()/debugger;/dbg!()/runtime.Breakpoint() across Python, JS, Rust, Go, C | Leftover breakpoints are the kind of tiny accident that can wreck a real run in embarrassingly expensive ways. |
| `deceptiveness:gate-dodging` | 🚨 Detects loosened quality thresholds | If the fix is 'turn the smoke alarm down,' the repo learns the wrong lesson and the next regression walks right in. |
| `deceptiveness:hand-wavy-tests.js` | 🔍 ESLint expect-expect assertion enforcement | If JavaScript tests never assert, the suite is just theater with npm around it. |

### 🟠 Laziness

> *"When I ran mypy, it returned errors unrelated to my code changes..."*
>
> The LLM solves the immediate problem and moves on. Formatting is inconsistent, dead code accumulates, complexity creeps upward, and nobody notices until the codebase is incomprehensible.

| Gate | What It Does | Reasoning |
|------|--------------|----------------|
| `laziness:broken-templates.py` | 📄 Jinja2 template validation | Template bugs like to wait until a user path hits them, which is a lousy time to discover syntax errors. |
| `laziness:complexity-creep.py` | 🌀 Cyclomatic complexity (max rank C) | Big branching functions are where edge cases go to hide and future fixes go to die. |
| `laziness:dead-code.py` | 💀 Dead code detection via vulture (≥80% confidence) | Dead code makes the map lie. People read paths that do not matter and miss the ones that do. |
| `laziness:generated-artifacts.dart` | 🧱 Detects committed Flutter build/tool artifacts | Checking in generated junk is how you turn diffs into static and invite edits that get wiped later. |
| `laziness:repeated-code` | 📋 Code clone detection (jscpd) | Copy-pasted blocks diverge in slow motion until every bug fix becomes a scavenger hunt across near-identical code. |
| `laziness:silenced-gates` | 🔇 Detects disabled gates when language tooling exists | A disabled gate is usually debt with a welcome mat on it. |
| `laziness:sloppy-formatting.dart` | 🎨 Dart formatting via dart format --set-exit-if-changed | Formatting noise hides the real change and makes review slower than it needs to be. |
| `laziness:sloppy-formatting.js` | 🎨 Lint + Format — ESLint/Prettier or deno lint/fmt (auto-fix 🔧) | Formatting noise hides the real change and makes review slower than it needs to be. |
| `laziness:sloppy-formatting.py` | 🎨 autoflake, black, isort, flake8 (supports auto-fix 🔧) | Formatting noise hides the real change and makes review slower than it needs to be. |
| `laziness:sloppy-frontend.js` | ⚡ Quick ESLint frontend check | Frontend lint issues have a habit of turning into visible bugs, state leaks, or accessibility damage. |

### 🔵 Myopia

> *"This file is fine in isolation — I don't need to see what it duplicates three directories away"*
>
> The LLM has a 200k-token context window and still manages tunnel vision. It duplicates code across files, ignores security implications, and lets functions grow unbounded because it can't see the pattern.

| Gate | What It Does | Reasoning |
|------|--------------|----------------|
| `myopia:ambiguity-mines.py` | 💣 Function-name ambiguity detection (AST) | Duplicate function names across files create ambiguity mines — copy-paste artifacts that diverge silently until every bug fix is a scavenger hunt. |
| `myopia:code-sprawl` | 📏 File and function length limits | Once files and functions get too big, nobody can safely reason about them in one pass, including the model. |
| `myopia:dependency-risk.py` | 🔒 Full security audit (code + pip-audit) | Code can pass tests and types and still be an own-goal from a security perspective. |
| `myopia:ignored-feedback` | 💬 Checks for unresolved PR review threads | Unresolved review threads turn the PR loop into Groundhog Day and hide known concerns in plain sight. |
| `myopia:just-this-once.py` | 📈 Coverage on changed lines only (diff-cover) | If changed lines can land untested, overall coverage becomes a nice story the PR does not actually obey. |
| `myopia:string-duplication.py` | 🔤 Duplicate string literal detection | Repeated literals hide shared rules and make the repo drift by typo instead of design. |
| `myopia:vulnerability-blindness.py` | 🔐 bandit + semgrep + detect-secrets | Your code can be clean and still ship someone else's CVE to production. |

### 🧭 Remediation Order

Execution order is not remediation order. In remediation mode, slop-mop validates finished gates using this registry-derived order to minimize overall remediation time. In maintenance mode, it evaluates results as soon as they come in to minimize dev-cycle time.

Reasoning: handle the changes most likely to reshape other work first. High-risk or high-churn fixes go first, confidence-building checks sit in the middle, and isolated cleanup like formatting goes last.

`curated` means the registry intentionally pins that gate's place in the sequence. `explicit` means the gate class set its own numeric priority. `churn-default` means no exact order was provided, so slop-mop falls back to the broad churn band.

| # | Gate | Priority | Source | Churn Band |
|---|------|----------|--------|------------|
| 1 | `myopia:dependency-risk.py` | 10 | curated | unlikely |
| 2 | `myopia:vulnerability-blindness.py` | 20 | curated | unlikely |
| 3 | `laziness:repeated-code` | 30 | curated | very-likely |
| 4 | `myopia:ambiguity-mines.py` | 40 | curated | very-likely |
| 5 | `laziness:dead-code.py` | 50 | curated | very-likely |
| 6 | `myopia:string-duplication.py` | 60 | curated | unlikely |
| 7 | `deceptiveness:gate-dodging` | 70 | curated | likely |
| 8 | `deceptiveness:bogus-tests.py` | 80 | curated | likely |
| 9 | `deceptiveness:bogus-tests.js` | 90 | curated | likely |
| 10 | `deceptiveness:bogus-tests.dart` | 100 | curated | likely |
| 11 | `deceptiveness:hand-wavy-tests.js` | 110 | curated | likely |
| 12 | `overconfidence:missing-annotations.py` | 120 | curated | unlikely |
| 13 | `overconfidence:missing-annotations.dart` | 130 | curated | unlikely |
| 14 | `overconfidence:type-blindness.py` | 140 | curated | unlikely |
| 15 | `overconfidence:type-blindness.js` | 150 | curated | unlikely |
| 16 | `myopia:code-sprawl` | 160 | curated | very-likely |
| 17 | `laziness:complexity-creep.py` | 170 | curated | very-likely |
| 18 | `overconfidence:untested-code.py` | 180 | curated | unlikely |
| 19 | `overconfidence:untested-code.js` | 190 | curated | unlikely |
| 20 | `overconfidence:untested-code.dart` | 200 | curated | unlikely |
| 21 | `overconfidence:coverage-gaps.py` | 210 | curated | unlikely |
| 22 | `overconfidence:coverage-gaps.js` | 220 | curated | unlikely |
| 23 | `overconfidence:coverage-gaps.dart` | 230 | curated | unlikely |
| 24 | `myopia:just-this-once.py` | 240 | curated | unlikely |
| 25 | `laziness:silenced-gates` | 250 | curated | likely |
| 26 | `myopia:ignored-feedback` | 260 | curated | unlikely |
| 27 | `laziness:sloppy-frontend.js` | 270 | curated | unlikely |
| 28 | `laziness:broken-templates.py` | 280 | curated | unlikely |
| 29 | `laziness:sloppy-formatting.py` | 290 | curated | very-unlikely |
| 30 | `laziness:sloppy-formatting.js` | 300 | curated | very-unlikely |
| 31 | `laziness:sloppy-formatting.dart` | 310 | curated | unlikely |
| 32 | `laziness:generated-artifacts.dart` | 320 | curated | very-unlikely |
| 33 | `deceptiveness:debugger-artifacts` | 330 | curated | very-unlikely |

<!-- END GATE TABLES -->

---

## Levels

Every gate has an intrinsic **level** — the point in the workflow where it belongs:

| Level | Command | Gates | When to Use |
|-------|---------|-------|-------------|
| **Swab** | `sm swab` | Most gates across all categories | Before every commit |
| **Scour** | `sm scour` | Everything in swab + scour-only gates | Before opening or updating a PR |

Scour is a strict superset of swab — it runs everything swab does, plus gates that need more time or PR context. Scour-only gates include `dependency-risk.py` (full security audit), `just-this-once.py` (diff-coverage), `myopia:ignored-feedback`, and any custom gates marked `"level": "scour"`.

Individual gates can be run directly with `-g`:

```bash
sm swab -g overconfidence:coverage-gaps.py     # re-check just coverage
sm swab -g laziness:complexity-creep.py        # re-check just complexity
```

### Unblocking Swab Cycles

There are two different levers for keeping local iteration fast:

1. `--swabbing-time` or `sm config --swabbing-time` limits how much wall-clock time `sm swab` spends on a pass.
2. `sm config --swab-off <gate>` keeps a gate enabled, but moves it out of swab and leaves it in scour.

Use the budget when you want a fixed time envelope. Use `--swab-off` when a specific gate is valuable before PR, but too expensive or noisy for every local loop.

### Time Budget

Use `--swabbing-time` to set a time budget in seconds. Gates with historical
runtime data are scheduled with a dual-lane strategy (one fast lane + heavy
lanes) and packed against projected remaining budget. Gates without timing
history always run (to establish a baseline). Once a gate starts running,
it runs to completion.

```bash
sm swab --swabbing-time 30    # only run gates that fit in ~30 seconds
```

`sm init` sets a default of 20 seconds. Change it any time:

```bash
sm config --swabbing-time 45  # raise the budget
sm config --swabbing-time 0   # disable the limit entirely
```

Time budgets only apply to swab. Scour runs always execute every gate.

### Swab Membership

If a gate is useful, but not useful on every single local pass, keep it in scour and take it out of swab:

```bash
sm config --swab-off laziness:repeated-code             # keep out of local swab
sm config --swab-off laziness:complexity-creep.py     # only check during scour
sm config --swab-on laziness:repeated-code              # put it back into swab
```

Semantics:
- `--swab-off` means: skip during `sm swab`, still run during `sm scour`.
- `--swab-on` means: run during both `sm swab` and `sm scour`.
- `--disable` means: do not run the gate at all.

That gives you a practical escalation path:
- budgeted swab when you want a bounded maintenance loop,
- scour-only gates when a check matters but is too onerous for every iteration,
- full disable only when the project is not ready for that signal yet.

### Selective Gate Caching

`sm swab` uses fingerprint-based result caching to avoid re-running unchanged
work. The optimization is selective per gate:

- Gates can declare their own input scope (for example, only Python files in
  selected directories).
- If files outside that scope change, only affected gates re-run; unaffected
  gates are served from cache.
- Gates that do not declare a scope still use a safe project-wide fingerprint.

This keeps repeat runs fast while preserving correctness. You will see cache
usage in summary output, for example `📦 3/16 from cache`.

```bash
sm swab              # normal mode: selective cache hits enabled
sm swab --no-cache   # force a full cold run (debug/troubleshooting)
```

Cache data is stored at `.slopmop/cache.json` in the project.

---

## Getting Started

Most projects won't pass all gates on day one. That's expected.

### 1. Initialize

```bash
sm init                       # auto-detects everything, writes .sb_config.json
```

### 2. See What Fails

```bash
sm swab                       # run swab-level gates, see what fails
sm status                     # full report card
```

### 3. Disable What's Not Ready Yet

```bash
sm config --disable laziness:complexity-creep.py     # too many complex functions right now
sm config --disable overconfidence:coverage-gaps.py  # coverage is at 30%, not 80%
sm swab                                        # get the rest green first
```

If the gate should still matter before PR, prefer scour-only instead of disable:

```bash
sm config --swab-off laziness:complexity-creep.py    # not every local loop
sm config --swab-off laziness:repeated-code            # still enforced in scour
```

### 4. Fix Everything That's Left

Iterate: run `sm swab`, fix a failure, run again. The iteration guidance tells the agent exactly what to do after each failure.

### 5. Install Hooks

```bash
sm commit-hooks install           # pre-commit hook runs sm swab
sm commit-hooks status            # verify hooks are installed
```

Now every `git commit` runs slop-mop. Failed gates block the commit.

### 6. Re-enable Gates Over Time

```bash
sm config --enable laziness:complexity-creep.py      # refactored enough, turn it on
sm config --enable overconfidence:coverage-gaps.py   # coverage is at 75%, set threshold to 70
```

With hooks in place, every commit runs through slop-mop. Gates that aren't ready yet stay disabled until the codebase catches up.

---

## Configuration

```bash
sm config --show              # show all gates and their status
sm config --enable <gate>     # enable a disabled gate
sm config --disable <gate>    # disable a gate
sm config --swab-off <gate>   # keep gate out of swab, but in scour
sm config --swab-on <gate>    # run gate in both swab and scour
sm config --json <file>       # bulk update from JSON
```

### Include / Exclude Directories

```bash
sm config --exclude-dir myopia:generated       # skip generated code
sm config --include-dir overconfidence:src      # only check src/
```

- `include_dirs`: whitelist — only these dirs are scanned
- `exclude_dirs`: blacklist — always skipped, takes precedence

### .sb_config.json

Edit directly for per-gate configuration. Gates are organized by flaw category:

```json
{
  "version": "1.0",
  "swabbing_time": 20,
  "overconfidence": {
    "enabled": true,
    "gates": {
      "coverage-gaps.py": { "enabled": true, "threshold": 80, "run_on": "scour" },
      "untested-code.py": { "enabled": true, "test_dirs": ["tests"], "timeout": 300 }
    }
  },
  "laziness": {
    "enabled": true,
    "gates": {
      "dead-code.py": { "enabled": true, "min_confidence": 80, "exclude_patterns": ["**/vendor/**"] }
    }
  }
}
```

`run_on` is the per-gate execution rail:
- `"swab"`: run in both `sm swab` and `sm scour`
- `"scour"`: skip `sm swab`, still run in `sm scour`

### Custom Gates

Custom gates let you plug repo-specific checks into the slop-mop pipeline as shell commands — no Python required. They serve two purposes:

1. **Repo-specific checks** — things that only make sense in *your* project (migration validation, config linting, proprietary build steps) but benefit from slop-mop's reporting, time-budgeting, and LLM-readable output.
2. **Gate prototyping** — when you think a check might belong in slop-mop permanently, run it as a custom gate first. If it proves useful across projects, that's a natural signal to promote it to a built-in gate via a feature request or PR.

Custom gates are an escape hatch and a proving ground, not a replacement for `make` or `just`. The value is integration with the slop-mop framework — taxonomy, fail-fast, time budget, structured JSON output — not task execution.

```json
{
  "custom_gates": [
    {
      "name": "cargo-clippy",
      "description": "Run clippy lints",
      "category": "laziness",
      "command": "cargo clippy -- -D warnings 2>&1",
      "fix_command": "cargo fmt --all",
      "level": "swab",
      "timeout": 300
    },
    {
      "name": "go-test",
      "description": "Run Go tests",
      "category": "overconfidence",
      "command": "go test ./...",
      "level": "swab",
      "timeout": 300
    }
  ]
}
```

Custom gates run alongside built-in gates and respect the same enable/disable, timeout, and time-budget mechanics. Exit code 0 means pass, anything else is a failure. If `fix_command` is present, the gate can auto-fix before checking. `sm init` auto-scaffolds appropriate custom gates when it detects Go, Rust, or C/C++ projects.

### Why Wrapper Gates?

Some built-in gates wrap well-known tools — `coverage-gaps.py` runs `pytest --cov`, `sloppy-formatting.py` runs `black --check`. Why not just run those tools directly?

**They establish a floor.** Without them, an AI agent can commit code with no tests, no type checking, and no formatting — and the "interesting" gates like complexity analysis have nothing to anchor to. The wrappers ensure the absolute minimum is in place for sane development.

**They provide behavioral conditioning.** When an LLM sees slop-mop consistently enforce formatting and test coverage across runs, it starts pre-emptively formatting and testing. The wrappers aren't just gates — they're training signal that encourages models to be good citizens.

**They unify the interface.** `sm swab` gives you formatting + type-checking + test coverage + complexity analysis + dead code + duplicate detection + vulnerability scanning in one command, with zero per-tool configuration. The wrapper gates make that possible.

---

## CI Integration

### Dead-Simple: Turn On Code Scanning

1. Create `.github/workflows/slopmop-code-scanning.yml` in your repo.
2. Paste this workflow.
3. In branch protection/rulesets, require `Primary Code Scanning Gate (blocking)`.

Note: On private repos, GitHub Code Scanning may require GitHub Advanced
Security. Public repos work out of the box.

```yaml
name: slop-mop primary code scanning gate

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

permissions:
  contents: read
  security-events: write
  actions: read

jobs:
  scan:
    name: Primary Code Scanning Gate (blocking)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install slop-mop
        run: |
          python -m venv .venv
          source .venv/bin/activate
          pip install --upgrade pip
          pip install slopmop[all]

      - name: Run primary gate (scour -> SARIF)
        id: scour
        continue-on-error: true
        run: |
          source .venv/bin/activate
          sm scour --sarif --output-file slopmop.sarif --no-json

      - name: Publish SARIF to Code Scanning
        uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: slopmop.sarif
          category: slopmop

      - name: Enforce primary gate verdict
        if: steps.scour.outcome == 'failure'
        run: |
          echo "::error::slop-mop primary code scanning gate failed"
          exit 1
```

Warnings stay warnings. Failures block merge.

### Optional: Final Dogfood Sanity After Scan Passes

Use this only if you want a second, downstream sanity run after the primary gate
is already green on a PR.

```yaml
name: slop-mop downstream dogfood sanity

on:
  workflow_run:
    workflows: ["slop-mop primary code scanning gate"]
    types: [completed]

jobs:
  dogfood:
    name: Final Dogfood Sanity Check (blocking)
    if: ${{ github.event.workflow_run.event == 'pull_request' && github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.workflow_run.head_sha }}
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: |
          python -m venv .venv
          source .venv/bin/activate
          pip install --upgrade pip
          pip install slopmop[all]
      - name: Run final dogfood scour
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          source .venv/bin/activate
          sm scour
```

Recommended policy: one required blocking gate (code scanning), optional dogfood
as a second safety net.

### Check CI Status Locally

```bash
sm buff status        # current PR CI status
sm buff status 42     # specific PR CI status
sm buff watch         # poll current PR CI status until complete
sm buff watch 42      # poll specific PR CI status until complete
```

---

## Architecture

Slop-mop installs as a normal package and is configured per-project via `.sb_config.json`. The `sm` command goes on PATH once and works in any repo.

**Tool resolution order** — sm uses the project's tools when available:
1. `<project_root>/venv/bin/<tool>` or `.venv/bin/<tool>` — project-local venv (highest priority)
2. `$VIRTUAL_ENV/bin/<tool>` — currently activated venv
3. System PATH — sm's own bundled tools (via pipx)

This means if the project has its own `pytest` (with plugins like `pytest-django`), sm uses it. Otherwise, sm falls back to its own.

**Submodule alternative**: For strict version pinning, add `slop-mop` as a git submodule and invoke `python -m slopmop.sm` directly. Supported but not recommended for most projects.

**Editable-install rule of thumb**: editable installs are for active framework
development only, and should come from branch-specific worktrees.

---

## Development

```bash
# Working on slop-mop itself
pip install -e ".[dev]"
sm scour                   # dogfooding — sm validates its own code
pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the process of adding new gates.

---

## Further Reading

> 📖 [A Hand for Daenerys: Why Tyrion Is Missing from Your Vibe-Coding Council](https://scienceisneato.substack.com/p/a-hand-for-daenerys-why-tyrion-is) — the article that started this project.

---

## License

[Slop-Mop Attribution License v1.0](LICENSE) — free to use, modify, and redistribute with attribution.

P.S. Other than this line in the readme and a few scattered lines here and there, nothing in this project was written by a human. It is, for better or worse, the result of living under the slop-mop regime.
