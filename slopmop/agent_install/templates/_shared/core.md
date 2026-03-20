## Slop-mop — your development protocol

Slop-mop (`sm`) is a speed multiplier. It accelerates long-running code generation by keeping the repo clean as you work, and it accelerates slop resolution by giving you a fast, repeatable loop that tells you exactly what to fix next.

The swab/scour/buff loop is your procedural backbone for normal development. In remediation-phase repos, `sm refit` is the stricter rail for paying down inherited slop one gate at a time.

| Verb | What it does | When to run it |
|------|-------------|----------------|
| `sm swab` | Fast iterative feedback — catches drift, auto-fixes what it can | After every meaningful code change |
| `sm scour` | Comprehensive pre-PR sweep — surfaces everything before it compounds | Before opening or updating a PR |
| `sm buff` | Post-PR triage — digests CI/review feedback into next steps | After CI completes or review feedback lands |
| `sm refit` | Remediation rail — persists a gate-by-gate plan and advances it deterministically | When a repo is still in remediation phase |

### The loop
1. Write code → `sm swab` → fix → repeat until clean.
2. Before PR → `sm scour`.
3. After CI/review → `sm buff <PR_NUMBER>`.

### Remediation rail
- If the repo is still in remediation phase, prefer `sm refit --generate-plan` to capture the current failing-gate plan.
- Then use `sm refit --continue` as the resume command after each fix.
- Let `refit` own the structured remediation commits; do not improvise commit sequencing when the rail is active.
- When another agent or wrapper is driving the loop, prefer `sm refit --json` or `--output-file` and consume `.slopmop/refit/protocol.json` instead of parsing prose.

### Tooling preference
- Prefer MCP tools `sm_swab`/`sm_scour`/`sm_buff` if available.
- Otherwise, run CLI commands from the project root.

### Safety
- Never bypass or silence a failing check — that's how repo rot compounds.
