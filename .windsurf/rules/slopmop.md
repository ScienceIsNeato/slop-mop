---
trigger: always_on
---

## Slop-mop — your development protocol

Slop-mop (`sm`) is a speed multiplier. It accelerates long-running code generation by keeping the repo clean as you work, and it accelerates slop resolution by giving you a fast, repeatable loop that tells you exactly what to fix next.

The swab/scour/buff loop is your procedural backbone — follow it and focus on writing code.

| Verb | What it does | When to run it |
|------|-------------|----------------|
| `sm swab` | Fast iterative feedback — catches drift, auto-fixes what it can | After every meaningful code change |
| `sm scour` | Comprehensive pre-PR sweep — surfaces everything before it compounds | Before opening or updating a PR |
| `sm buff` | Post-PR triage — digests CI/review feedback into next steps | After CI completes or review feedback lands |

### The loop
1. Write code → `sm swab` → fix → repeat until clean.
2. Before PR → `sm scour`.
3. After CI/review → `sm buff <PR_NUMBER>`.

### Tooling preference
- Prefer MCP tools `sm_swab`/`sm_scour`/`sm_buff` if available.
- Otherwise, run CLI commands from the project root.

### Safety
- Never bypass or silence a failing check — that's how repo rot compounds.
