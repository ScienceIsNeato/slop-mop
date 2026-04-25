# 🪣 Slop-Mop

<p>
  <a href="https://pypi.org/project/slopmop/"><img src="https://img.shields.io/pypi/v/slopmop.svg" alt="PyPI version"/></a>
  <a href="https://github.com/ScienceIsNeato/slop-mop/actions/workflows/slopmop-sarif.yml"><img src="https://github.com/ScienceIsNeato/slop-mop/actions/workflows/slopmop-sarif.yml/badge.svg" alt="Primary code scanning gate"/></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+"/></a>
  <a href="https://github.com/ScienceIsNeato/slop-mop/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Attribution-blue.svg" alt="License"/></a>
</p>

Slop-mop is a quality gate runner for AI-assisted codebases.

It does not try to make agents smart. It gives them rails. Run the tool, read
what failed, fix that thing, run it again.

That is the whole idea.

Agents are good at closing the ticket in front of them. They are less good at
not leaving the codebase worse than they found it. Slop-mop looks for the mess
that still passes normal checks: shallow tests, duplicated logic, missing
coverage, complexity creep, stale config, unhandled PR feedback.

It is opinionated. Sometimes loudly. That is on purpose.

## Quick Start

Install it:

```bash
pipx install slopmop[all]
```

Set up a repo:

```bash
sm init
```

Run the normal loop:

```bash
sm swab
```

If it fails, fix what it reported and run `sm swab` again. When it passes,
commit. Before opening or updating a PR, run the deeper pass:

```bash
sm scour
```

After CI or review feedback lands:

```bash
sm buff
```

If you are not sure what comes next, use the auto-advance command:

```bash
sm sail
```

It reads the current workflow state and runs the next obvious slop-mop verb.

## The Loop

Slop-mop has four verbs you will actually use:

| Verb | What it is for | When to run it |
| --- | --- | --- |
| `sm sail` | Pick the next workflow step | When you are not sure what to do next |
| `sm swab` | Fast local feedback | After meaningful code changes |
| `sm scour` | Thorough pre-PR sweep | Before opening or updating a PR |
| `sm buff` | CI and review follow-up | After CI completes or review feedback lands |

The boring version:

```text
write code -> sm swab -> commit -> sm scour -> push/open PR -> sm buff
```

The workflow state machine is documented in [docs/WORKFLOW.md](docs/WORKFLOW.md).

## What It Checks

Slop-mop groups gates around four common agent failure modes.

**Overconfidence**  
Code exists, but is it tested? Typed? Covered? This catches missing tests,
coverage gaps, and type-checking blind spots.

**Deceptiveness**  
Tests pass, but do they prove anything? This catches bogus tests, debugger
artifacts, and other signs that the repo only looks clean.

**Laziness**  
The code works, but it is starting to rot. This catches complexity creep, dead
code, formatting drift, repeated code, stale docs, and silenced gates.

**Myopia**  
The local change looks fine, but the repo-wide picture is worse. This catches
duplication, security issues, dependency risk, and similar cross-cutting mess.

The full gate reasoning lives in [docs/GATE_REASONING.md](docs/GATE_REASONING.md).

## Refit vs Maintenance

There are two modes.

Use **refit** when a repo is already dirty and you need a structured cleanup
plan:

```bash
sm refit --start
sm refit --iterate
sm refit --finish
```

Use **maintenance** once the repo is in decent shape:

```bash
sm swab
sm scour
sm buff
```

Refit is slower and more deliberate. Maintenance is the day-to-day loop.

## Install Options

Most users should install everything:

```bash
pipx install slopmop[all]
```

Minimal install:

```bash
pipx install slopmop
```

Minimal install gives you the framework. Gates that need tools like `black`,
`pyright`, `bandit`, or `pytest` will tell you what is missing.

Extras are available if you want narrower installs:

| Extra | Adds |
| --- | --- |
| `lint` | formatting and lint tools |
| `typing` | type checkers |
| `analysis` | dead-code and complexity tools |
| `security` | security and dependency scanners |
| `testing` | pytest, coverage, and diff coverage tools |
| `templates` | Jinja template validation |
| `all` | all of the above |

Developer setup details live in [DEVELOPING.md](DEVELOPING.md).

## Configuration

`sm init` writes `.sb_config.json` after looking at the repo. It enables gates
that appear relevant and leaves non-applicable gates alone.

Useful commands:

```bash
sm config --show
sm config --enable myopia:vulnerability-blindness.py
sm config --disable laziness:complexity-creep.py
```

Disabling a gate should be temporary. If a gate is wrong, tune it or file the
tooling bug. If the repo is not ready yet, use refit or baseline mode instead of
pretending the problem is gone.

Migration behavior is documented in [docs/MIGRATIONS.md](docs/MIGRATIONS.md).

## Baselines

Sometimes you inherit a repo that is already messy. Slop-mop can snapshot the
current failures so new failures stay loud while old ones get paid down.

```bash
sm status --generate-baseline-snapshot
sm swab --ignore-baseline-failures
sm scour --ignore-baseline-failures
```

This is not a way to hide problems. It is a way to stop old problems from
blocking every unrelated change while you clean them up deliberately.

## CI

Run slop-mop in CI the same way you run it locally:

```yaml
name: slop-mop

on:
  pull_request:
  push:
    branches: [main]

jobs:
  swab:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: python -m pip install "slopmop[all]"
      - run: sm swab --json --output-file .slopmop/last_swab.json
```

This repo's own workflow is in
[.github/workflows/slopmop-sarif.yml](.github/workflows/slopmop-sarif.yml).

For PR closure, use `sm buff` after CI finishes. It checks CI state, unresolved
review threads, and the next action the agent should take.

## Agent Setup

Slop-mop can install repo-local agent instructions for common coding agents:

```bash
sm agent install
```

You can target one agent if you prefer:

```bash
sm agent install --target copilot
sm agent install --target cursor
sm agent install --target claude
```

The canonical agent workflow for this repo is in [AGENTS.md](AGENTS.md). The
short version: run the rail, fix what it reports, do not bypass the gate.

## Custom Gates

Slop-mop can run repo-specific checks alongside built-in gates. Use this when a
project has local rules that generic linting will never know about.

Start with [NEW_GATE_PROTOCOL.md](NEW_GATE_PROTOCOL.md).

## When To Push Back On The Tool

Sometimes slop-mop is wrong.

That is useful information. Do not route around it with ad-hoc commands and
pretend the rail is fine. Fix the gate, tune the config, or file the bug. The
point is not obedience. The point is making the correct workflow easier than the
wrong one.

## Contributing

For repo conventions, see [CONVENTIONS.md](CONVENTIONS.md).

For contribution guidance, see [CONTRIBUTING.md](CONTRIBUTING.md).

For local development, see [DEVELOPING.md](DEVELOPING.md).

## License

Slop-mop uses the [Slop-Mop Attribution License v1.0](LICENSE).

If you use it, attribution is required.