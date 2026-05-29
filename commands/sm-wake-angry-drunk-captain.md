# /sm-wake-angry-drunk-captain — escalate to the human

The last-resort verb. Use it ONLY when the loop is genuinely exhausted:
barnacles filed, gates green or truly unfixable, and the single remaining move
is a human judgment call no `sm` verb can make for you.

The standing order is *"do not wake the captain unless there's an emergency."*
He is asleep. He is angry. He is drunk. He went below decks because the crew
swore they had it handled. Picture his face before you reach for this.

```bash
sm wake-angry-drunk-captain \
  --objective "what you were trying to get done" \
  --verbs-tried "sm swab — green" \
  --verbs-tried "sm scour — green" \
  --verbs-tried "sm buff 42 — CI green, no unresolved threads" \
  --why-stuck "no remaining verb advances; the blocker is a product/design call" \
  --decision "the ONE call only a human can make" \
  --option "approach A" \
  --option "approach B"
```

All four of `--objective`, `--verbs-tried`, `--why-stuck`, and `--decision` are
required. Invoke the verb without them and it reads the standing order back to
you and refuses — that friction is the point. If you can't fill every line, you
don't have an emergency, you have unfinished work. Go back to `sm sail`.

A valid summons writes `.slopmop/last_captain_summons.md`, lays the case in
front of the captain, then **blocks on a prompt and waits for a human to type
orders**. You cannot satisfy this verb alone — a human must be at the keyboard.
The orders are recorded to the summons file and the workflow halts with a
non-zero exit. Carry out the captain's orders; do not keep looping.

If no human is at the wheel (non-interactive terminal), the verb refuses with
`🥃 NO CAPTAIN AT THE WHEEL` and decides nothing. Run it where the captain can
answer.

**Prerequisite:** `sm` must be installed. If `command not found`, suggest:
```bash
pipx install slopmop[all]
```
