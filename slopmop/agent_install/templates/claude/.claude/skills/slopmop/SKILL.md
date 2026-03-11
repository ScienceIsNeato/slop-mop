---
name: slop-mop
description: >-
  Gradient descent tool and rapid development protocol — treats LLM weaknesses
  as adversarial patterns causing repo rot, provides greased rails via the
  swab/scour/buff loop so you can focus on writing great code.
---

# Slop-mop skill

Slop-mop (`sm`) is your procedural cornerstone for development in this repository. It provides a fast, repeatable loop that eliminates the guesswork of "what do I validate next?" — just follow the protocol and focus on code.

## When to use

- **During implementation**: Run `sm swab` after every meaningful code change. Each pass is gradient descent — it catches drift and auto-fixes what it can. Keep running until clean.
- **Before PR**: Run `sm scour` for a comprehensive sweep that surfaces everything before it compounds.
- **After CI/review**: Run `sm buff <PR_NUMBER>` to convert raw CI results and review feedback into a concrete remediation plan.

## The development loop

```
Write code → sm swab → fix → repeat (until clean)
                ↓ ready for PR
            sm scour → fix anything remaining
                ↓ PR opened
            sm buff <PR#> → follow remediation plan
```

## Tooling preference

- If MCP tools `sm_swab`, `sm_scour`, `sm_buff` are available, prefer those.
- Otherwise, run CLI commands directly from the project root.

## Safety

- Never bypass, disable, or silence a failing check — that's how repo rot starts.
- If output is large, summarize and cite the most actionable items first.
