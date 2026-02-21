# � Slop-Mop

<a href="https://github.com/ScienceIsNeato/slop-mop/actions/workflows/slopmop.yml"><img src="https://github.com/ScienceIsNeato/slop-mop/actions/workflows/slopmop.yml/badge.svg" alt="Slop-Mop CI"/></a> <a href="https://github.com/ScienceIsNeato/slop-mop/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Attribution-blue.svg" alt="License: Attribution"/></a> <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="Python 3.9+"/></a>

**Quality gates for AI-assisted codebases.** Not a silver bullet — just a mop.

<img src="assets/heraldic_splash.png" alt="Slop-Mop" width="300" align="right"/>

LLMs optimize for task completion, not codebase health. Left unchecked, they cargo-cult patterns, duplicate code they can't see, and accumulate technical debt in predictable, repeatable ways. Slop-Mop is a set of quality gates you bolt onto a project to catch that stuff automatically — duplication, coverage gaps, complexity creep, security blind spots, bogus tests — so you can focus on the decisions only a human can make.

**Phase 1: Remediation.** Bolt it on, run it, fix what it finds.
**Phase 2: Maintenance.** Keep the gates passing on every commit.

---

## Quick Start

```bash
# Install once per machine
pipx install slopmop        # recommended — isolated, no dep conflicts
# or: pip install slopmop

# Per-project setup (run in your repo root)
sm init                     # auto-detects project type, writes .sb_config.json
sm validate commit          # run quality gates
```

