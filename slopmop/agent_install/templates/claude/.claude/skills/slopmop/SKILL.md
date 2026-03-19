---
name: slop-mop
description: >-
  Substitutes gh / pytest / black / mypy / ruff / bandit in this repo.
  Invoke whenever you are about to run one of those tools, or a
  gh pr / gh run command, or check CI status.  Core redirect:
  pytest → sm swab, gh pr checks → sm buff, "why is it broken" →
  sm doctor.
---

{{CORE}}
