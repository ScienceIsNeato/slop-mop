# 🪣 Slop-Mop

<p>
  <a href="https://github.com/ScienceIsNeato/slop-mop/actions/workflows/slopmop-sarif.yml"><img src="https://github.com/ScienceIsNeato/slop-mop/actions/workflows/slopmop-sarif.yml/badge.svg" alt="Primary code scanning gate"/></a>
  <a href="https://codecov.io/gh/ScienceIsNeato/slop-mop"><img src="https://codecov.io/gh/ScienceIsNeato/slop-mop/branch/main/graph/badge.svg" alt="Coverage"/></a>
  <a href="https://pypi.org/project/slopmop/"><img src="https://img.shields.io/pypi/v/slopmop.svg" alt="PyPI version"/></a>
  <a href="https://pypi.org/project/slopmop/"><img src="https://img.shields.io/pypi/pyversions/slopmop.svg" alt="Python versions"/></a>
  <a href="https://github.com/ScienceIsNeato/slop-mop/releases"><img src="https://img.shields.io/github/v/release/ScienceIsNeato/slop-mop?display_name=tag&amp;sort=semver" alt="Latest GitHub release"/></a>
  <a href="https://github.com/ScienceIsNeato/slop-mop/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Slop--Mop%20Attribution%20v1.0-blue.svg" alt="License"/></a>
</p>

Slop-mop is a quality gate runner for AI-assisted codebases.

It does not try to make agents smart. It gives them greased rails: a path of
least resistance toward more maintainable choices. Run the tool, read what
failed, fix that thing, run it again.

That is the whole idea.

Agents are good at closing the ticket in front of them. They are less good at
not leaving the codebase worse than they found it. Slop-mop looks for the mess
that still passes normal checks: shallow tests, duplicated logic, missing
coverage, complexity creep, stale config, unhandled PR feedback.

It is opinionated. Sometimes loudly. That is on purpose.

## Project Status

slop-mop has reached 1.0.0. The current public policy surface for release and
stability expectations lives here:

- [DOCS/COMPATIBILITY.md](https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/COMPATIBILITY.md)
- [DOCS/MIGRATIONS.md](https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/MIGRATIONS.md)
- [DOCS/RELEASING.md](https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/RELEASING.md)
- [SECURITY.md](https://github.com/ScienceIsNeato/slop-mop/blob/main/SECURITY.md)

## Quick Start

Install it:

```bash
pipx install slopmop[all]
```

Set up a repo:

```bash
sm init
```

Choose a starting point.

If the repo is already carrying failures, create a baseline and report only new
failures while you clean up:

```bash
sm status --generate-baseline-snapshot
sm swab --ignore-baseline-failures
```

If you want slop-mop to walk the repo through a structured cleanup first, use
refit instead:

```bash
sm refit --start
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
| `sm swab` | Code-centric local feedback | After meaningful code changes |
| `sm scour` | Code-centric pre-PR sweep | Before opening or updating a PR |
| `sm buff` | Process-centric CI and review follow-up | After CI completes or review feedback lands |
| `sm sail` | Process-centric next-step selection | When you are not sure what to do next |

The boring version:

```text
write code -> sm swab -> commit -> sm scour -> push/open PR -> sm buff
```

The workflow state machine is documented in [DOCS/WORKFLOW.md](https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/WORKFLOW.md).

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

The full gate reasoning lives in [DOCS/GATE_REASONING.md](https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/GATE_REASONING.md).

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

## Minimal Install

If you only want the framework without optional gate dependencies:

```bash
pipx install slopmop
```

Minimal install gives you the framework. Gates that need tools like `black`,
`pyright`, `bandit`, or `pytest` will tell you what is missing.

Developer setup details live in [DOCS/DEVELOPING.md](https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/DEVELOPING.md).

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

Migration behavior is documented in [DOCS/MIGRATIONS.md](https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/MIGRATIONS.md).

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

Run slop-mop in CI the same way you run it locally: install it, check out enough
git history for history-aware gates, then run the gate command.

See [DOCS/CI.md](https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/CI.md) for a GitHub Actions template.

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

Generated agent files are local workspace configuration. They should stay out
of source control; the reusable source templates live in this repository under
`slopmop/agent_install/templates/`.

The short version for agents: ride the rail, fix what it reports, do not bypass
the gate.

## Custom Gates

Slop-mop's CI framework is well adapted to existing checks that are not covered
by built-in gates. Add your own check as a custom gate and manage it like any
other slop-mop quality gate.

Start with [DOCS/NEW_GATE_PROTOCOL.md](https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/NEW_GATE_PROTOCOL.md).

## When To Push Back On The Tool

Sometimes slop-mop is wrong.

That is useful information. Do not route around it with ad-hoc commands and
pretend the rail is fine. Fix the gate, tune the config, or file the bug. The
point is not obedience. The point is making the correct workflow easier than the
wrong one.

For slop-mop tooling friction, start with:

```bash
sm barnacle --help
```

## Contributing

For repo conventions, see [DOCS/CONVENTIONS.md](https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/CONVENTIONS.md).

For contribution guidance, see [DOCS/CONTRIBUTING.md](https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/CONTRIBUTING.md).

For local development, see [DOCS/DEVELOPING.md](https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/DEVELOPING.md).

## License

Slop-mop uses the [Slop-Mop Attribution License v1.0](https://github.com/ScienceIsNeato/slop-mop/blob/main/LICENSE).

If you use it, attribution is required.
