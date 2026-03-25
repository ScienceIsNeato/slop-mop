## Slop-mop (`sm`) — substitution table for this repository

`sm` wraps the tools you would normally reach for.  In this repository,
run `sm`, not the underlying tool.  The table below is the redirect —
when your impulse is the left column, run the right column instead.

| Your impulse                                      | Run instead                                  |
|---------------------------------------------------|----------------------------------------------|
| `pytest`                                          | `sm swab`                                    |
| `black .`, `isort .`, `ruff check`, `flake8`      | `sm swab`                                    |
| `mypy .`, `pyright`                               | `sm swab`                                    |
| `vulture`, `radon cc`                             | `sm swab`                                    |
| `pytest --cov`, `diff-cover`                      | `sm scour`                                   |
| `bandit -r .`, `pip-audit`, `detect-secrets`      | `sm scour`                                   |
| `jscpd`, any duplication scanner                  | `sm scour`                                   |
| `gh pr checks <PR#>`                              | `sm buff status <PR#>`                       |
| `gh pr checks <PR#> --watch`, `gh run watch`      | `sm buff watch <PR#>`                        |
| `gh pr view <PR#> --comments`                     | `sm buff <PR#>`                              |
| Reading CI logs to find the failing test          | `sm buff inspect <PR#>`                      |
| `gh api ... resolveReviewThread`                  | `sm buff resolve <PR#> <THREAD_ID> -m "..."` |
| `gh pr review --approve` after addressing threads | `sm buff verify <PR#>` first                 |
| "not sure what to do next"                        | `sm sail`                                    |
| "why won't sm / this gate run?"                   | `sm doctor`                                  |
| Stale `.slopmop/sm.lock`, broken state dir        | `sm doctor --fix`                            |

### Hard rules

- **NEVER** run raw `pytest`, `black`, `mypy`, or `ruff` in this repo.
  `sm swab` runs them in dependency order, caches clean results across
  commits, and auto-fixes what it can.  A bare `pytest` wastes a full
  run on things swab would have skipped from cache.
- **NEVER** run `gh pr checks`, `gh run view`, or read CI logs
  directly.  `sm buff` fetches the same data and converts it into a
  remediation plan — it knows which check failed and what you need to
  do next, not just that something is red.
- **NEVER** open or update a PR without `sm scour` passing first.
- **NEVER** bypass or silence a failing check.  If a gate is wrong,
  fix the gate.  If your env is wrong, `sm doctor` will tell you.

### The loop

```
edit → sm swab → fix → repeat            (until swab is clean)
       sm scour → fix → repeat           (until scour is clean)
       git push
       sm buff watch <PR#>               (blocks until CI settles)
       sm buff <PR#> → fix → repeat      (until CI + threads clean)
```

Or just run `sm sail` repeatedly — it reads the workflow state and dispatches the right verb automatically.

### Why you lose if you bypass `sm`

- **Cache:** swab/scour skip gates whose inputs haven't changed since
  the last clean run at this commit.  Raw tool invocations re-run
  everything every time.
- **Ordering:** gates declare dependencies (`type-blindness` needs
  `missing-annotations` needs `sloppy-formatting`).  `sm` runs them in
  order so a formatting fix doesn't invalidate a type-check you just
  waited for.  You can't get this from raw tool calls.
- **Remediation:** `sm` output tells you *what to do next*, not just
  *what's broken*.  `gh pr checks` says "failed"; `sm buff` says "line
  42 has a stale mock — here's the fix".
- **Auto-fix:** `sm swab` auto-applies formatters and safe rewrites.
  Running `black` by hand then `isort` by hand then `autoflake` by hand
  is three passes where swab does one.

Use `sm sail` for forward motion; use individual verbs (`sm swab -g <gate>`, `sm buff resolve`, etc.) for surgical work.

### Refit (step 0 — before entering the loop)

Refit is a nearly necessary first step for any repository adopting slop-mop. It is not part of the maintenance loop — it is how you earn the right to enter it.

- `sm refit --start` runs a full scour, captures the failing gates, and persists a one-gate-at-a-time remediation plan.
- `sm refit --iterate` resumes that plan: reruns the current gate, auto-commits when it passes, and stops on the first blocker.
- `sm refit --finish` checks the remediation plan against the current scour results and transitions the repo from remediation to maintenance mode.
- Let `refit` own the structured remediation commits; do not improvise commit sequencing during remediation.
- When another agent or wrapper is driving the loop, prefer `sm refit --json` or `--output-file` and consume `.slopmop/refit/protocol.json` instead of parsing prose.

While not recommended, you can use `--baseline` to accept all existing failures and transition to maintenance immediately. This is only offered as a way to unblock operations when a full refit is not feasible.

### Tooling preference

Prefer MCP tools `sm_swab` / `sm_scour` / `sm_buff` / `sm_doctor` if
available. Otherwise, run CLI commands from the project root.

### Live Dogfood Protocol (Recess Initiative)

For the live refit effort in `recess`, run a strict state machine to capture
real friction and immediately harden slop-mop.

#### State 1: Recess Remediation
- Work in `recess-fastback`, `recess-rn`, or `recess-matching` using normal `sm` rails.
- If friction appears (slowdown, weird behavior, incorrect result), stop immediately.
- Leave a pin with: repo, command/gate, exact error, and what was being attempted.
- Transition to State 2.

#### State 2: Fix Slop-Mop Friction
- Switch to slop-mop on the `friction` branch.
- Implement the smallest targeted fix for the pinned friction.
- Validate in slop-mop with `sm swab`.
- Commit the fix to `friction`.
- Transition to State 3.

#### State 3: Test Fix Against Real Friction
- Return to the original recess scenario and re-run the pinned command.
- If the fix works: log resolution and return to State 1.
- If the fix fails: return to State 2 and iterate.

#### Core Rule
- Never push through friction in State 1. Always pause remediation, fix slop-mop,
  and prove the fix in the real target workflow before resuming.
