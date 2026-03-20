# Refit Integration Plan

## Purpose

This document defines the higher-level integration plan for testing `sm refit`
as a rail that can safely drive work in a secondary fixture repository.

The immediate goal is not to test a live LLM prompt. The goal is to test the
contract between slop-mop and an agent-like orchestrator that:

1. Reads `.slopmop/refit/protocol.json`
2. Applies the intended remediation in a controlled secondary repo
3. Hands control back to `sm refit --continue`
4. Repeats until the plan completes

The first prerequisite is a formal secondary-repo management protocol. Without
that, the integration suite will be flaky, hard to reason about, and likely to
violate `refit`'s own safety assumptions around branch and HEAD stability.

## Design Constraints

The protocol needs to preserve these invariants:

1. Fixture state must be deterministic and pin-able.
2. Reserved refs must never be mutated by a test run.
3. A test must be able to prove exactly which source commit produced which
   remediation patch.
4. `refit` must not observe unexpected HEAD movement inside the working repo.
5. Cross-repo relationships must be explicit, machine-readable, and reviewable.
6. The integration runner must be able to resume, inspect, and fail closed.

## Terms

- Primary repo: this repo, `slop-mop`
- Secondary repo: the fixture repo under test, currently `bucket-o-slop`
- Fixture base ref: the pinned starting commit checked out in the secondary repo
- Fixture patch ladder: a sequence of commits in the secondary repo whose diffs
  represent ideal remediation steps
- Scenario: one end-to-end integration test case for a specific remediation rail

## What Must Be Formalized

### Reserved refs

These refs in the secondary repo are never to be force-moved, rebased, or used
as writable branches by the integration runner:

- fixture base refs pinned in `tests/integration/conftest.py`
- scenario source branches that hold the patch ladder
- tags used to mark scenario anchors

### Writable refs

The integration runner is allowed to create and mutate only per-run working
branches derived from the pinned fixture base ref.

### Identity and traceability

Every run needs stable metadata tying together:

- slop-mop commit SHA
- secondary repo base SHA
- secondary repo scenario branch or tag
- scenario patch-ladder commit SHAs
- working branch name
- protocol files emitted during the run

### Cross-repo linkage

When a change in one repo depends on a change in the other, that relationship
must be represented in metadata rather than buried in prose.

## Protocol Options

## Option A: Ephemeral Working Branch + Patch Ladder

This is the recommended option.

### Model

- Keep a pinned scenario branch in the secondary repo as read-only source data.
- Store the ideal remediation path as a linear sequence of commits on that
  branch.
- For each integration run, create a fresh writable working branch from the
  pinned fixture base SHA.
- The agent shim never checks out the next ideal commit directly.
- Instead, it applies the diff between consecutive ladder commits into the
  current working tree.

### Why it fits `refit`

`refit` blocks on unexpected HEAD movement. Directly checking out a different
commit in the working repo would violate that invariant. Applying a patch keeps
HEAD stable until `refit` itself performs the commit it owns.

### Git action order

1. Clone secondary repo
2. Fetch scenario refs and tags
3. Checkout pinned fixture base SHA in detached state
4. Create writable branch for the run
5. Run `sm init`, `sm refit --generate-plan`
6. Run `sm refit --continue`
7. On `blocked_on_failure`, have the shim apply the next patch-ladder diff
8. Re-run `sm refit --continue`
9. Repeat until `completed`
10. Record final git log, protocol sequence, and worktree status

### Branch naming

Scenario source branch:

- `scenario/refit/<scenario-name>`

Per-run writable branch:

- `run/refit/<scenario-name>/<yyyymmdd>-<short-slopmop-sha>-<run-id>`

Examples:

- `scenario/refit/happy-path-small`
- `run/refit/happy-path-small/20260319-a1b2c3d-run01`

### Metadata

Suggested scenario manifest fields:

