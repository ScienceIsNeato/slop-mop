# /sm-sail — drive a PR to green, autonomously

`sm sail` is the one verb you run to move a change forward. It reads the
workflow state and **drives** — running swab, scour, CI watch, and review
triage in sequence — stopping only when it needs *you* to do something it
can't: fix a failing gate, commit, push, open the PR, resolve a review thread,
or make a decision. You do that one thing, then run `sm sail` again.

This is **a loop, not a one-shot.** Once you've started sailing a change, you
own it until `sm sail` reports **PR ready for human review** — or you hit a
decision only the human can make. Do **not** end your turn with `sm sail`
parked on a step you could have taken. "I ran sail once" is not done.

## The loop

```text
until sail says "PR ready for human review":
    sm sail                 # drives as far as it can, then parks with ONE ask
    # do exactly what it parked on:
    #   failing swab/scour gate → fix the reported issues
    #   "commit your changes"   → git add -A && git commit -m "..."
    #   "push / open PR"        → git push  (and gh pr create --fill if new)
    #   review threads          → fix in code, or resolve honestly (below)
    #   ⚓ HOLD / a real fork    → make the call, or escalate to the human
    # then run sm sail again
```

`sm sail` already runs `swab`, `scour`, `buff watch`, and review triage **under
the hood** — you don't call those directly. It also runs `scour` before it ever
tells you to push, so locally-catchable findings never cost a CI round-trip.
Reach for `sm swab -g <gate>` or `sm buff resolve` only for surgical work.

## When sail parks on review threads

Resolve each thread with a real scenario and **evidence** — never close one to
fake green:

- `fixed_in_code` — you changed the code. Cite the commit.
- `invalid_with_explanation` — the finding is wrong. Explain why, with evidence.
- `no_longer_applicable` — code moved since the comment. Say what changed.
- `out_of_scope_ticketed` — valid but not this PR. File an issue, link it.

```text
sm buff resolve <PR#> <THREAD_ID> --scenario <scenario> --message "<evidence>"
```

Then run `sm sail` again — it re-watches CI and re-checks threads. (Full triage
reference: `/sm-buff`.)

## When to stop before "PR ready" — only two reasons

1. **A decision you can't make** — an architectural fork, a product call, or
   genuinely ambiguous intent. Resolve that thread `--scenario
   needs_human_feedback --no-resolve` with the specific question, finish
   everything else first, then surface the single decision to the human. (Slow
   down at the forks — pushing harder in the wrong direction is the trap, not
   the fix.)
2. **A blocker you can't clear** — the same CI gate failing repeatedly despite
   real fixes, stalled progress across rounds, or an external outage (expired
   token, broken runner). Report what's stuck and what you tried.

Everything else — a nitpick, a lint finding, a coverage gap, a logic bug you
understand — is yours to fix, then `sm sail` again. Never return on work you
could have finished, and never silence a failing check.

## Expect convergence, not one pass

LLM reviewers (CodeRabbit, Cursor Bugbot) re-review **every push**, so each
round of fixes can surface a smaller batch. 2–4 rounds to green is normal —
keep sailing.

**What `sm swab` does on its own** (not via sail): surfaces results and tells
you to commit, share them with the human, and await the next instruction — the
tacking-mode guidance lives there.

**First time in a repo?** Run `sm refit --start` first.

**Prerequisite:** `sm` must be installed. If `command not found`:
```bash
pipx install 'slopmop[all]'
```
