# 🪣 Slop-Mop

<p>
  <a href="https://github.com/ScienceIsNeato/slop-mop/actions/workflows/slopmop-sarif.yml"><img src="https://github.com/ScienceIsNeato/slop-mop/actions/workflows/slopmop-sarif.yml/badge.svg" alt="Primary code scanning gate"/></a>
  <a href="https://codecov.io/gh/ScienceIsNeato/slop-mop"><img src="https://codecov.io/gh/ScienceIsNeato/slop-mop/branch/main/graph/badge.svg" alt="Coverage"/></a>
  <a href="https://pypi.org/project/slopmop/"><img src="https://img.shields.io/pypi/v/slopmop.svg" alt="PyPI version"/></a>
  <a href="https://pypi.org/project/slopmop/"><img src="https://img.shields.io/pypi/pyversions/slopmop.svg" alt="Python versions"/></a>
  <a href="https://github.com/ScienceIsNeato/slop-mop/releases"><img src="https://img.shields.io/github/v/release/ScienceIsNeato/slop-mop?display_name=tag&amp;sort=semver" alt="Latest GitHub release"/></a>
  <a href="https://github.com/ScienceIsNeato/slop-mop/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Slop--Mop%20Attribution%20v1.0-blue.svg" alt="License"/></a>
</p>

Slop-mop steers agents towards choices that maximize long-term repository maintainability
and stability by making the easy choices the right choices. 

<img src="https://raw.githubusercontent.com/ScienceIsNeato/slop-mop/main/assets/heraldic_splash.png" alt="Slop-Mop heraldic" width="300" align="right"/>

It does not try to turn agents into what they aren't. Rather, slop-mop takes LLMs' strengths
and points those assets at their own weaknesses. It does so via greased rails: a path of
least resistance toward more maintainable choices. The hard work is already done in the 
gate creation and orchestration - the agent just has to run the check and do exactly what sm
tells it to.

Don't make sloppy choices. Keep moving forward and address debt relentlessly.
Resist the urge to side-step the check. Just fix what it flags and keep moving: that is the whole idea.

It is purposefully opinionated, as structure begets adherence to best practices.

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

For an existing repo, start with refit. It walks the project through a
structured cleanup before you enter the day-to-day maintenance loop:

```bash
sm refit --start
sm refit --iterate
sm refit --finish
```

If you cannot do the full refit right now, generate a baseline as a temporary
escape hatch. That keeps new failures loud while you come back to the cleanup:

```bash
sm status --generate-baseline-snapshot
sm swab --ignore-baseline-failures
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

Slop-mop has five verbs you will actually use:

| Verb | What it is for | When to run it |
| --- | --- | --- |
| `sm status` | Workflow state and baseline snapshots | When you need current state or a temporary baseline |
| `sm swab` | Code-centric local feedback | After meaningful code changes |
| `sm scour` | Code-centric pre-PR sweep | Before opening or updating a PR |
| `sm buff` | Process-centric CI and review follow-up | After CI completes or review feedback lands |
| `sm sail` | Process-centric next-step selection | When you are not sure what to do next |

The boring version:

```text
write code -> sm swab -> commit -> sm scour -> push/open PR -> sm buff
```

Not sure where you are in that loop? `sm sail` figures it out for you.
Full state machine: [DOCS/WORKFLOW.md](https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/WORKFLOW.md).

<figure>
  <img src="https://raw.githubusercontent.com/ScienceIsNeato/slop-mop/main/assets/sm-swab-human-readable.png" alt="Human-readable sm swab output showing grouped quality gates and a no slop detected summary" />
  <figcaption>
    The default <code>sm swab</code> view is built for humans: grouped gates,
    progress, timings, and a clear final verdict. Agent loops can use
    <code>--porcelain</code> when they need terse output instead.
  </figcaption>
</figure>

## What It Checks

Slop-mop groups gates around four common agent failure modes.

**Overconfidence**  
The code compiles. Tests pass. That's not the same as being tested or covered.
This catches missing tests, coverage gaps, and type-blindness that slips through
because the code *runs*.

**Deceptiveness**  
Tests pass, but do they actually prove anything? Bogus assertions, tests that
exist to make the coverage report happy, leftover debug traces that signal the
code was never properly cleaned up before shipping. Slop-mop sees through it.

**Laziness**  
Working code rots. Complexity creep, dead code, formatting drift, repeated
logic - these compound quietly until the codebase becomes unnavigable.
Catch them while they're small.

**Myopia**  
Your change looks fine. The repo-wide picture might not be. Duplication,
security gaps, dependency risk - things that only show up when you zoom out
past the file you're in.

The full gate reasoning lives in [DOCS/GATE_REASONING.md](https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/GATE_REASONING.md).

## Refit vs Maintenance

New repo or inherited mess? Start with refit. It builds a remediation plan
and walks you through gate-by-gate until the codebase is clean enough to
enter the maintenance loop:

```bash
sm refit --start
sm refit --iterate
sm refit --finish
```

Once you're in decent shape, maintenance is just the loop:

```bash
sm swab
sm scour
sm buff
```

Don't skip refit to go straight to maintenance on a dirty repo. You'll spend
more time fighting the gates than fixing the code. Do the work upfront.

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
bug. Don't just silence it and move on - that's how slop accumulates.

Migration behavior is documented in [DOCS/MIGRATIONS.md](https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/MIGRATIONS.md).

## Baselines

Inherited a mess and can't stop to fix it all right now? Snapshot the current
failures. New failures stay loud, old ones get paid down over time:

```bash
sm status --generate-baseline-snapshot
sm swab --ignore-baseline-failures
sm scour --ignore-baseline-failures
```

This isn't a way to hide problems. It's a way to stop old debt from blocking
every unrelated change while you work back to a clean state. Don't live in
baseline mode - it's a temporary unblocker, not a permanent config.

## CI

Run slop-mop in CI the same way you run it locally: install it and run the gate
command.

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

That's useful information. Don't route around it with ad-hoc commands and
pretend the rail is fine. Fix the gate, tune the config, file the bug. The
point isn't obedience - it's making the correct path the path of least
resistance.

For slop-mop tooling friction, file a barnacle issue upstream:

```bash
sm barnacle file \
  --title "short summary of the slop-mop friction" \
  --command "sm <verb> [flags]" \
  --expected "what should have happened" \
  --actual "what happened instead" \
  --repro-step "how to reproduce it" \
  --tried "what you already tried" \
  --workflow swab \
  --blocker-type blocking \
  --json
```

Barnacles are for defects in slop-mop itself: invalid guidance, false gate
results, broken rails, confusing output, or install/upgrade/refit friction. They
create structured GitHub issues tagged for maintainer triage. They are not a
local queue and not a replacement for fixing real target-repo failures.
The generated Markdown body is also written to `.slopmop/last_barnacle_issue.md`
so failed filings are retryable without reconstructing context.

## Contributing

For repo conventions, see [DOCS/CONVENTIONS.md](https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/CONVENTIONS.md).

For contribution guidance, see [DOCS/CONTRIBUTING.md](https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/CONTRIBUTING.md).

For local development, see [DOCS/DEVELOPING.md](https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/DEVELOPING.md).

## License

Slop-mop uses the [Slop-Mop Attribution License v1.0](https://github.com/ScienceIsNeato/slop-mop/blob/main/LICENSE).

If you use it, attribution is required.
