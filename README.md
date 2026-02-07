# 🧹 Slop-Mop

<a href="https://github.com/ScienceIsNeato/slop-mop/actions/workflows/slopmop.yml"><img src="https://github.com/ScienceIsNeato/slop-mop/actions/workflows/slopmop.yml/badge.svg" alt="Slop-Mop CI"/></a> <a href="https://github.com/ScienceIsNeato/slop-mop/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"/></a> <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="Python 3.9+"/></a>

**Quality gates for AI-assisted codebases.** Not a silver bullet — just a mop.

<img src="assets/heraldic_splash.png" alt="Slop-Mop" width="300" align="right"/>

## The Problem (Which Nobody Has Solved)

LLMs are reward hackers. They optimize for task completion — not codebase health. Left unsupervised, they cargo-cult patterns, duplicate code they can't see, and put blinders on for momentum. The result is technical debt that accumulates faster than any human team could produce.

You can't prompt-engineer this away. The tension between _shipping_ and _maintaining_ is genuinely unsolved. Humans struggle with it too. But LLMs struggle in predictable, repeatable ways, which at least makes some of it automatable.

### Who This Is For

Slop-Mop was built for dev teams of one — a single human partnered with AI coding agents. On a traditional team, you have code review, pair programming, and institutional knowledge spread across people. When it's just you and your LLMs, you don't have any of that. You're the only mind reviewing tens of thousands of lines of generated code, and there aren't enough hours in the day to catch everything your AI partners are producing.

You need something that watches the codebase _for_ you. Not perfectly — but well enough to catch the predictable stuff so you can focus on the decisions only a human can make.

## So What Is This?

Slop-Mop is a set of quality gates you bolt onto a project. It works in two phases:

**Phase 1: Remediation.** Bolt it onto an existing repo, run it, and fix what it finds. Duplication, missing tests, complexity rot, security holes, format drift — the accumulated debt that piles up when agents operate unchecked.

**Phase 2: Maintenance.** Once the gates pass, keep them passing. This is the harder part. Every commit, every PR, every agent session runs through the same gates. Debt doesn't accumulate (as much) because it gets caught before it lands.

### The Key Insight

When you tell an LLM exactly what to do, it typically does it well. When you don't, it decides for itself — and after years of watching what happens when it decides for itself, the answer is usually unnecessary churn.

Slop-Mop's output has been refined to give agents exact instructions in specific failure scenarios. Instead of vague "fix the code quality" guidance, it tells the model precisely what command to run, what threshold was violated, and what to do next. The thinking is that agents left to interpret quality problems on their own tend to go sideways — rewriting things that didn't need rewriting, or "fixing" one issue by creating two more.

### What It Catches

- **Duplication** — LLMs reinvent what they can't see. Duplication detection surfaces it. There's also a string-level variant (`quality:string-duplication`) that finds repeated string literals across files and pushes them into a shared constants module. A side effect of this: when source and test code reference the same constant instead of independently hardcoding the same string, changing the value in one place updates both. Tests stay in sync with the code they exercise, which makes them less brittle over time.
- **Coverage gaps** — Tests that don't exercise the code, or code with no tests at all.
- **Complexity creep** — Functions that grow without pushback.
- **Security blind spots** — `bandit` and `semgrep` catch insecure code patterns (SQL injection, hardcoded credentials, unsafe deserialization). `detect-secrets` uses entropy analysis and pattern matching to find API keys, passwords, and PII that would be embarrassing or dangerous to commit. Agents don't think twice about dropping a connection string inline.
- **Format entropy** — Consistency erosion across agent sessions.
- **Bogus tests** — Tests that exist structurally but don't test anything: empty bodies, `assert True`, functions with no assertions. Agents under coverage pressure will create these to satisfy the gate without doing the work. AST analysis catches them.

---

## Quick Start

```bash
# Clone slop-mop into your project
git submodule add https://github.com/ScienceIsNeato/slop-mop.git

# Install and run interactive setup
cd slop-mop && pip install -e . && sm init

# See current state and recommendations
sm status

# Validate your code
sm validate commit       # Fast commit validation
sm validate pr           # Full PR validation
```

