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

A valid summons writes `.slopmop/last_captain_summons.md` and halts the loop
with a non-zero exit. It does **not** read your terminal — an agent's stdin is
a pipe, never a live human, so forcing a prompt would make this verb unreachable
in the exact stuck-in-a-loop case it exists for. Instead it speaks the same
JSON-envelope contract as every other verb:

- `data.relay_to_human` — the captain's question, laid out for the human, ending
  on a direct ask. Show this to the user **verbatim**.
- `data.agent_directive` — the instruction back to you: **your turn is over.**
  Display `relay_to_human`, then stop and wait. Do not run another verb. Do not
  continue the loop.

The human answers in the chat; their reply is the captain's orders. Carry them
out — and do not wake him again. You cannot satisfy this verb alone; that is the
point.

**Prerequisite:** `sm` must be installed. If `command not found`, suggest:
```bash
pipx install slopmop[all]
```
