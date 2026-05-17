---
name: sm-sail
description: >-
  Auto-advance the slop-mop workflow. Use when unsure what to run next,
  or to let slop-mop drive the iteration loop automatically. Triggers
  when the user says "sail", "what should I run?", "advance the workflow",
  "next step", or "keep going" in a project using slop-mop.
---

# sm sail — workflow auto-advance

`sm sail` reads the current workflow state and dispatches the right verb
automatically. Use it when you don't know whether to swab, scour, or buff.

## Prerequisite

`sm` must be installed globally. If `command not found`:

```bash
pipx install slopmop[all]
```

## When to use sail vs individual verbs

| Use `sm sail` when…                         | Use the verb directly when…              |
|---------------------------------------------|------------------------------------------|
| You want forward motion with no decisions   | You need a specific gate (`-g flag`)     |
| Continuing an established remediation loop  | You know exactly what phase you're in    |
| Letting an autonomous agent drive           | Surgical work on one check or thread     |

## The loop sail automates

```
edit → sm swab → fix → repeat            (until swab is clean)
       sm scour → fix → repeat           (until scour is clean)
       git push
       sm buff watch <PR#>               (blocks until CI settles)
       sm buff <PR#> → fix → repeat      (until CI + threads clean)
```

Run `sm sail` at any point — it reads `.slopmop/` state and picks up
where you left off.

## Hard rules

- **NEVER** bypass a failing gate — sail will not let you skip forward.
- If sail dispatches a verb and it fails, fix what it names, then run
  `sm sail` again.
- If the environment looks broken, `sm doctor` (or `sm doctor --fix`)
  before re-running sail.