Auto-detects your project type and enables relevant gates. See [`sm init`](#setup-sm-init) for details and [`sm config`](#configuration-sm-config) for customization.

---

## How It Works

Run a profile, fix what fails, repeat:

```bash
sm validate commit
```

When a gate fails, the output tells you exactly what to do next:

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
│ 2. Validate: sm validate python-coverage --verbose       │
│ 3. Resume:   sm validate commit                          │
│                                                          │
│ Keep iterating until all the slop is mopped.             │
└──────────────────────────────────────────────────────────┘
```

Iterate until all gates pass, then commit. Use `sm status` for a full report card.

---

## Available Gates

### Python

| Gate                     | Description                                             |
| ------------------------ | ------------------------------------------------------- |
| `python:lint-format`     | 🎨 Code formatting (black, isort, flake8)               |
| `python:static-analysis` | 🔍 Type checking with strict typing (mypy)              |
| `python:tests`           | 🧪 Test execution (pytest)                              |
| `python:coverage`        | 📊 Whole repo coverage analysis (80% threshold default) |
| `python:diff-coverage`   | 📊 Coverage on changed lines only (diff-cover)          |

### JavaScript

| Gate                     | Description                              |
| ------------------------ | ---------------------------------------- |
| `javascript:lint-format` | 🎨 Linting/formatting (ESLint, Prettier) |
| `javascript:tests`       | 🧪 Test execution (Jest)                 |
| `javascript:coverage`    | 📊 Coverage analysis                     |
| `javascript:types`       | 📝 TypeScript type checking (tsc)        |

### Quality

| Gate                         | Description                            |
| ---------------------------- | -------------------------------------- |
| `quality:complexity`         | 🌀 Cyclomatic complexity (radon)       |
| `quality:dead-code`          | 💀 Dead code detection (vulture)       |
| `quality:loc-lock`           | 📏 File and function length limits     |
| `quality:source-duplication` | 📋 Code duplication detection (jscpd)  |
| `quality:string-duplication` | 🔤 Duplicate string literal detection  |
| `quality:bogus-tests`        | 🧟 Bogus test detection (AST analysis) |
| `general:templates`          | 📄 Template syntax validation          |

### Security

| Gate             | Description                                                              |
| ---------------- | ------------------------------------------------------------------------ |
| `security:local` | 🔐 Code security scan (bandit + semgrep + detect-secrets)                |
| `security:full`  | 🔒 Security audit (code scan + dependency vulnerabilities via pip-audit) |

### Profiles

| Profile  | Description           | Gates Included                                                                                                                                |
| -------- | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `commit` | Commit validation     | lint, static-analysis, tests, coverage, complexity, dead-code, loc-lock, duplication (source + string), bogus-tests, security-local, JS gates |
| `pr`     | Full PR validation    | All commit gates + PR comments, diff-coverage, security-full                                                                                  |
| `quick`  | Ultra-fast lint check | lint, security-local                                                                                                                          |

JS gates auto-skip when no JavaScript is detected.

---

## Setup: `sm init`

```bash
sm init                    # Interactive setup
sm init --non-interactive  # Auto-detect, use defaults
```

Scans your repo, detects languages and test frameworks, writes `.sb_config.json`. Re-run to start fresh (backs up existing config first).

Start with what passes, disable the rest, ramp up over time:

```bash
sm config --disable python:coverage   # Not ready yet
sm validate commit                    # Get everything else green first
sm config --enable python:coverage    # Enable later
```

---

## Configuration: `sm config`

```bash
sm config --show              # Show all gates and their status
sm config --enable <gate>     # Enable a disabled gate
sm config --disable <gate>    # Disable a gate
sm config --json <file>       # Update config from a JSON file
```

### Include / Exclude Directories

```bash
sm config --exclude-dir quality:generated    # Skip generated code
sm config --include-dir python:src           # Only check src/
```

- `include_dirs`: whitelist — only these dirs are scanned
- `exclude_dirs`: blacklist — always skipped, takes precedence

Edit `.sb_config.json` directly for per-gate configuration:

```json
{
  "version": "1.0",
  "default_profile": "commit",
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

## Git Hooks: `sm commit-hooks`

```bash
sm commit-hooks install commit    # Install pre-commit hook
sm commit-hooks status            # Show installed hooks
sm commit-hooks uninstall         # Remove slop-mop hooks
```

Once installed, gates run automatically before every `git commit`. Failed gates block the commit.

---

## CI Integration: `sm ci`

Example GitHub Actions workflow:

```yaml
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
          python-version: '3.11'
      - run: pip install slopmop
      - run: sm validate commit
      - if: github.event_name == 'pull_request'
        env:
          GH_TOKEN: ${{ github.token }}
        run: sm validate pr:comments
```

Check CI status locally:

```bash
sm ci               # Current PR
sm ci 42             # Specific PR
sm ci --watch        # Poll until CI completes
```

The `pr:comments` gate checks for unresolved PR review threads. Use `sm validate pr` locally to see what's outstanding, fix or resolve each thread, then re-run until clear.

---

## Architecture

Slop-mop installs as a normal package (`pipx install slopmop` or `pip install slopmop`) and is configured per-project via `.sb_config.json`. The `sm` command is on your PATH once and works in any repo.

**Tool resolution order**: When sm runs a check, it looks for the required tool in this order:
1. `<project_root>/venv/bin/<tool>` or `.venv/bin/<tool>` — project-local venv (highest priority)
2. `$VIRTUAL_ENV/bin/<tool>` — currently activated venv
3. System PATH — where sm's own bundled tools live when installed via pipx

This means if your project has its own `pytest` (with project-specific plugins like `pytest-django`), sm will use it. If it doesn't, sm falls back to its own.

**Version pinning**: If you need strict version pinning, the git submodule approach still works. Add `slop-mop` as a submodule and invoke `python -m slopmop.sm` from it directly. The submodule model is supported but no longer recommended for most projects.

## Development

```bash
# Working on slop-mop itself
pip install -e .
sm validate --self
pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for adding new gates.

---

## Further Reading

📖 [A Hand for Daenerys: Why Tyrion Is Missing from Your Vibe-Coding Council](https://scienceisneato.substack.com/p/a-hand-for-daenerys-why-tyrion-is)

---

## License

[Slop-Mop Attribution License v1.0](LICENSE) — free to use, modify, and redistribute with attribution.

P.S. Other than this line in the readme and a few scattered lines here and there, nothing in this project was written by a human. It is, for better or worse, the result of living under the slop-mop regime.
