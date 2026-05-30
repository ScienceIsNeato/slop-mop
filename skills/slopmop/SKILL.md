---
name: slopmop
description: >-
  Trigger when you would normally reach for pytest, gh, mypy, black, or other
  raw repo tooling. Redirect to `sm swab`, `sm scour`, `sm buff`, `sm sail`,
  `sm refit`, or `sm doctor` so remediation follows the established rails.
  Also trigger when you find a repo with sm installed but no .sb_config.json
  — use `sm init --non-interactive` before entering the loop.
  Also trigger when filing issues about slop-mop friction — use
  `sm barnacle file` / `/sm-barnacle`, never `gh issue create`.
  Also trigger when the maintenance loop is exhausted and only a human
  judgment call remains — use `sm wake-angry-drunk-captain` as a last resort.
---

# Slop-mop skill

> **Filing slop-mop friction?** Use `/sm-barnacle` or `sm barnacle file` — **never `gh issue create` directly**. The barnacle CLI auto-applies the correct labels and targets the right repo regardless of where you are.

Slop-mop (`sm`) has two primary modes: **refit** (one-time onboarding) and **maintenance** (steady-state development). Refit remediates all existing slop and installs permanent guards; the swab/scour/buff loop then keeps the repo clean as you work.

## When to use

- **Initial setup (step -1)**: Run `sm init --non-interactive` when the repo has
  `sm` installed but no `.sb_config.json`. This generates a config tuned to the
  detected stack. Run it before refit or the maintenance loop.
- **Default action**: Run `sm sail` when you're not sure what's next — it reads workflow state and does the right thing.
- **Refit (step 0)**: Run `sm refit --start` to generate a remediation plan, then `sm refit --iterate` until complete, then `sm refit --finish` to enter maintenance.
- **During implementation**: Run `sm swab` after every meaningful code change. Keep running until clean.
- **Before PR**: Run `sm scour` for a comprehensive sweep.
- **After CI/review**: Run `sm buff <PR_NUMBER>` to convert feedback into next steps.
- **Loop exhausted (last resort)**: Run `sm wake-angry-drunk-captain` only when barnacles are filed, gates are green or truly unfixable, and the one move left is a human judgment call no verb can make. It demands structured proof and then blocks for a human to type orders. See below.

## When the loop is exhausted: wake the captain

Every other verb assumes there is more *agent* work to do. `sm wake-angry-drunk-captain` is the one that doesn't — it escalates to the human, and only the human, when you have genuinely run out of moves.

The name is the guardrail. The captain is asleep, angry, and drunk; the standing order is *"do not wake me unless there's an emergency."* Picture his face before you reach for it.

Required proof (skip any and it reads the standing order back and refuses):

```bash
sm wake-angry-drunk-captain \
  --objective "what you were trying to get done" \
  --verbs-tried "sm swab — green" \
  --verbs-tried "sm buff 42 — CI green, no unresolved threads" \
  --why-stuck "no remaining verb advances; blocker is a product/design call" \
  --decision "the ONE call only a human can make" \
  --option "approach A" --option "approach B"
```

A valid summons blocks on a prompt and **waits for a human to type orders** — you cannot complete it alone. If no human is at the wheel, it refuses and decides nothing. When orders come, carry them out; do not keep looping. Full detail: `/sm-wake-angry-drunk-captain`.

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
- Report friction (invalid guidance, broken state, blocked rails) via `/sm-barnacle` rather than working around it.

## Reference

Full project docs: https://github.com/ScienceIsNeato/slop-mop
Workflow state machine: https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/WORKFLOW.md
Gate reasoning: https://github.com/ScienceIsNeato/slop-mop/blob/main/DOCS/GATE_REASONING.md
