---
name: sm-refit
description: >-
  Onboard an existing repo to slop-mop with directed remediation. Use for
  repos that have many pre-existing failures or are adopting slop-mop for
  the first time. Triggers when the user says "refit", "onboard this repo",
  "adopt slop-mop", "this repo has a lot of failures", "clean up this codebase",
  or "set up slop-mop for this project".
---

# sm refit — one-time onboarding rail

Refit is step 0 — how you earn the right to enter the swab/scour/buff
maintenance loop. It is not part of the maintenance loop itself.

## Prerequisite

`sm` must be installed globally. If `command not found`:

```bash
pipx install slopmop[all]
sm init    # detect project type, create .sb_config.json
```

## The sequence

```bash
sm refit --start      # scan, capture all failing gates, persist a plan
                      # → .slopmop/refit/protocol.json

# For each gate in the plan:
#   fix the current blocker
sm refit --iterate    # resume plan: rerun current gate, auto-commit on
                      # pass, stop on next blocker

# Repeat until the plan is complete:
sm refit --finish     # verify plan against scour, transition to maintenance
```

## Key behaviours

- `--start` runs a full scour and creates a one-gate-at-a-time remediation
  plan. Gates are ordered by dependency — you can't skip ahead.
- `--iterate` reruns the current gate. When it passes, it auto-commits and
  advances to the next gate.
- `--finish` checks all plan gates against current scour results and
  transitions the repo from remediation to maintenance mode.
- Let refit own the commit sequencing. Don't improvise commits or reorder
  gates during remediation.
- For agent loops: use `sm refit --json` or `--output-file` and consume
  `.slopmop/refit/protocol.json` for structured state.

## Baseline escape hatch

If a full refit isn't feasible right now:

```bash
sm refit --baseline   # accept all existing failures, enter maintenance immediately
```

Use sparingly — this grandfathers failures rather than fixing them.

## After refit

Once `sm refit --finish` completes, use the maintenance loop:

```
sm swab → fix → sm swab (until clean)
sm scour → fix → sm scour (until clean)
git push → sm buff watch <PR#> → sm buff <PR#>
```

Or just run `sm sail` repeatedly.

## Barnacle discipline during refit

If slop-mop itself blocks valid work or gives bad guidance during refit,
file a barnacle — don't invent local workarounds:

```bash
sm barnacle file \
  --title "short summary" \
  --command "sm refit --iterate" \
  --expected "expected behaviour" \
  --actual "what actually happened" \
  --workflow refit
```
