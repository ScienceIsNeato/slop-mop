# /sm-buff — replaces `gh pr checks`, `gh run view`, `gh pr view --comments`

Post-push rail.  Use instead of any `gh pr` / `gh run` invocation.
Buff fetches the same data and converts it into a remediation plan.

| Moment                         | Run                                          |
|--------------------------------|----------------------------------------------|
| Just pushed, CI queued/running | `sm buff watch <PR#>` — blocks until settled |
| CI done, want triage           | `sm buff <PR#>` — remediation plan           |
| Quick status snapshot          | `sm buff status <PR#>`                       |
| Unresolved review threads      | `sm buff verify <PR#>`                       |
| Resolve one thread             | `sm buff resolve <PR#> <THREAD_ID> -m "..."` |
| Dig into a single failure      | `sm buff inspect <PR#>`                      |
| Ready to push fixes            | `sm buff finalize <PR#> --push`              |

Never run raw `gh pr checks [--watch]` or read CI logs by hand.  Buff
knows which check failed *and* what to do about it.  `gh` only knows
the colour.
