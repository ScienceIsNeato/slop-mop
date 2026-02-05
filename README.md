# 🧹 Slop-Mop

<a href="https://github.com/ScienceIsNeato/slop-mop/actions/workflows/slopmop.yml"><img src="https://github.com/ScienceIsNeato/slop-mop/actions/workflows/slopmop.yml/badge.svg" alt="Slop-Mop CI"/></a> <a href="https://github.com/ScienceIsNeato/slop-mop/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"/></a> <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="Python 3.9+"/></a>

**Quality gates for AI-assisted codebases.** Not a silver bullet — just a mop.

<img src="assets/heraldic_splash.png" alt="Slop-Mop" width="300" align="right"/>

## The Problem (Which Nobody Has Solved)

LLMs are reward hackers. They optimize for task completion — not codebase health. Left unsupervised, they cargo-cult patterns, duplicate code they can't see, and put blinders on for momentum. The result is technical debt that accumulates faster than any human team could produce.

You can't prompt-engineer this away. The tension between *shipping* and *maintaining* is genuinely unsolved. Humans struggle with it too. But LLMs struggle in predictable, repeatable ways — and that's an opening.

## So What Is This?

Slop-Mop is a set of quality gates you bolt onto a project. It works in two phases:

**Phase 1: Remediation.** Bolt it onto an existing repo, run it, and fix what it finds. Duplication, missing tests, complexity rot, security holes, format drift — the accumulated debt that piles up when agents operate unchecked. This alone can bring a neglected codebase back to maintainable.

**Phase 2: Maintenance.** Once the gates pass, keep them passing. This is the harder part. Every commit, every PR, every agent session runs through the same gates. Debt doesn't accumulate (as much) because it gets caught before it lands.

### The Key Insight

When you tell an LLM exactly what to do, it typically does it well. When you don't, it decides for itself — and after years of watching what happens when it decides for itself, the answer is usually unnecessary churn.

Slop-Mop's output has been refined to give agents exact instructions in specific failure scenarios. Instead of vague "fix the code quality" guidance, it tells the model precisely what command to run, what threshold was violated, and what to do next. This keeps agents hyper-focused on the mechanical quality work, freeing up their actual power for the things that matter: architectural decisions and feature integration.

### What It Catches

- **Duplication** — LLMs reinvent what they can't see. Duplication detection surfaces it.
- **Coverage gaps** — Tests that don't exercise the code, or code with no tests at all.
- **Complexity creep** — Functions that grow without pushback.
- **Security blind spots** — Patterns a human reviewer would flag.
- **Format entropy** — Consistency erosion across agent sessions.

---

## Quick Start

```bash
# Clone slop-mop into your project
git submodule add https://github.com/ScienceIsNeato/slop-mop.git

# Install and run interactive setup
cd slop-mop && pip install -e . && sm init

# Validate your code
sm validate commit       # Fast commit validation
sm validate pr           # Full PR validation
```

Auto-detects your project type and enables relevant gates. See [`sm init`](#setup-sm-init) and [`sm config`](#configuration-sm-config) for details on customization.

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
4. `sm validate commit` — check for remaining issues
5. Repeat until clean

---

## Design Choices

Some opinions baked into the tool, for better or worse:

- **Fail-fast by default.** Stops at the first failing gate rather than running everything. The theory is that fixing one thing at a time produces better results than dumping a wall of errors.
- **Profiles over flags.** `sm validate commit` is easier to remember (and harder to get wrong) than a list of individual gate names.
- **Auto-detection.** Slop-Mop looks at your project structure and enables relevant gates. You can override this, but the goal is zero-config for common setups.
- **Actionable output.** Error messages include the exact command to re-run the failing gate. This matters more for AI agents than humans, but it doesn't hurt either way.
- **Self-dogfooding.** `sm validate --self` runs slop-mop's own gates against itself. If we can't pass our own checks, something's wrong.

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

Not because slop-mop is magic, but because it standardizes the workflow. The same gates run the same way every time, which means less drift between sessions.

---

## Available Gates

### Python Gates

| Gate                       | Description                               |
| -------------------------- | ----------------------------------------- |
| `python:lint-format`       | 🎨 Code formatting (black, isort, flake8) |
| `python:static-analysis`   | 🔍 Type checking (mypy)                   |
| `python:tests`             | 🧪 Test execution (pytest)                |
| `python:coverage`          | 📊 Coverage analysis (80% threshold)      |
| `python:diff-coverage`     | 📊 Coverage on changed files only         |
| `python:new-code-coverage` | 📊 Coverage for new code in PR            |

### JavaScript Gates

| Gate                    | Description                              |
| ----------------------- | ---------------------------------------- |
| `javascript:lint-format`| 🎨 Linting/formatting (ESLint, Prettier) |
| `javascript:tests`      | 🧪 Test execution (Jest)                 |
| `javascript:coverage`   | 📊 Coverage analysis                     |
| `javascript:types`      | 📝 TypeScript type checking (tsc)        |

### Quality Gates

| Gate                       | Description                           |
| -------------------------- | ------------------------------------- |
| `quality:complexity`       | 🌀 Cyclomatic complexity (radon)      |
| `quality:source-duplication`| 📋 Code duplication detection (jscpd)|
| `general:templates`        | 📄 Template syntax validation         |

### Security Gates

| Gate              | Description                                    |
| ----------------- | ---------------------------------------------- |
| `security:local`  | 🔐 Fast local scan (bandit + semgrep + secrets)|
| `security:full`   | 🔒 Comprehensive security analysis             |

### Profiles (Gate Groups)

| Profile      | Description            | Gates Included                                                     |
| ------------ | ---------------------- | ------------------------------------------------------------------ |
| `commit`     | Fast commit validation | lint, static-analysis, tests, coverage, complexity, security-local |
| `pr`         | Full PR validation     | All gates + PR comment check                                       |
| `quick`      | Ultra-fast lint check  | lint, security-local                                               |

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
2. Review the config, disable gates you're not ready for
3. Run `sm validate commit` and fix what fails
4. Gradually enable more gates and tighten thresholds over time

### The Gradual Ramp (vs. Eating the Whole Pig)

If you bolt slop-mop onto a repo with zero test coverage, turning on the coverage gate at 80% means you're not shipping anything until you write a *lot* of tests. That might be the right call, but usually it isn't.

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

This lets you work on features *while* building up quality infrastructure incrementally. Each threshold bump is a small, manageable chunk of work instead of a multi-hour remediation session.

---

## Configuration: `sm config`

View and modify gate settings after init.

```bash
sm config --show              # Show all gates and their status
sm config --enable <gate>     # Enable a disabled gate
sm config --disable <gate>    # Disable a gate
sm config --json <file>       # Update config from a JSON file
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

---

## Further Reading

For more on the thinking behind this project — why AI-assisted coding needs structural guardrails and not just better prompts:

📖 [A Hand for Daenerys: Why Tyrion Is Missing from Your Vibe-Coding Council](https://scienceisneato.substack.com/p/a-hand-for-daenerys-why-tyrion-is)

---

## License

MIT
