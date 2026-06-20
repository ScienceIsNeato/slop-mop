# /sm-buff — CI + review-thread triage (under the hood of sail)

**You usually don't run buff directly — run `sm sail`.** `sm sail` drives the
whole PR to green and calls `buff watch` / triage for you, stopping only when it
needs you to act (see `/sm-sail`). Reach for `sm buff` here only for **surgical
work**: inspecting a specific failure, or resolving a single review thread when
sail has parked on threads.

## The buff verbs sail runs for you

| Moment                          | Run                                                       |
|---------------------------------|-----------------------------------------------------------|
| Block until CI settles          | `sm buff watch <PR#>` — exit 0 = CI green + threads clear |
| Snapshot without blocking       | `sm buff status <PR#>`                                     |
| What failed + remediation       | `sm buff inspect <PR#>`                                    |
| Take the next thread batch      | `sm buff iterate <PR#>`                                    |
| Resolve one thread              | `sm buff resolve <PR#> <THREAD_ID> --scenario <s> --message "…"` |
| Confirm threads cleared         | `sm buff verify <PR#>`                                     |

`sm buff watch` reports the terminal state sail keys off:
`Final PR state: clean - CI checks passed and PR feedback is resolved` (exit 0).

## Resolving a thread — honestly

When sail parks on review threads, resolve each with a real scenario and
**evidence** — never close one to fake green:

- `fixed_in_code` — you changed the code. Cite the commit.
- `invalid_with_explanation` — the finding is wrong. Explain why, with evidence.
- `no_longer_applicable` — code moved since the comment. Say what changed.
- `out_of_scope_ticketed` — valid but not this PR. File an issue, link it.
- `needs_human_feedback` — a decision only the human can make. Resolve with
  `--no-resolve` and a specific question; finish everything else, then surface
  it. This is one of only two reasons to stop before green (the other is a
  blocker you can't clear). See `/sm-sail`.

Then run `sm sail` again — it re-watches CI and re-checks threads.

Never run raw `gh pr checks [--watch]` or read CI logs by hand. `gh` knows the
colour; `sm buff` knows the fix.

**Prerequisite:** `sm` must be installed. If `command not found`:
```bash
pipx install 'slopmop[all]'
```
