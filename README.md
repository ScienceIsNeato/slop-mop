# 🪣 Slop-Mop

<p>
  <a href="https://pypi.org/project/slopmop/"><img src="https://img.shields.io/pypi/v/slopmop.svg" alt="PyPI version"/></a>
  <a href="https://github.com/ScienceIsNeato/slop-mop/actions/workflows/slopmop.yml"><img src="https://github.com/ScienceIsNeato/slop-mop/actions/workflows/slopmop.yml/badge.svg" alt="CI"/></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+"/></a>
  <a href="https://github.com/ScienceIsNeato/slop-mop/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Attribution-blue.svg" alt="License"/></a>
</p>

**Quality gates for AI-assisted codebases.** Not a silver bullet — just a mop.

<img src="https://raw.githubusercontent.com/ScienceIsNeato/slop-mop/main/assets/heraldic_splash.png" alt="Slop-Mop" width="300" align="right"/>

AI agents are great at winning battles and terrible at maintaining the ship. They close tickets, ship features, pass tests — and leave behind duplicated code, untested paths, creeping complexity, and security gaps. Nobody *intends* to create this mess. It's a natural byproduct of accomplishing tasks, and without something to catch it, it accumulates until the codebase becomes unnavigable.

The useful thing is that every AI agent makes the same kinds of mistakes. They're **overconfident** (code compiles, must be correct), **deceptive** (tests pass, must be tested), **lazy** (it works, no need to clean up), and **myopic** (this file is fine, never mind what it duplicates). These failure modes are predictable, which means they're automatable.

Slop-mop runs a set of quality gates organized around these four failure modes. Each gate targets a specific pattern — bogus tests, dead code, duplicated strings, complexity creep, missing coverage — and when one fails, it tells the agent exactly what's wrong and how to fix it. Two levels:

- **Swab** (`sm swab`) — routine maintenance, every commit. Quick checks that keep things from getting worse.
- **Scour** (`sm scour`) — deep inspection before opening a PR. Catches what routine swabbing misses.

The mop finds the slop. You (or your agent) clean it up. The ship stays seaworthy.

---

## Quick Start

```bash
# Install (once per machine)
pipx install slopmop          # recommended — isolated, no dep conflicts
# or: pip install slopmop

# Set up your project
sm init                       # auto-detects languages, writes .sb_config.json

# Run quality gates
sm swab                       # fix what it finds, commit when green
sm scour                      # thorough check before opening a PR
```

`sm init` auto-detects Python, JavaScript, or both and writes a `.sb_config.json` with applicable gates enabled.

---

## The Loop

Development with slop-mop follows a single repeated cycle:

```
sm swab → see what fails → fix it → repeat → commit
```

When a gate fails, the output tells you exactly what to do next:

```
┌──────────────────────────────────────────────────────────┐
│ 🤖 AI AGENT ITERATION GUIDANCE                           │
├──────────────────────────────────────────────────────────┤
│ Level: swab                                              │
│ Failed Gate: deceptiveness:py-coverage                   │
├──────────────────────────────────────────────────────────┤
│ NEXT STEPS:                                              │
│                                                          │
│ 1. Fix the issue described above                         │
│ 2. Re-check: sm swab -g deceptiveness:py-coverage        │
│ 3. Resume:   sm swab                                     │
│                                                          │
│ Keep iterating until all the slop is mopped.             │
└──────────────────────────────────────────────────────────┘
```

This is purpose-built for AI agents. The guidance is machine-readable, the iteration is mechanical, and the agent never has to wonder what to do next. It saves tokens (no flailing), saves CI dollars (catch it locally), and keeps the codebase habitable long-term.

Use `sm status` for a report card of all gates at once.

---

## Why These Categories?

Gates aren't organized by language — they're organized by **the failure mode they catch**. These are the four ways LLMs reliably degrade a codebase:

### 🔴 Overconfidence

> *"It compiles, therefore it's correct."*

The LLM generates code that looks right, passes a syntax check, and silently breaks at runtime. These gates verify that the code actually works.

| Gate | What It Does |
|------|--------------|
| `overconfidence:py-tests` | 🧪 Runs pytest — code must actually pass its tests |
| `overconfidence:py-static-analysis` | 🔍 mypy strict — types must check out |
| `overconfidence:py-types` | 🔬 pyright strict — second opinion on types |
| `overconfidence:js-tests` | 🧪 Jest test execution |
| `overconfidence:js-types` | 🏗️ TypeScript type checking (tsc) |
| `overconfidence:deploy-script-tests` | 🚀 Validates deploy scripts |

### 🟡 Deceptiveness

> *"Tests pass, therefore the code is tested."*

The LLM writes tests that assert nothing, mock everything, or cover the happy path and call it done. Coverage numbers look great. The code is still broken.

| Gate | What It Does |
|------|--------------|
| `deceptiveness:py-coverage` | 📊 Whole-repo coverage (80% default threshold) |
| `deceptiveness:py-diff-coverage` | 📈 Coverage on changed lines only (diff-cover) |
| `deceptiveness:bogus-tests` | 🧟 AST analysis for tests that assert nothing |
| `deceptiveness:js-coverage` | 📊 JavaScript coverage analysis |
| `deceptiveness:js-bogus-tests` | 🎭 Bogus test detection for JS/TS |

### 🟠 Laziness

> *"It works, therefore it's done."*

The LLM solves the immediate problem and moves on. Formatting is inconsistent, dead code accumulates, complexity creeps upward, and nobody notices until the codebase is incomprehensible.