```json
{
  "schema": "refit-integration/v1",
  "scenario": "happy-path-small",
  "secondary_repo": "ScienceIsNeato/bucket-o-slop",
  "fixture_base_sha": "<sha>",
  "scenario_branch": "scenario/refit/happy-path-small",
  "patch_ladder": [
    {"step": 1, "from_sha": "<sha>", "to_sha": "<sha>", "gate": "myopia:source-duplication"},
    {"step": 2, "from_sha": "<sha>", "to_sha": "<sha>", "gate": "overconfidence:coverage-gaps.py"}
  ]
}
```

### Cross-repo PR relationship

This option supports the cleanest PR linkage model:

- slop-mop PR introduces runner/protocol changes
- secondary repo PR introduces or updates scenario branch/patch ladder
- each PR references the other via explicit metadata fields or a shared scenario
  identifier

Suggested shared key:

- `scenario_id = refit-happy-path-small`

### Pros

- Preserves `refit`'s HEAD-stability invariant
- Easy to audit step-by-step
- Diffs are legible and attributable to gates
- Supports deterministic happy-path and failure-path scenarios

### Cons

- Requires maintaining a patch ladder in the secondary repo
- Slightly more setup than direct checkout approaches

## Option B: Detached Scenario Checkpoints + Worktree Copy

### Model

- Store ideal remediation checkpoints as commits or tags in the secondary repo
- For each step, export the tree delta from the checkpoint into a writable copy
  of the worktree used by the test
- The working branch remains local to the run

### Git action order

1. Clone secondary repo
2. Checkout pinned base SHA
3. Create writable run branch
4. On each blocked gate, materialize the file delta from the next checkpoint
   commit without checking out that commit into the active worktree
5. Resume `sm refit --continue`

### Branch naming

Checkpoint tags:

- `scenario/refit/<scenario-name>/step-<nn>`

Per-run branch:

- `run/refit/<scenario-name>/<run-id>`

### Pros

- Cleaner conceptual separation between immutable checkpoints and mutable run
  branch
- Easier to inspect exact step endpoints with tags

### Cons

- Slightly less natural than a linear patch ladder
- More bookkeeping if a step touches many files
- Easy for checkpoint tags and manifests to drift apart

## Option C: Direct Branch or Commit Handoffs

This option is not recommended.

### Model

- The agent shim checks out a different branch or commit in the secondary repo
  when it needs to apply a remediation step

### Why it is a poor fit

- Violates `refit`'s protection against unexpected HEAD movement
- Makes it hard to distinguish agent-authored changes from repo-state jumps
- Produces a less realistic contract test because `refit` is no longer owning
  the commit boundary the way it will in production

### Verdict

Do not use this unless `refit` is redesigned to explicitly allow external HEAD
movement, which would weaken an important safety invariant.

## Recommended Default

Choose Option A: Ephemeral Working Branch + Patch Ladder.

It is the best match for the current `refit` design because it keeps the
secondary repo's active HEAD stable during agent work while still letting the
test consume deterministic, ideal remediation outputs.

## Opinionated Protocol

This section defines the protocol if Option A is selected.

### Branch classes

Reserved immutable refs:

- `scenario/refit/<scenario-name>`
- `refs/tags/scenario/refit/<scenario-name>/base`
- `refs/tags/scenario/refit/<scenario-name>/step-<nn>`

Writable per-run refs:

- `run/refit/<scenario-name>/<timestamp>-<run-id>`

Forbidden actions on reserved refs:

- force-push
- rebase
- amend
- delete during normal test execution
- opening feature PRs directly from them

### Required metadata files

In the primary repo:

- `tests/integration/scenarios/<scenario-name>.json`

In the secondary repo:

- optional mirrored manifest or README explaining how the scenario ladder is
  maintained

Suggested manifest contents:

