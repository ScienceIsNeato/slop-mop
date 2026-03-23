---
name: slop-mop
description: >-
  Speed multiplier for long-running code generation and slop resolution —
  provides the swab/scour/buff loop and the refit remediation rail so you always know what to do next.
---

# Slop-mop skill

Slop-mop (`sm`) is your procedural backbone for development in this repository. It accelerates long-running code generation by keeping the repo clean as you work, and it accelerates slop resolution by giving you a fast, repeatable loop that tells you exactly what to fix next.

## When to use

- **Default action**: Run `sm sail` when you're not sure what's next — it reads workflow state and does the right thing.
- **During implementation**: Run `sm swab` after every meaningful code change. Keep running until clean.
- **During inherited remediation**: Run `sm refit --start`, then `sm refit --iterate` until the plan completes.
- **Before PR**: Run `sm scour` for a comprehensive sweep.
- **After CI/review**: Run `sm buff <PR_NUMBER>` to convert feedback into next steps.

## The loop

```
Fastest path:  sm sail → fix what it finds → sm sail → repeat until PR lands
Manual path:   write code → sm swab → fix → repeat → sm scour → sm buff <PR#>
Remediation:   sm refit --start → fix one gate → sm refit --iterate
```

`sm sail` automates verb selection. Use individual verbs for surgical work.

## Tooling preference

- Prefer MCP tools `sm_swab`/`sm_scour`/`sm_buff` if available.
- Otherwise, run CLI commands from the project root.

## Refit discipline

- Use `sm refit` only for remediation-phase repos.
- Treat `sm refit --iterate` as the canonical resume command.
- Let `refit` own the structured remediation commits when the rail is active.

## Safety

- Never bypass or silence a failing check — that's how repo rot compounds.