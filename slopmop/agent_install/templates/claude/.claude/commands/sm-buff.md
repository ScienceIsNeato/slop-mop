# /sm-buff — drive a PR to green, autonomously

`sm buff` is the post-push rail. This is **a loop, not a one-shot.** Once
you've pushed to a PR, you own it until CI is green and every review thread is
handled — or you hit a decision only the human can make. Do **not** end your
turn with CI in flight, a red check, or an unanswered review comment.
"I pushed" is not done. "`sm buff watch` exited 0" is done.

## Definition of done (the only success exit)

Run `sm buff watch <PR#>`. It blocks until CI settles, then prints exactly one
terminal state:

- `Final PR state: clean - CI checks passed and PR feedback is resolved`
  → **done.** Report the green state and stop.
- anything else (`blocked by CI`, `unresolved PR review threads remain`)
  → **not done.** Keep driving the loop below.

`sm buff watch` exits 0 *only* in the clean case. Treat its exit code as the
loop condition — you are not finished until it is 0.

## The loop

```text
until clean:
    sm buff watch <PR#>            # blocks on CI; exit 0 = clean, stop here
    sm buff inspect <PR#>          # what failed + what to do about it
    # --- handle EVERY item this round ---
    failed CI job   → fix in code
    review thread   → fix in code, OR resolve with a real scenario (below)
    sm scour                       # catch locally what CI would catch, BEFORE pushing
    sm buff finalize <PR#> --push  # commit + push the batch
    # → back to watch
```

With many threads, drive the batches with `sm buff iterate <PR#>` between
inspect and finalize — it hands you one prioritized batch at a time so you
don't thrash.

## Handling review threads — honestly

Every thread is resolved with a scenario **and evidence**, never silently
closed to fake green:

- `fixed_in_code` — you changed the code. Cite the commit.
- `invalid_with_explanation` — the finding is wrong. Explain why, with evidence.
- `no_longer_applicable` — code moved since the comment. Say what changed.
- `out_of_scope_ticketed` — valid but not this PR. File an issue, link it.

```bash
sm buff resolve <PR#> <THREAD_ID> --scenario <scenario> --message "<evidence>"
```

**Never mark a thread resolved just to turn the box green.** If you can't
honestly pick one of the four above, it's an escalation — see below.

## The one exit to the human

Use `needs_human_feedback` **only** when a thread needs a decision you can't
make: an architectural fork, a product call, or genuinely ambiguous intent.
(This is the "slow down at the forks" rule — pushing harder in the wrong
direction is the trap, not the fix.)

When you hit one:

1. Resolve that thread `--scenario needs_human_feedback --no-resolve` with the
   specific question.
2. Finish everything else in the loop first — don't strand the rest of the PR
   on one open question.
3. Then surface to the human: the PR number, the single decision you need, and
   the options.

That is the *only* reason to return before clean. A nitpick, a lint finding, a
coverage gap, a logic bug you understand — those are yours to fix, not to ask
about.

## Expect convergence, not one pass

LLM reviewers (CodeRabbit, Cursor Bugbot) re-review **every new commit**, so
each fix-and-push spawns a fresh, smaller batch. 2–4 rounds to clean is
normal — keep going. Two things keep it short:

- **Shift left:** run `sm scour` before every push. Lint, coverage, and SAST
  findings caught locally never cost a CI round-trip. The pre-push hook from
  `sm commit-hooks install` does this for you automatically.
- **Fix the root, not the symptom:** when a bot flags a pattern, scan your
  whole diff for other instances and fix them in the same push, so the next
  round can't re-raise it.

## Circuit breaker — stop and report instead of spinning

Autonomy is not "spin forever." Stop and report to the human if:

- the **same CI gate fails 3 times** despite real fix attempts (likely flaky or
  infra — say so, link the run), or
- **two consecutive rounds make no net progress** (the unresolved count isn't
  shrinking), or
- a check is **red for reasons outside the repo** (expired token, broken
  runner, external outage).

Report what's stuck and what you tried — don't burn turns, and don't fake a
resolution to escape.

## Command reference

| Moment                          | Run                                                       |
|---------------------------------|-----------------------------------------------------------|
| Just pushed / CI running        | `sm buff watch <PR#>` — blocks; exit 0 = clean            |
| Snapshot without blocking       | `sm buff status <PR#>`                                     |
| What failed + remediation       | `sm buff inspect <PR#>`                                    |
| Take the next thread batch      | `sm buff iterate <PR#>`                                    |
| Resolve one thread              | `sm buff resolve <PR#> <THREAD_ID> --scenario <s> --message "…"` |
| Commit + push the batch         | `sm buff finalize <PR#> --push`                            |
| Confirm threads cleared         | `sm buff verify <PR#>`                                     |

Never run raw `gh pr checks [--watch]` or read CI logs by hand. `gh` knows the
colour; `sm buff` knows the fix.

**Prerequisite:** `sm` must be installed. If `command not found`:
```bash
pipx install 'slopmop[all]'
```
