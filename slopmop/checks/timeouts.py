"""Named subprocess-timeout tiers for the checks tree.

Before this module, ``timeout=60`` appeared ~20 times and ``timeout=120``
~16 times across the gates with no way to tell intent apart from accident
(tech-debt audit #10). Gates should pick the tier that matches what the
subprocess *does*; a repo-size problem that busts a tier is a reason to
bump the gate to the next tier, not to invent a new number.

The values are the historical ones — introducing this module changed no
behavior. A handful of one-off literals (10s, 15s, 180s) remain in gates
whose semantics didn't match a tier; normalize them opportunistically when
touching those gates.
"""

from __future__ import annotations

# Liveness/identity probes: `tool --version`, import checks. If a probe
# takes longer than this, the tool is effectively broken.
PROBE_TIMEOUT = 5

# Small metadata commands with bounded output: `git ls-files`, `npx --yes
# <tool> --version`, single-file parses.
QUICK_COMMAND_TIMEOUT = 30

# The standard single-tool analysis pass over a repo (linters, formatters
# in check mode). The default choice for a new gate.
DEFAULT_TOOL_TIMEOUT = 60

# Heavier analyzers that resolve imports or build type graphs (mypy,
# pyright, vulture over a large tree, security scanners).
SLOW_TOOL_TIMEOUT = 120

# Whole-suite invocations: running the project's tests, duplication scans
# that hash every file.
HEAVY_TASK_TIMEOUT = 300

# The pathological-but-legitimate ceiling: full coverage runs on large
# projects (e.g. flutter test --coverage). Anything beyond this is a hang.
EXHAUSTIVE_TASK_TIMEOUT = 900
