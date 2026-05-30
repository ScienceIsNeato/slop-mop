---
name: sm-buff
description: >-
  Triage CI results and PR review threads after pushing. Use as the
  first pass before raw gh run/log investigation when needed. Triggers
  when CI has run, a PR has review feedback, or the user says "buff",
  "check CI", "triage PR", "what failed in CI", "resolve this thread",
  or "watch PR <number>".
---

# sm buff — post-push CI triage

`sm buff` replaces every `gh pr` / `gh run` invocation after a push.
It fetches CI results and review threads and converts them into a
remediation plan — not just a colour, but what to do next.

## Prerequisite

`sm` must be installed globally. If `command not found`:

```bash
pipx install slopmop[all]
```

## Substitution table

| Your impulse                                     | Run instead                                          |
|--------------------------------------------------|------------------------------------------------------|
| `gh pr checks <PR#>`                             | `sm buff status <PR#>`                               |
| `gh pr checks <PR#> --watch`, `gh run watch`     | `sm buff watch <PR#>`                                |
| `gh pr view <PR#> --comments`                    | `sm buff <PR#>`                                      |
| Reading CI logs to find the failing test         | `sm buff inspect <PR#>` first, then raw `gh run list/view` or logs for missing detail |
| `gh api ... resolveReviewThread`                 | `sm buff resolve <PR#> <THREAD_ID> --scenario <s> -m "..."` |
| `gh pr review --approve` after addressing threads | `sm buff verify <PR#>` first                        |

## Buff subcommands

| Moment                          | Command                                                  |
|---------------------------------|----------------------------------------------------------|
| Just pushed, CI queued/running  | `sm buff watch <PR#>` — blocks until CI settles          |
| CI done, want a remediation plan | `sm buff <PR#>` — full triage                           |
| Quick status snapshot           | `sm buff status <PR#>`                                   |
| Dig into one failure            | `sm buff inspect <PR#>`                                  |
| Resolve a review thread         | `sm buff resolve <PR#> <THREAD_ID> --scenario <s> -m "..."` |
| Confirm all threads resolved    | `sm buff verify <PR#>`                                   |

## Thread resolution scenarios

When resolving threads with `sm buff resolve`, pick the scenario that fits:

- `fixed_in_code` — code addresses the feedback; cite the commit
- `invalid_with_explanation` — feedback is incorrect; explain with evidence
- `no_longer_applicable` — code changed since the comment
- `out_of_scope_ticketed` — valid but not this PR; file an issue and link it
- `needs_human_feedback` — intent unclear; ask for clarification (uses `--no-resolve`)

## The full loop

```
git push
sm buff watch <PR#>               # blocks until CI settles
sm buff <PR#>                     # triage: what failed and what to do
fix → commit → push
sm buff watch <PR#>               # repeat until CI + threads clean
sm buff verify <PR#>              # confirm all threads resolved
```

## Hard rules

- Start with `sm buff`. If it does not expose enough detail for a
  failure investigation, use raw `gh run list/view` or CI logs, then
  return to `sm buff` for structured resolution. Keep `gh run watch`
  on the buff rail.
- **NEVER** mark a failing check resolved without actually fixing it.
- Do not push fixes until all threads are resolved, marked
  `WONT_RESOLVE`, or explicitly awaiting human feedback.
