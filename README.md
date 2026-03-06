# 🪣 Slop-Mop

<p>
  <a href="https://pypi.org/project/slopmop/"><img src="https://img.shields.io/pypi/v/slopmop.svg" alt="PyPI version"/></a>
  <a href="https://github.com/ScienceIsNeato/slop-mop/actions/workflows/slopmop.yml"><img src="https://github.com/ScienceIsNeato/slop-mop/actions/workflows/slopmop.yml/badge.svg" alt="CI"/></a>
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
```

`sm init` auto-detects Python, JavaScript/TypeScript, Go, Rust, and C/C++ and writes a `.sb_config.json` with applicable gates enabled. For Go, Rust, and C/C++ projects it scaffolds custom gates (e.g. `go test`, `cargo clippy`, `make`) since built-in gates focus on Python and JS.

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

---

## The Loop

Development with slop-mop follows a single repeated cycle:

```
sm swab → see what fails → fix it → repeat → commit
```

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
| 🔬 **Diagnostic** | Novel analysis (duplicate strings, gate dodging, size limits) | State what to change, where, and by how much. "Move `foo()` to `bar.py` — clears by 223 lines." |

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

| Gate | What It Does |
|------|--------------|
| `overconfidence:coverage-gaps.js` | 📊 JavaScript coverage analysis |
| `overconfidence:coverage-gaps.py` | 📊 Whole-repo coverage (80% default threshold) |
| `overconfidence:missing-annotations.py` | 🔍 mypy strict — types must check out |
| `overconfidence:type-blindness.js` | 🏗️ TypeScript type checking (tsc) |
| `overconfidence:type-blindness.py` | 🔬 pyright strict — second opinion on types |
| `overconfidence:untested-code.js` | 🧪 Jest test execution |
| `overconfidence:untested-code.py` | 🧪 Runs pytest — code must actually pass its tests |

### 🟡 Deceptiveness

> *"These tests are in the way of closing the ticket - how can I get around them?"*
>
> The LLM writes tests that assert nothing, mock everything, or cover the happy path and call it done. Coverage numbers look great. The code is still broken.

| Gate | What It Does |
|------|--------------|
| `deceptiveness:bogus-tests.js` | 🎭 Bogus test detection for JS/TS |
| `deceptiveness:bogus-tests.py` | 🧟 AST analysis for tests that assert nothing |
| `deceptiveness:debugger-artifacts` | 🐞 Catches leftover breakpoint()/debugger;/dbg!()/runtime.Breakpoint() across Python, JS, Rust, Go, C |
| `deceptiveness:gate-dodging` | 🎭 Detects loosened quality thresholds |
| `deceptiveness:hand-wavy-tests.js` | 🔍 ESLint expect-expect assertion enforcement |

### 🟠 Laziness

> *"When I ran mypy, it returned errors unrelated to my code changes..."*
>
> The LLM solves the immediate problem and moves on. Formatting is inconsistent, dead code accumulates, complexity creeps upward, and nobody notices until the codebase is incomprehensible.

| Gate | What It Does |
|------|--------------|
| `laziness:broken-templates.py` | 📄 Jinja2 template validation |
| `laziness:complexity-creep.py` | 🌀 Cyclomatic complexity (max rank C) |
| `laziness:dead-code.py` | 💀 Dead code detection via vulture (≥80% confidence) |
| `laziness:silenced-gates` | 🔇 Detects disabled gates when language tooling exists |
| `laziness:sloppy-formatting.js` | 🎨 ESLint + Prettier (supports auto-fix 🔧) |
| `laziness:sloppy-formatting.py` | 🎨 autoflake, black, isort, flake8 (supports auto-fix 🔧) |
| `laziness:sloppy-frontend.js` | ⚡ Quick ESLint frontend check |

### 🔵 Myopia

> *"This file is fine in isolation — I don't need to see what it duplicates three directories away"*
>
> The LLM has a 200k-token context window and still manages tunnel vision. It duplicates code across files, ignores security implications, and lets functions grow unbounded because it can't see the pattern.

| Gate | What It Does |
|------|--------------|
| `myopia:code-sprawl` | 📏 File and function length limits |
| `myopia:dependency-risk.py` | 🔒 Full security audit (code + pip-audit) |
| `myopia:ignored-feedback` | 💬 Checks for unresolved PR review threads |
| `myopia:just-this-once.py` | 📈 Coverage on changed lines only (diff-cover) |
| `myopia:source-duplication` | 📋 Code clone detection (jscpd) |
| `myopia:string-duplication.py` | 🔤 Duplicate string literal detection |
| `myopia:vulnerability-blindness.py` | 🔐 bandit + semgrep + detect-secrets |

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

### Time Budget

Use `--swabbing-time` to set a time budget in seconds. Gates with historical
runtime data are sorted fastest-first and skipped once the accumulated
estimate would exceed the budget. Gates without timing history always run
(to establish a baseline). Once a gate starts running, it runs to completion.

```bash
sm swab --swabbing-time 30    # only run gates that fit in ~30 seconds
```

`sm init` sets a default of 20 seconds. Change it any time:

```bash
sm config --swabbing-time 45  # raise the budget
sm config --swabbing-time 0   # disable the limit entirely
```

Time budgets only apply to swab. Scour runs always execute every gate.

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
      "coverage-gaps.py": { "enabled": true, "threshold": 80 },
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

Custom gates run alongside built-in gates and respect the same enable/disable, timeout, and time-budget mechanics. Exit code 0 means pass, anything else is a failure. `sm init` auto-scaffolds appropriate custom gates when it detects Go, Rust, or C/C++ projects.

### Why Wrapper Gates?

Some built-in gates wrap well-known tools — `coverage-gaps.py` runs `pytest --cov`, `sloppy-formatting.py` runs `black --check`. Why not just run those tools directly?

**They establish a floor.** Without them, an AI agent can commit code with no tests, no type checking, and no formatting — and the "interesting" gates like complexity analysis have nothing to anchor to. The wrappers ensure the absolute minimum is in place for sane development.

**They provide behavioral conditioning.** When an LLM sees slop-mop consistently enforce formatting and test coverage across runs, it starts pre-emptively formatting and testing. The wrappers aren't just gates — they're training signal that encourages models to be good citizens.

**They unify the interface.** `sm swab` gives you formatting + type-checking + test coverage + complexity analysis + dead code + duplicate detection + vulnerability scanning in one command, with zero per-tool configuration. The wrapper gates make that possible.

---

## CI Integration

### GitHub Actions

```yaml
name: slop-mop
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  quality-gates:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install slopmop[all]
      - run: sm swab
      - if: github.event_name == 'pull_request'
        env:
          GH_TOKEN: ${{ github.token }}
        run: sm scour
```

### Check CI Status Locally

```bash
sm ci               # current PR
sm ci 42             # specific PR
sm ci --watch        # poll until CI completes
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
