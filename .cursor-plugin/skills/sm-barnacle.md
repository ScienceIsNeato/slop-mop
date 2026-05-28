---
name: sm-barnacle
description: >-
  Report slop-mop tool friction. Triggers when sm itself gives invalid
  guidance, blocks valid work, produces confusing output, or breaks install
  flow. Never use gh issue create for slop-mop bugs — use sm barnacle file.
---

# sm barnacle — report slopmop friction

Use when `sm` itself is broken — not when your repo has lint failures.

```bash
sm barnacle file \
  --title "short summary of the slop-mop friction" \
  --command "sm <verb> [flags]" \
  --expected "what should have happened" \
  --actual "what happened instead" \
  --repro-step "how to reproduce it" \
  --tried "what you already tried" \
  --workflow swab \
  --blocker-type blocking \
  --json
```

Use `--dry-run` when GitHub auth is unavailable. The generated issue body is
written to `.slopmop/last_barnacle_issue.md`.

## Hard rule

- **NEVER** use `gh issue create` for slop-mop friction.
  `sm barnacle file` targets the right repo, adds the correct labels,
  and captures platform/version metadata automatically.
- File the barnacle, then continue only if the friction is non-blocking.

## Prerequisite

`sm` must be installed. If `command not found`:

```bash
pipx install slopmop[all]
```
