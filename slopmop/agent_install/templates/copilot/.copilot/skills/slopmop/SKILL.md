---
name: slop-mop
description: >-
  Speed multiplier for long-running code generation and slop resolution —
  provides the swab/scour/buff loop so you always know what to do next.
---

# Slop-mop skill

Slop-mop (`sm`) is your procedural backbone for development in this repository. It accelerates long-running code generation by keeping the repo clean as you work, and it accelerates slop resolution by giving you a fast, repeatable loop that tells you exactly what to fix next.

## When to use

- **During implementation**: Run `sm swab` after every meaningful code change. Keep running until clean.
- **Before PR**: Run `sm scour` for a comprehensive sweep.
- **After CI/review**: Run `sm buff <PR_NUMBER>` to convert feedback into next steps.

## The loop

```
Write code → sm swab → fix → repeat (until clean)
                ↓ ready for PR
            sm scour → fix anything remaining
                ↓ PR opened
            sm buff <PR#> → follow remediation plan
```

## Tooling preference

- Prefer MCP tools `sm_swab`/`sm_scour`/`sm_buff` if available.
- Otherwise, run CLI commands from the project root.

## Safety

- Never bypass or silence a failing check — that's how repo rot compounds.