| Gate | What It Does |
|------|--------------|
| `laziness:py-lint` | 🎨 autoflake, black, isort, flake8 (supports auto-fix 🔧) |
| `laziness:js-lint` | 🎨 ESLint + Prettier (supports auto-fix 🔧) |
| `laziness:complexity` | 🌀 Cyclomatic complexity (max rank C) |
| `laziness:dead-code` | 💀 Dead code detection via vulture (≥80% confidence) |
| `laziness:template-syntax` | 📄 Jinja2 template validation |
| `laziness:js-frontend` | ⚡ Quick ESLint frontend check |

### 🔵 Myopia

> *"My change is fine. Why would I look at the bigger picture?"*

The LLM has a 200k-token context window and still manages tunnel vision. It duplicates code across files, ignores security implications, and lets functions grow unbounded because it can't see the pattern.

| Gate | What It Does |
|------|--------------|
| `myopia:loc-lock` | 📏 File and function length limits |
| `myopia:source-duplication` | 📋 Code clone detection (jscpd) |
| `myopia:string-duplication` | 🔤 Duplicate string literal detection |
| `myopia:security-scan` | 🔐 bandit + semgrep + detect-secrets |
| `myopia:security-audit` | 🔒 Full security audit (code + pip-audit) |

### PR Gates

| Gate | What It Does |
|------|--------------|
| `pr:comments` | 💬 Checks for unresolved PR review threads |

---

## Levels

Every gate has an intrinsic **level** — the point in your workflow where it belongs:

| Level | Command | Gates | When to Use |
|-------|---------|-------|-------------|
| **Swab** | `sm swab` | All overconfidence, deceptiveness, laziness, myopia checks | Before every commit |
| **Scour** | `sm scour` | Everything in swab + PR comments, diff-coverage, full security audit | Before opening or updating a PR |

Scour is a strict superset of swab — it runs everything swab does, plus context-dependent gates that need a PR or deeper analysis.

### Aliases

For convenience, named aliases let you run a subset with `-g`:

| Alias | Gates | Purpose |
|-------|-------|---------|
| `quick` | 2 gates — lint + security scan | Fast feedback during development |
| `python` | 5 gates — Python-specific subset | Language-focused validation |
| `javascript` | 5 gates — JS/TS-specific subset | Language-focused validation |
| `quality` | 5 gates — complexity, duplication, loc-lock | Code quality only |
| `security` | 1 gate — full security audit | Security-focused validation |

JS gates auto-skip when no JavaScript is detected.

### Time Budget (Preview)

Short on time? Use `--swabbing-time` to set a budget in seconds. Gates are
ordered by historical runtime and skipped once the budget would be exceeded:

```bash
sm swab --swabbing-time 30    # only run gates that fit in ~30 seconds
sm scour --swabbing-time 120  # thorough pass, but cap at 2 minutes
```

> **Note:** `--swabbing-time` is a preview feature — the flag is accepted but
> budget enforcement is not yet active. Full implementation is coming in a
> future release.

---

## Getting Started: The Remediation Path

Most projects won't pass all gates on day one. That's expected. Here's the ramp:

### 1. Initialize

```bash
sm init                       # auto-detects everything, writes .sb_config.json
```

### 2. See Where You Stand

```bash
sm swab                       # run swab-level gates, see what fails
sm status                     # full report card
```

### 3. Disable What You're Not Ready For

```bash
sm config --disable laziness:complexity        # too many complex functions right now
sm config --disable deceptiveness:py-coverage  # coverage is at 30%, not 80%
sm swab                                        # get the rest green first
```

### 4. Fix Everything That's Left

Iterate: run `sm swab`, fix a failure, run again. The iteration guidance tells you exactly what to do after each failure.

### 5. Install Hooks

```bash
sm commit-hooks install           # pre-commit hook runs sm swab
sm commit-hooks status            # verify hooks are installed
```

Now every `git commit` runs slop-mop. Failed gates block the commit.

### 6. Re-enable Gates Over Time

```bash
sm config --enable laziness:complexity         # refactored enough, turn it on
sm config --enable deceptiveness:py-coverage   # coverage is at 75%, set threshold to 70
```

### 7. Let Agents Vibe-Code

With hooks in place, agents can write code freely. Slop-mop catches the slop before it reaches the repo. This saves tokens (no back-and-forth debugging), saves CI money (catch it locally), and keeps the codebase survivable long-term.

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

Edit directly for per-gate configuration:

```json
{
  "version": "1.0",
  "python": {
    "gates": {
      "coverage": { "threshold": 80 },
      "tests": { "test_dirs": ["tests"] }
    }
  },
  "quality": {
    "exclude_dirs": ["generated", "vendor"]
  }
}
```

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
      - run: pip install slopmop
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

Slop-mop installs as a normal package and is configured per-project via `.sb_config.json`. The `sm` command is on your PATH once and works in any repo.

**Tool resolution order** — sm uses your project's tools when available:
1. `<project_root>/venv/bin/<tool>` or `.venv/bin/<tool>` — project-local venv (highest priority)
2. `$VIRTUAL_ENV/bin/<tool>` — currently activated venv
3. System PATH — sm's own bundled tools (via pipx)

This means if your project has its own `pytest` (with plugins like `pytest-django`), sm uses it. Otherwise, sm falls back to its own.

**Submodule alternative**: If you need strict version pinning, add `slop-mop` as a git submodule and invoke `python -m slopmop.sm` directly. Supported but not recommended for most projects.

---

## Development

```bash
# Working on slop-mop itself
pip install -e .
sm scour --self               # dogfooding — sm validates its own code
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
