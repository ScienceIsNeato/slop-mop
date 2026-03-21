## Slop-mop — your development protocol

Slop-mop (`sm`) has two primary modes: **refit** and **maintenance**.

**Refit** is a one-time onboarding process. When you refit a repository, you have pulled into port — you stop all development and get the ship seaworthy. Refit remediates all existing slop in a repository and installs permanent guards to prevent the reintroduction of such slop. Running `sm` on an un-remediated repo is not recommended; slop-mop's ability to detect slop decreases as a function of the total amount of slop already present.

**Maintenance** is the steady-state. Once refit is complete, the swab/scour/buff loop is your procedural backbone for keeping the repo clean as you work.

| Verb | What it does | When to run it |
|------|-------------|----------------|
| `sm swab` | Fast iterative feedback — catches drift, auto-fixes what it can | After every meaningful code change |
| `sm scour` | Comprehensive pre-PR sweep — surfaces everything before it compounds | Before opening or updating a PR |
| `sm buff` | Post-PR triage — digests CI/review feedback into next steps | After CI completes or review feedback lands |

### The maintenance loop
1. Write code → `sm swab` → fix → repeat until clean.
2. Before PR → `sm scour`.
3. After CI/review → `sm buff <PR_NUMBER>`.

### Refit (step 0 — before entering the loop)

Refit is a nearly necessary first step for any repository adopting slop-mop. It is not part of the maintenance loop — it is how you earn the right to enter it.

- `sm refit --start` runs a full scour, captures the failing gates, and persists a one-gate-at-a-time remediation plan.
- `sm refit --iterate` resumes that plan: reruns the current gate, auto-commits when it passes, and stops on the first blocker.
- `sm refit --finish` checks the remediation plan against the current scour results and transitions the repo from remediation to maintenance mode.
- Let `refit` own the structured remediation commits; do not improvise commit sequencing during remediation.
- When another agent or wrapper is driving the loop, prefer `sm refit --json` or `--output-file` and consume `.slopmop/refit/protocol.json` instead of parsing prose.

While not recommended, you can use `--baseline` to accept all existing failures and transition to maintenance immediately. This is only offered as a way to unblock operations when a full refit is not feasible.

### Tooling preference
- Prefer MCP tools `sm_swab`/`sm_scour`/`sm_buff` if available.
- Otherwise, run CLI commands from the project root.

### Safety
- Never bypass or silence a failing check — that's how repo rot compounds.
