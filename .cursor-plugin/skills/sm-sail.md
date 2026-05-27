---
name: sm-sail
description: >-
  Drive the slop-mop workflow toward a green, buffed PR. Use when the human
  says "sail", "ship it", "take it home", or approves the work and wants it
  shipped. Also use when unsure what to run next in a slop-mop project.
---

# sm sail — workflow autopilot

`sm sail` activates SAILING mode on entry, reads the current workflow state,
runs the next step or emits the exact command to run, then exits. Call it again
after following its instruction.

## Prerequisite

`sm` must be installed globally. If `command not found`:

```bash
pipx install slopmop[all]
```

## What sail tells you to do

```
sm sail → runs swab
  swab clean + uncommitted → "git add -A && git commit -m '...' then sm sail"
  swab clean + committed   → runs scour
  scour clean + no PR      → "git push -u origin HEAD && gh pr create --fill then sm sail"
  scour clean + PR exists  → "git push then sm sail"
  PR open                  → runs buff inspect
  buff issues              → fix gate, then sm sail again
  buff all-green           → ⛵ PR ready for human review
```

## Note on iterating-mode guidance

When `sm swab` passes outside of sail (iterating mode), the output includes
"share results with the human, await the next instruction." That guidance comes
from `sm swab` directly — `sm sail` is always in SAILING mode.

## Only stops for

- **Gate failure** — fix what it names, then `sm sail` again
- **`⚓ HOLD`** — human decision needed; address it, then `sm sail` again
- **PR ready** — surface to human for merge

## Hard rules

- **NEVER** bypass a failing gate — sail will not let you skip forward.
- If the environment looks broken: `sm doctor` before re-running sail.
