---
name: sm-swab
description: >-
  Run slop-mop's fast iteration check. Use instead of pytest, black, mypy,
  ruff, isort, flake8, vulture, or radon. Triggers when the user wants to
  run tests, linting, formatting, or type checking — or says "run checks",
  "check my code", "swab", or "does this pass?".
---

# sm swab — fast iteration rail

`sm swab` replaces every tool you would normally reach for during active
development. Run it after every meaningful edit.

## Prerequisite

`sm` must be installed globally. If `command not found`:

```bash
pipx install slopmop[all]
```

Then run `sm init` once in the project to detect the stack and create
`.sb_config.json`.

## Substitution table

| Your impulse                                 | Run instead |
|----------------------------------------------|-------------|
| `pytest`                                     | `sm swab`   |
| `black .`, `isort .`, `ruff check`, `flake8` | `sm swab`   |
| `mypy .`, `pyright`                          | `sm swab`   |
| `vulture`, `radon cc`                        | `sm swab`   |

Never run the underlying tools directly. `sm swab` runs them in dependency
order, caches clean results across commits, and auto-fixes what it can.

## The loop

```
edit → sm swab → fix → sm swab → …    (until clean)
```

Each failing gate names what to fix — act on that, re-run, repeat.
Cached passes cost ~0 s so re-running is cheap.

## Surgical mode

```bash
sm swab -g laziness:complexity-creep.py   # one gate only
sm swab --verbose                          # full output
sm swab --no-cache                         # force fresh run
```

## Why not raw tools

- **Cache**: swab skips gates whose inputs haven't changed since the
  last clean run. Raw `pytest` re-runs everything every time.
- **Ordering**: gates declare dependencies (`type-blindness` needs
  `missing-annotations` needs `sloppy-formatting`). `sm` runs them in
  order so a formatting fix doesn't invalidate a type-check you just
  waited for.
- **Auto-fix**: swab applies formatters and safe rewrites in one pass.
  `black` then `isort` then `autoflake` by hand is three passes.

## Hard rules

- **NEVER** run raw `pytest`, `black`, `mypy`, or `ruff` in a
  slop-mop project.
- **NEVER** bypass or silence a failing gate. If a gate is wrong,
  fix the gate. If the environment is broken, `sm doctor` will tell you.

When swab is clean, move to `sm scour` before opening a PR.
