---
name: slopmop
description: >-
  Protocols for highly efficient and directed remediation of known quality
  issues — provides the swab/scour/buff maintenance loop and the refit
  onboarding process so you always know what to do next.
---

# Slop-mop skill

Slop-mop (`sm`) has two primary modes: **refit** (one-time onboarding) and **maintenance** (steady-state development). Refit remediates all existing slop and installs permanent guards; the swab/scour/buff loop then keeps the repo clean as you work.

## When to use

- **Refit (step 0)**: Run `sm refit --start` to generate a remediation plan, then `sm refit --iterate` until complete, then `sm refit --finish` to enter maintenance.
- **During implementation**: Run `sm swab` after every meaningful code change. Keep running until clean.
- **Before PR**: Run `sm scour` for a comprehensive sweep.
- **After CI/review**: Run `sm buff <PR_NUMBER>` to convert feedback into next steps.

## The maintenance loop

```
write code → sm swab → fix → repeat → sm scour → sm buff <PR#>
```

## Refit (before entering the loop)

Refit is not part of the maintenance loop. It is step 0 — how you earn the right to enter the loop.

```
sm refit --start → fix one gate → sm refit --iterate → ... → sm refit --finish
```

## Tooling preference

- Prefer MCP tools `sm_swab`/`sm_scour`/`sm_buff` if available.
- Otherwise, run CLI commands from the project root.

## Safety

- Never bypass or silence a failing check — that's how repo rot compounds.
