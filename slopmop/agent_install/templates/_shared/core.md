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

### Tooling preference

Prefer MCP tools `sm_swab` / `sm_scour` / `sm_buff` / `sm_doctor` if
available. Otherwise, run CLI commands from the project root.
