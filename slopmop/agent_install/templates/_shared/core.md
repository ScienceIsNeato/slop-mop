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

### Live Dogfood Protocol

For live refit efforts in real target repositories, use barnacles to report
slop-mop friction upstream instead of treating it as target-repo work.

A **barnacle** is a defect or unexpected behaviour in slop-mop itself,
discovered while using it in a real repository. Barnacles are one-way GitHub
issues in the slop-mop repo, tagged for maintainer triage. They are not a
machine-local queue and they are not claimed or resolved from the target repo.

#### When To File
- Work in the target repository using normal `sm` rails.
- File a barnacle when slop-mop gives invalid guidance, blocks valid work,
  produces a false positive/negative, or makes the next step unclear.
- Do not file a barnacle for real target-repo lint, test, coverage, or review
  failures. Fix those normally.

#### How To File
Run this from the affected repository:

```bash
sm barnacle file \
  --title "short summary of the slop-mop friction" \
  --command "sm <verb> [flags]" \
  --expected "expected behaviour" \
  --actual "what actually happened" \
  --repro-step "first reproduction step" \
  --repro-step "second reproduction step" \
  --tried "what you already tried" \
  --output "short relevant output excerpt" \
  --workflow swab \
  --blocker-type blocking \
  --json
```

Use `--dry-run` if GitHub auth is unavailable and you need to capture the
structured issue body for a human. The generated body is written to
`.slopmop/last_barnacle_issue.md` by default; pass `--body-file <path>` if you
need a specific retry artifact location.

#### After Filing
- If the barnacle is non-blocking, continue the target-repo rail.
- If it blocks forward progress, stop that rail and report the issue URL.
- Do not invent a local workaround that hides the slop-mop defect.

#### Core Rule
- Never push through genuine slop-mop friction. File a barnacle issue with
  reproduction steps and let the upstream fix improve the tool for everyone.