Auto-detects your project type and enables relevant gates. See [`sm init`](#setup-sm-init) for setup details, [`sm commit-hooks`](#git-hooks-sm-commit-hooks) to enforce gates on every commit, and [`sm config`](#configuration-sm-config) for customization.

---

## How It Works (For AI Agents)

The intended workflow is simple and iterative. Run a profile, fix what fails, repeat.

```bash
sm validate commit
```

When a gate fails, the output tells you what to do next:

```
┌──────────────────────────────────────────────────────────┐
│ 🤖 AI AGENT ITERATION GUIDANCE                           │
├──────────────────────────────────────────────────────────┤
│ Profile: commit                                          │
│ Failed Gate: python-coverage                             │
├──────────────────────────────────────────────────────────┤
│ NEXT STEPS:                                              │
│                                                          │
│ 1. Fix the issue described above                         │
│ 2. Validate: sm validate python-coverage                 │
│ 3. Resume:   sm validate commit                          │
│                                                          │
│ Keep iterating until all checks pass.                    │
└──────────────────────────────────────────────────────────┘
```

### Prefer Profiles Over Individual Gates

```bash
# ❌ Verbose and error-prone
sm validate -g python:lint-format,python:static-analysis,python:tests,python:coverage

# ✅ Profiles group gates for common scenarios
sm validate commit
```

### The Loop

1. `sm validate commit` — see what fails
2. Fix the first failure
3. `sm validate <failed-gate>` — verify just that fix
4. Repeat steps 2-3 until `sm validate commit` passes
5. Commit only when all gates are green

**The key discipline:** Don't move on until the gates pass. Each iteration should end with `sm validate commit` returning success. If you're tempted to skip a gate or push broken code "just this once," that's the slop creeping back in.

If you want to see everything at once instead of fail-fast, `sm status` runs the same gates but doesn't stop at the first failure. It prints a report card at the end.

---

## Design Choices

Some opinions baked into the tool:

- **Fail-fast by default.** Stops at the first failing gate rather than running everything. The assumption is that fixing one thing at a time produces fewer regressions than dumping a wall of errors at once.
- **Profiles over flags.** `sm validate commit` is easier to remember (and harder to get wrong) than a list of individual gate names.
- **Auto-detection.** Slop-Mop looks at your project structure and enables relevant gates. You can override this, but the goal is zero-config for common setups.
- **Actionable output.** Error messages include the exact command to re-run the failing gate.
- **Self-dogfooding.** `sm validate --self` runs slop-mop's own gates against itself.

### A Note on Tool Use

If you're an AI agent working in a project that has slop-mop installed, prefer using it over running raw tools:

```bash
# Instead of this:
pytest tests/unit/test_foo.py -v
black --check src/
mypy src/

# Use this:
sm validate commit
```

The reason is consistency. The same gates run the same way every time, regardless of which agent session is running them or how long it's been since the last one.

---

## Available Gates

### Python Gates

| Gate                       | Description                                    |
| -------------------------- | ---------------------------------------------- |
| `python:lint-format`       | 🎨 Code formatting (black, isort, flake8)      |
| `python:static-analysis`   | 🔍 Type checking with strict typing (mypy)     |
| `python:tests`             | 🧪 Test execution (pytest)                     |
| `python:coverage`          | 📊 Coverage analysis (80% threshold)           |
| `python:diff-coverage`     | 📊 Coverage on changed lines only (diff-cover) |
| `python:new-code-coverage` | 📊 Alias for diff-coverage (CI compat)         |

### JavaScript Gates

| Gate                     | Description                              |
| ------------------------ | ---------------------------------------- |
| `javascript:lint-format` | 🎨 Linting/formatting (ESLint, Prettier) |
| `javascript:tests`       | 🧪 Test execution (Jest)                 |
| `javascript:coverage`    | 📊 Coverage analysis                     |
| `javascript:types`       | 📝 TypeScript type checking (tsc)        |

### Quality Gates

| Gate                         | Description                            |
| ---------------------------- | -------------------------------------- |
| `quality:complexity`         | 🌀 Cyclomatic complexity (radon)       |
| `quality:dead-code`          | 💀 Dead code detection (vulture)       |
| `quality:loc-lock`           | 📏 File and function length limits     |
| `quality:source-duplication` | 📋 Code duplication detection (jscpd)  |
| `quality:string-duplication` | 🔤 Duplicate string literal detection  |
| `quality:bogus-tests`        | 🧟 Bogus test detection (AST analysis) |
| `general:templates`          | 📄 Template syntax validation          |

### Security Gates

| Gate             | Description                                                               |
| ---------------- | ------------------------------------------------------------------------- |
| `security:local` | 🔐 Code security scan (bandit + semgrep + detect-secrets)                  |
| `security:full`  | 🔒 Security audit (code scan + dependency vulnerabilities via pip-audit)   |

### Profiles (Gate Groups)

| Profile  | Description           | Gates Included                                                                                                           |
| -------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `commit` | Commit validation     | lint, static-analysis, tests, coverage, complexity, dead-code, loc-lock, duplication (source + string), bogus-tests, security-local, JS gates |
| `pr`     | Full PR validation    | All commit gates + PR comments, diff-coverage, new-code-coverage, security-full                                                               |
| `quick`  | Ultra-fast lint check | lint, security-local                                                                                                                          |

---

## Setup: `sm init`

Run once when you first add slop-mop to a project. It scans your repo, figures out what you've got, and writes a `.sb_config.json`.

```bash
sm init                    # Interactive — walks you through it
sm init --non-interactive  # Auto-detect everything, use defaults
```

**What it detects:** Python vs JavaScript (or both), test directories, pytest/jest presence, recommended gates and profiles.

**Re-running:** `sm init` is destructive by design. If you want to start fresh — say your project structure has changed significantly — re-run it. It backs up your existing config and writes a new one from scratch based on current project state.

**Intended flow:**

1. Run `sm init` to generate a baseline config
2. Review the report card it prints — that's where the repo stands right now
3. Disable gates you're not ready for
4. Run `sm validate commit` and fix what fails
5. Gradually enable more gates and tighten thresholds over time

### The Gradual Ramp (vs. Eating the Whole Pig)

If you bolt slop-mop onto a repo with zero test coverage, turning on the coverage gate at 80% means you're not shipping anything until you write a _lot_ of tests. That might be the right call, but usually it isn't.

The alternative:

```bash
# Start with coverage disabled
sm config --disable python:coverage

# Get everything else passing first
sm validate commit

# Enable coverage at a low threshold
sm config --enable python:coverage
# Edit .sb_config.json: set coverage threshold to 5
sm validate commit

# Ramp up over time: 5% → 30% → 50% → 80%
```

This lets you work on features _while_ building up quality infrastructure incrementally. Each threshold bump is a small, manageable chunk of work instead of a multi-hour remediation session.

---

## Configuration: `sm config`

View and modify gate settings after init.

```bash
sm config --show              # Show all gates and their status
sm config --enable <gate>     # Enable a disabled gate
sm config --disable <gate>    # Disable a gate
sm config --json <file>       # Update config from a JSON file
```

### Include and Exclude Directories

When a gate reports false positives (or misses code you care about), use include/exclude directories to scope what gets checked. This is one of the most powerful tools for fixing large swaths of noise all at once.

```bash
# Exclude generated code from quality checks
sm config --exclude-dir quality:generated

# Exclude vendor/third-party code from python checks  
sm config --exclude-dir python:vendor
sm config --exclude-dir python:third_party

# Exclude test files from security scanning (test secrets are intentional)
sm config --exclude-dir security:tests
sm config --exclude-dir security:fixtures

# Focus python checks on specific directories only
sm config --include-dir python:src
sm config --include-dir python:lib
```

**Format:** `--include-dir CATEGORY:DIR` or `--exclude-dir CATEGORY:DIR`

**Valid categories:** `python`, `javascript`, `security`, `quality`, `general`, `integration`

**How it works:**
- `include_dirs`: If set, ONLY these directories are scanned (whitelist)
- `exclude_dirs`: These directories are always skipped (blacklist)
- Excludes take precedence over includes

**Common patterns:**

| Problem | Solution |
|---------|----------|
| Dead code check flags test mocks | `sm config --exclude-dir python:tests` |
| Security scanner finds test credentials | `sm config --exclude-dir security:fixtures` |
| Duplication check flags generated code | `sm config --exclude-dir quality:generated` |
| Want to check only `src/` for now | `sm config --include-dir python:src` |

The changes are written to `.sb_config.json`. You can also edit that file directly for more complex configurations like per-gate excludes:

```json
{
  "quality": {
    "exclude_dirs": ["generated", "vendor"],
    "gates": {
      "duplication": {
        "exclude_dirs": ["templates"]
      }
    }
  }
}
```

The config file (`.sb_config.json`) supports per-gate customization:

```json
{
  "version": "1.0",
  "default_profile": "commit",
  "python": {
    "enabled": true,
    "gates": {
      "coverage": { "threshold": 80 },
      "tests": { "test_dirs": ["tests"] }
    }
  },
  "quality": {
    "gates": {
      "duplication": {
        "threshold": 5,
        "exclude_dirs": ["generated", "vendor"]
      }
    }
  }
}
```

---

## Git Hooks: `sm commit-hooks`

Installing a git hook makes the gates automatic — they run before every commit without anyone having to remember.

```bash
sm commit-hooks install commit    # Install pre-commit hook with 'commit' profile
sm commit-hooks status            # Show installed hooks
sm commit-hooks uninstall         # Remove slop-mop hooks
```

Once installed, `sm validate commit` runs automatically before every `git commit`. If any gate fails, the commit is blocked. The agent has to fix the issue before it can land code.

The thinking behind this: once you've cleaned up the existing debt (Phase 1) and installed the hook, you've moved the quality enforcement out of your head and into the machine. The agent will still fail gates — it'll try things that don't pass, iterate, try again. But the loop is mechanical now. You're not the one who has to remember to check for duplication or coverage or formatting. The hook does that.

The hook uses your project's venv for deterministic execution (falls back to system `sm` if no venv is found). You can install it with any profile — `commit` for the standard set, `quick` for fast lint-only, or a custom profile if you've defined one.

---

## CI Integration: `sm ci`

Hooks enforce gates locally. CI enforces them in the cloud. They complement each other.

Slop-mop ships a GitHub Actions workflow that dogfoods itself. Use it as a template for your own project:

```yaml
# .github/workflows/slopmop.yml
name: slop-mop

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - run: pip install -e ".[dev]"

      - name: Run slop-mop
        run: sm validate commit

      - name: Check PR comments (PRs only)
        if: github.event_name == 'pull_request'
        env:
          GH_TOKEN: ${{ github.token }}
        run: sm validate pr:comments
```

**Checking CI status locally:**

```bash
sm ci               # Check CI status for current PR
sm ci 42            # Check CI status for PR #42
sm ci --watch       # Poll until CI completes (runs unattended)
```

Watch mode polls every 30 seconds and reports results automatically when CI finishes — no tab-switching or manual refreshing.

**Why both?** Hooks catch problems before code is pushed. CI catches things hooks can't — platform-specific failures, PR-level checks like comment resolution, and the case where someone bypasses the hook entirely.

---

## Status and Reports: `sm status`

The `status` command runs all gates without fail-fast and produces a full report card:

```bash
sm status          # Run pr profile (default)
sm status commit   # Run commit profile
```

### What Status Shows

- **Gate Inventory** — Every registered gate, grouped by category, with pass/fail/n/a status
- **Remediation** — Specific guidance for each failing gate, including fix suggestions
- **Verdict** — Bottom-line summary: how many passed, how many failed, total runtime
- **Recommendations** — Applicable gates not yet in your profile, with exact `sm config` commands to enable them

The recommendations section helps you incrementally adopt stricter quality gates. Instead of enabling everything at once (and drowning in failures), add one gate at a time, fix what it finds, then add the next.

### Generating Full Machine-Readable Reports

For AI agents or external tooling, use `--verbose` to write a JSON report:

```bash
sm status --verbose
```

This writes a timestamped file (`sm_status_<timestamp>.json`) containing:

- Summary statistics (passed/failed/skipped/not-applicable counts)
- Per-gate details: status, duration, output, errors, fix suggestions
- Applicability info for gates not in the current profile

Use this for:

- Feeding detailed context to AI agents analyzing codebase health
- Integration with external dashboards or tracking tools
- Historical comparison of quality metrics over time

---

## Commit vs. PR Profiles

Slop-mop distinguishes between two levels of validation because they serve different purposes.

### `sm validate commit` — Keep Each Commit Clean

The commit profile runs the gates that matter for individual chunks of work:

- Lint and formatting (Python + JavaScript)
- Static analysis (mypy)
- Tests and coverage (Python + JavaScript)
- Complexity analysis
- Source and string duplication detection
- Bogus test detection
- Fast security scan (bandit, semgrep, detect-secrets)

JavaScript gates auto-skip when no JS is detected, so the profile works for Python-only, JS-only, and mixed projects alike.

This is the profile intended for every commit. The idea is to catch things like bad formatting, missing tests, duplicated code, and complexity spikes while the agent is still working on the change — when the context is fresh and the fix is small.

### `sm validate pr` — Ensure the PR as a Whole Is Ready

The PR profile runs everything in the commit profile _plus_ checks that only make sense at the PR level:

- **`pr:comments`** — Are all PR review comments addressed? This gate checks GitHub for unresolved review threads and blocks until they're handled.
- **`python:diff-coverage`** / **`python:new-code-coverage`** — Does the code you changed in this PR specifically have test coverage? `python:coverage` measures the whole project; this measures only the lines the PR touches, using `diff-cover` against the target branch.
- **`security:full`** — The security audit replaces `security:local` at PR level, adding dependency vulnerability checking via `pip-audit` (requires network access).

Commit-level gates catch problems while the agent is still working and the context is fresh. PR-level gates check whether the deliverable as a whole is ready to merge — CI is green, reviewers are satisfied, and the new code specifically (not just the project overall) is tested.

---

## Usage

```bash
# Validation with profiles (preferred)
sm validate commit                    # Fast commit validation
sm validate pr                        # Full PR validation
sm validate quick                     # Ultra-fast lint only

# Validation with specific gates
sm validate python:coverage           # Single gate validation
sm validate --self                    # Validate slop-mop itself

# Setup and configuration
sm init                               # Interactive project setup
sm init --non-interactive             # Auto-configure with defaults
sm config --show                      # Show current configuration

# Git hooks
sm commit-hooks install commit        # Install pre-commit hook
sm commit-hooks status                # Show installed hooks
sm commit-hooks uninstall             # Remove slop-mop hooks

# CI status
sm ci                                 # Check CI for current PR
sm ci 42                              # Check CI for PR #42
sm ci --watch                         # Poll until CI completes

# Full report card
sm status                             # Run all commit gates, show report
sm status pr                          # Report card for PR profile

# Help
sm help                               # List all quality gates
sm help commit                        # Show what's in a profile
sm help python:coverage               # Detailed gate documentation
```

---

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Self-validation (slop-mop validates itself!)
sm validate --self
```

### Adding New Gates

See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete guide to adding new quality gates.

---

## Further Reading

Background on the thinking behind this project:

📖 [A Hand for Daenerys: Why Tyrion Is Missing from Your Vibe-Coding Council](https://scienceisneato.substack.com/p/a-hand-for-daenerys-why-tyrion-is)

---

## License

MIT