```json
{
  "schema": "refit-integration/v1",
  "scenario": "happy-path-small",
  "secondary_repo_url": "https://github.com/ScienceIsNeato/bucket-o-slop.git",
  "fixture_base_sha": "<sha>",
  "scenario_branch": "scenario/refit/happy-path-small",
  "reserved_tags": [
    "scenario/refit/happy-path-small/base",
    "scenario/refit/happy-path-small/step-01",
    "scenario/refit/happy-path-small/step-02"
  ],
  "patch_ladder": [
    {
      "step": 1,
      "gate": "myopia:source-duplication",
      "from_sha": "<sha>",
      "to_sha": "<sha>",
      "expected_commit_subject": "refactor(source-duplication): resolve remediation findings"
    }
  ],
  "cross_repo": {
    "scenario_id": "refit-happy-path-small",
    "slop_mop_tracking_issue": null,
    "secondary_repo_tracking_issue": null
  }
}
```

### Git action protocol

Order matters.

1. Fetch and verify reserved refs exist
2. Verify the fixture base SHA matches the scenario manifest
3. Create the writable run branch from the base SHA
4. Generate the refit plan
5. Let `refit` drive the loop
6. Only when protocol event is `blocked_on_failure`, apply the next ladder diff
7. Never manually commit after applying a ladder diff; let `refit` own the
   commit if the gate then passes with expected worktree state
8. If the protocol event is not the one expected for the next scenario step,
   fail closed
9. At completion, assert clean worktree and expected commit subjects

### Protection rules

The runner must fail closed when:

- reserved refs are missing
- reserved refs resolve to SHAs different from the manifest
- the active branch is not the writable run branch
- HEAD changes outside `refit`'s own commit events
- the next gate in protocol does not match the next patch-ladder step
- the worktree is dirty before a patch application begins

## Cross-Repo PR Policy

If a slop-mop change depends on a secondary-repo scenario update, treat the two
PRs as a pair with explicit linkage.

### Required linkage

Each paired PR should include:

- the shared `scenario_id`
- the counterpart repo PR URL or placeholder
- the pinned scenario manifest SHA being targeted

### Merge order

Preferred order:

1. Merge secondary repo scenario PR first
2. Update pinned SHAs in slop-mop
3. Merge slop-mop PR

If merge order must invert, the slop-mop PR should stay draft or clearly note
the pending secondary-repo prerequisite.

### PR naming

Primary repo PR title:

- `refit integration: add <scenario-name> runner coverage`

Secondary repo PR title:

- `fixture(refit): add <scenario-name> patch ladder`

## Initial Implementation Plan

This is the work plan once the secondary-repo management option is chosen.

### Phase 0: Protocol foundations

1. Add this document and lock the secondary-repo strategy.
2. Add a scenario manifest format under `tests/integration/scenarios/`.
3. Add validation helpers for reserved refs and scenario metadata.

### Phase 1: Integration runner

1. Extend `tests/integration/docker_manager.py` with a persistent scenario
   runner that can execute multiple commands in one container.
2. Add support for collecting multiple extracted files and a scenario summary.
3. Add fail-closed assertions for branch, HEAD, and worktree invariants.

### Phase 2: Deterministic agent shim

1. Implement a small scenario driver that reads `protocol.json`.
2. On `blocked_on_failure`, verify the expected gate and apply the next ladder
   patch.
3. Resume `sm refit --continue` until complete.

### Phase 3: First happy-path scenario

1. Add a minimal scenario with 3 to 4 gates in the secondary repo.
2. Add one end-to-end integration test proving:
   - event sequence correctness
   - structured commit subjects
   - final completed state
   - clean worktree

### Phase 4: Negative scenarios

1. Unexpected HEAD drift
2. Dirty worktree drift
3. Mismatched patch ladder step
4. Missing reserved ref or manifest mismatch

## Decision Request

Choose one:

1. Option A: Ephemeral Working Branch + Patch Ladder
2. Option B: Detached Scenario Checkpoints + Worktree Copy
3. Option C: Direct Branch or Commit Handoffs

Recommendation: Option A.