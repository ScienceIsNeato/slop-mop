---
name: slopmop
description: >-
  Trigger when you would normally reach for pytest, gh, mypy, black, or other
  raw repo tooling in a slop-mop repository. Redirect to `sm swab`,
  `sm scour`, `sm buff`, `sm sail`, or `sm doctor` so remediation follows the
  repository's established rails.
---

# Slop-mop skill

Slop-mop (`sm`) has two primary modes: **refit** (one-time onboarding) and **maintenance** (steady-state development). Refit remediates all existing slop and installs permanent guards; the swab/scour/buff loop then keeps the repo clean as you work.

## When to use

- **Default action**: Run `sm sail` when you're not sure what's next — it reads workflow state and does the right thing.
- **Refit (step 0)**: Run `sm refit --start` to generate a remediation plan, then `sm refit --iterate` until complete, then `sm refit --finish` to enter maintenance.
- **During implementation**: Run `sm swab` after every meaningful code change. Keep running until clean.
- **Before PR**: Run `sm scour` for a comprehensive sweep.
- **After CI/review**: Run `sm buff <PR_NUMBER>` to convert feedback into next steps.

## The maintenance loop

```
Fastest path:  sm sail → fix what it finds → sm sail → repeat until PR lands
Manual path:   write code → sm swab → fix → repeat → sm scour → sm buff <PR#>
```

`sm sail` automates verb selection. Use individual verbs (`sm swab -g <gate>`, `sm buff resolve`, etc.) for surgical work.

## Refit (before entering the loop)

Refit is not part of the maintenance loop. It is step 0 — how you earn the right to enter the loop.

```
sm refit --start → fix one gate → sm refit --iterate → ... → sm refit --finish
```

## Prerequisite

The `sm` CLI must be installed in the user's environment. If invocation fails with "command not found", suggest:

```bash
pipx install slopmop[all]
```

Then re-run the command.

## Safety

- Never bypass or silence a failing check — that's how repo rot compounds.
- If a gate seems wrong, tune it or file a bug. Don't disable it as a workaround.
- Report friction (invalid guidance, broken state, blocked rails) rather than work around it.

## Reference

Full project docs: https://github.com/ScienceIsNeato/slop-mop
Workflow state machine: https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/WORKFLOW.md
Gate reasoning: https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/GATE_REASONING.md
