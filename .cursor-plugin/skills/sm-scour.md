---
name: sm-scour
description: >-
  Run slop-mop's deep pre-PR sweep. Use instead of pytest --cov, bandit,
  pip-audit, detect-secrets, jscpd, or diff-cover. Triggers when the user
  wants to check coverage, security, duplication, or says "before PR",
  "pre-PR", "scour", "is this ready to push?", or "full sweep".
---

# sm scour — pre-PR sweep

`sm scour` is the gate between local work and a pull request. Run it
after `sm swab` is clean, before `git push`.

## Prerequisite

`sm` must be installed globally. If `command not found`:

```bash
pipx install slopmop[all]
```

## Substitution table

| Your impulse                               | Run instead |
|--------------------------------------------|-------------|
| `pytest --cov`, `diff-cover`               | `sm scour`  |
| `bandit -r .`, `pip-audit`, `detect-secrets` | `sm scour` |
| `jscpd`, any duplication scanner           | `sm scour`  |

## What scour adds over swab

Scour runs all swab gates **plus** the deeper checks that are too slow
or noisy for every-edit feedback:

- **Coverage**: lines touched in this diff that lack test coverage
- **Security**: bandit static analysis, pip-audit for known CVEs,
  detect-secrets for leaked credentials
- **Duplication**: cross-file duplicate code blocks (jscpd)
- **String duplication**: repeated literals that should be constants
- **Complexity**: cyclomatic complexity above threshold

## The gate sequence

```
sm swab → fix → sm swab (clean)
sm scour → fix → sm scour (clean)
git push
```

Never open a PR without `sm scour` passing.

## Surgical mode

```bash
sm scour -g overconfidence:coverage-gaps.py   # one gate
sm scour --verbose                             # full output
```

## Hard rules

- **NEVER** open or update a PR without `sm scour` passing first.
- **NEVER** run raw `bandit`, `pip-audit`, or `pytest --cov` — you
  lose cache, ordering, and remediation guidance.
- If a gate is wrong, fix the gate.
