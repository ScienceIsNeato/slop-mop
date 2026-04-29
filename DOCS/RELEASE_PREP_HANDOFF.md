# Release Prep Handoff

This document captures the deep-research follow-up that was **not** finished in
the current release-prep pass.

## What This PR Already Covers

This branch already addresses the following release-readiness items:

- release artifact verification in `.github/workflows/release.yml`
- generated `requirements.txt` sync from `pyproject.toml`
- public `SECURITY.md`, `DOCS/RELEASING.md`, and `DOCS/COMPATIBILITY.md`
- CI migration-coverage enforcement
- CI unit-test coverage signal and artifact publication
- fixture-based `sm upgrade` regression scenarios

## Remaining Fair-Game Work

These are still in scope if the goal is "final release prep without feature
enhancements":

1. `#113` `sm doctor` gaps
   The biggest remaining non-enhancement backlog item. This is still broad and
   likely wants to be split into smaller diagnostic improvements.

2. `#124` per-file string inventory / incremental duplication performance
   Labeled `triage:needed` and not marked as an enhancement in the current open
   issue list. This is the clearest remaining performance-oriented backlog item.

3. `#71` swab output token economics
   Still open and currently labeled `triage:debatable`. Worth touching only if
   agent-loop output size is still a practical blocker after the current release
   prep.

4. Historical config corpus beyond hand-authored scenarios
   This PR adds realistic fixture scenarios, but they are still authored inside
   the repo. A stronger 1.0 bar would archive real historical `.sb_config.json`
   snapshots keyed to actual released versions and verify `sm upgrade` against
   them.

5. Governance / maintainer policy surface
   `SECURITY.md`, release docs, and compatibility docs now exist, but there is
   still no dedicated maintainer/governance/support-process doc if that is
   desired before calling the project stable.

6. Broader packaging matrix confidence
   The release workflow now smoke-tests built artifacts, but there is still no
   dedicated matrix for wheel/install behavior across every claimed Python
   version or across macOS/Linux/Windows install modes.

## Parked Enhancement Work

These are intentionally **not** the next things to pull if the instruction is
"no feature enhancements":

- Open enhancement backlog still untouched: `#12`, `#46`, `#76`, `#82`,
  `#96`, `#102`, `#115`, `#116`
- Enhancement batch already implemented locally but not merged:
  `#14`, `#27`, `#45`, `#47`, `#127`
  Local branch: `codex/backlog-batch-14-27-45-47-127`

## Recommended Next Order

If release prep continues before more backlog feature work, the pragmatic order
is:

1. `#113`
2. `#124`
3. historical config corpus for `sm upgrade`
4. governance/support doc pass
5. `#71` only if output size is still causing real friction
