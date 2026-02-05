<p align="center">
  <img src="assets/heraldic_splash.png" alt="Slop-Mop: Give Daenerys a Hand" width="800"/>
</p>

<h1 align="center">🧹 Slop-Mop</h1>

<p align="center">
  <strong>Quality Gates for AI-Generated Code</strong><br/>
  <em>Because when all problems are solved with dragons, you end up with a kingdom of ashes.</em>
</p>

<p align="center">
  <a href="#the-problem">The Problem</a> •
  <a href="#the-solution">The Solution</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#ai-agent-workflow">AI Workflow</a> •
  <a href="#available-gates">Gates</a> •
  <a href="#configuration">Configuration</a>
</p>

---

## The Problem

> *"There's a growing sense among developers that vibe coding is 'cooked.' It works amazingly well... until it doesn't."*

LLMs weren't trained to build sustainable codebases. They were trained to **close tickets**—to satisfy acceptance criteria with minimal consideration for long-term consequences. This makes them exceptional mercenary engineers and dangerous long-term stewards.

For a deeper exploration of this dynamic, see [A Hand for Daenerys: Why Tyrion Is Missing from Your Vibe-Coding Council](https://scienceisneato.substack.com/p/a-hand-for-daenerys-why-tyrion-is).

### What LLMs Do Well
- ✅ Complete individual tasks with impressive speed
- ✅ Produce code that passes tests on the first try
- ✅ Follow established patterns when they see them
- ✅ Generate boilerplate and repetitive code instantly

### What LLMs Do Poorly (Without Intervention)
- ❌ Question whether the work should exist in the first place
- ❌ Maintain architectural integrity across sessions
- ❌ Avoid duplicating code they can't see in context
- ❌ Resist the urge to "fix" things outside scope
- ❌ Consider consequences beyond the immediate task

The training data optimized for "issue opened → code committed → tests pass → issue closed." That's **Daenerys-mode**: decisive, effective, and optimized for velocity. But without a **Tyrion** asking the uncomfortable questions, you accumulate technical debt at an alarming rate.

---

## The Solution

**Slop-Mop is Tyrion in a box.**

It's a bolt-on quality gate framework designed specifically for AI-generated code. While humans might forget to run a linter or skip writing tests when tired, LLMs have different failure modes: they duplicate code, submit unvetted changes, overhype features, and optimize for completion over quality.

Slop-Mop addresses these LLM-specific failure modes by:

### 🎯 Optimizing for How LLMs Actually Work

| LLM Tendency | Slop-Mop Response |
|--------------|-------------------|
| Duplicate code across files | Code duplication detection (jscpd) |
| Submit unvetted changes | Mandatory test and coverage gates |
| Overhype capabilities | Security scanning (bandit, semgrep) |
| Tunnel vision on current task | Complexity analysis, static typing |
| Cargo-cult patterns | Lint enforcement, format consistency |

### 🛤️ Putting Guardrails on Tool Use

LLMs are excellent at following instructions and terrible at knowing when to stop. Slop-Mop provides:

- **Fail-fast execution**: Stop at the first failure, fix it, move on
- **Exact fix instructions**: Tell the LLM precisely what command to run next
- **Profiles, not flags**: `sm validate commit` instead of remembering 12 gate names
- **Iteration guidance**: Clear next steps after every failure

### 🔧 Helping LLMs Help Themselves

When LLMs see well-structured code with tests, they emulate that pattern. Slop-Mop enforces the patterns you want propagated:

- Coverage requirements force tests to exist
- Complexity limits prevent spaghetti code
- Type checking catches errors before runtime
- Security scans block obviously bad patterns

The more the LLM sees good patterns, the more it generates good patterns. Slop-Mop bootstraps that flywheel.

---

## Quick Start

```bash
# Clone slop-mop into your project
git submodule add https://github.com/ScienceIsNeato/slop-mop.git

# Install and run interactive setup
cd slopmop && pip install -e . && sm init

# Validate your code
sm validate commit       # Fast commit validation
sm validate pr           # Full PR validation
```

**That's it.** Zero configuration required. Slop-Mop auto-detects your project type and enables appropriate gates.

---

## AI Agent Workflow

**🤖 This is the primary use case. If you're an AI coding assistant, this section is for you.**

### The Simple Pattern

```bash
sm validate commit
```

When a check fails, Slop-Mop tells you exactly what to do next:

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

### What NOT to Do

```bash
# ❌ DON'T - verbose, error-prone, misses the point
sm validate -g python:lint-format,python:static-analysis,python:tests,python:coverage

# ✅ DO - simple, iterative, self-guiding
sm validate commit
```

### The Iteration Loop

1. **Run the profile**: `sm validate commit`
2. **See what fails**: Output shows exactly which gate failed
3. **Fix the issue**: Follow the guidance in the error output
4. **Validate the fix**: `sm validate <failed-gate>` (just that one gate)
5. **Resume the profile**: `sm validate commit` (catch remaining issues)
6. **Repeat until green**: Keep iterating until all checks pass

This fail-fast, iterative approach is:
- **Faster** than running everything at once
- **Easier** to reason about (one problem at a time)
- **Cleaner** in commit history (incremental fixes)

---

## Primary Tenets

### 1. Easy to Use
- **Bolt-on installation**: Git submodule, one command setup
- **Auto-downloads dependencies**: No manual tool installation
- **Auto-configures on first run**: Detects project type, enables relevant gates
- **Zero required configuration**: Works out of the box

### 2. Immediate Value
- **Start using instantly**: Run on existing projects to find debt
- **Prevent future debt**: Install in new projects from day one
- **Incremental improvement**: Each run chips away at issues

### 3. Optimized for LLM Failure Modes
- **Detects what LLMs do wrong**: Duplication, unvetted code, complexity creep
- **Not focused on human errors**: Typos, incomplete refactors, emotional comments
- **Provides actionable output**: LLMs need exact instructions, not vague guidance

### 4. Minimal Friction
- **Fail-fast execution**: Don't waste time on checks that will fail anyway
- **Configurable thresholds**: Adjust to your project's reality
- **Profile-based workflow**: One command for common scenarios
- **Self-validation**: `sm validate --self` dogfoods the tool itself

---

## Available Gates

### Python Gates

| Gate                       | Description                               |
| -------------------------- | ----------------------------------------- |
| `python-lint-format`       | 🎨 Code formatting (black, isort, flake8) |
| `python-static-analysis`   | 🔍 Type checking (mypy)                   |
| `python-tests`             | 🧪 Test execution (pytest)                |
| `python-coverage`          | 📊 Coverage analysis (80% threshold)      |
| `python-diff-coverage`     | 📊 Coverage on changed files only         |
| `python-new-code-coverage` | 📊 Coverage for new code in PR            |

### JavaScript Gates

| Gate                 | Description                              |
| -------------------- | ---------------------------------------- |
| `javascript-lint`    | 🎨 Linting/formatting (ESLint, Prettier) |
| `javascript-tests`   | 🧪 Test execution (Jest)                 |
| `javascript-coverage`| 📊 Coverage analysis                     |
| `javascript-types`   | 📝 TypeScript type checking (tsc)        |

### Quality Gates

| Gate                  | Description                           |
| --------------------- | ------------------------------------- |
| `complexity`          | 🌀 Cyclomatic complexity (radon)      |
| `duplication`         | 📋 Code duplication detection (jscpd) |
| `template-validation` | 📄 Template syntax validation         |

### Security Gates

| Gate             | Description                                    |
| ---------------- | ---------------------------------------------- |
| `security-local` | 🔐 Fast local scan (bandit + semgrep + secrets)|
| `security-full`  | 🔒 Comprehensive security analysis             |

### Profiles (Gate Groups)

| Profile      | Description            | Gates Included                                                     |
| ------------ | ---------------------- | ------------------------------------------------------------------ |
| `commit`     | Fast commit validation | lint, static-analysis, tests, coverage, complexity, security-local |
| `pr`         | Full PR validation     | All gates + PR comment check                                       |
| `quick`      | Ultra-fast lint check  | lint, security-local                                               |

---

## Usage

```bash
# Validation with profiles (preferred)
sm validate commit                    # Fast commit validation
sm validate pr                        # Full PR validation
sm validate quick                     # Ultra-fast lint only

# Validation with specific gates
sm validate python-coverage           # Single gate validation
sm validate --self                    # Validate slop-mop itself

# Setup and configuration
sm init                               # Interactive project setup
sm init --non-interactive             # Auto-configure with defaults
sm config --show                      # Show current configuration

# Help
sm help                               # List all quality gates
sm help commit                        # Show what's in a profile
sm help python-coverage               # Detailed gate documentation
```

---

## Configuration

Slop-Mop works with **zero configuration** but supports customization via `.sb_config.json`:

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

## Philosophy Deep Dive

Slop-Mop emerged from a senior developer's choice to pivot early to LLM-driven code generation in 2024. The realization: **LLMs need heavy steering** to produce sustainable code.

Some of that steering happens mid-conversation ("No, don't refactor that file"). But a significant portion can be automated via context and protocol—forcing LLMs to follow best practices before they can introduce slop.

### The Dany/Tyrion Framework

From the [Substack article](https://scienceisneato.substack.com/p/a-hand-for-daenerys-why-tyrion-is):

> **Daenerys** is a mid-level contractor optimized for velocity. Her PRs sail through review: acceptance criteria satisfied, tests written, docs updated. She wins battles.
>
> **Tyrion** has been around longer. He's methodical, strategic, and excellent at seeing around corners. He wins wars.
>
> You need both: the dragon to win today, the strategist to survive tomorrow. The problem is, your coding agent only came with the dragon.

Slop-Mop provides automated Tyrion-level oversight:
- **Before merge**: "Did you actually test this? Is coverage acceptable?"
- **During development**: "This function is too complex. Break it down."
- **At code review**: "There are unaddressed PR comments. Handle them."

The goal isn't to slow down the dragon—it's to ensure the dragon doesn't burn down the kingdom.

---

## License

MIT

---

<p align="center">
  <em>"I drink and I know things."</em> — Tyrion Lannister<br/>
  <em>"Dracarys."</em> — Daenerys Targaryen<br/><br/>
  <strong>Use both. That's the point.</strong>
</p>
