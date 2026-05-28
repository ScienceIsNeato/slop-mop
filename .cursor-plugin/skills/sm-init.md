---
name: sm-init
description: >-
  Configure slopmop for this repo. Triggers when you find a repo with sm
  installed but no .sb_config.json, or after upgrading slopmop. Run before
  sm refit or the maintenance loop.
---

# sm init — initial repo setup

Run `sm init --non-interactive` when the repo has `sm` installed but no
`.sb_config.json`. It auto-detects the stack and writes a tuned config.

After init, run `sm sail` to enter the loop.

## Prerequisite

`sm` must be installed. If `command not found`:

```bash
pipx install slopmop[all]
```

## Usage

```bash
sm init --non-interactive   # agent context: skip prompts
sm init                     # interactive: prompts for test dirs, thresholds
```

Re-run after `pip install --upgrade slopmop` to pick up new gates.

## Hard rule

- Run `sm init` **before** `sm refit` or `sm swab` in a fresh repo.
  Without a `.sb_config.json`, gates cannot run.
