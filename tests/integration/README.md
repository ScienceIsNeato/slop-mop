# Integration Tests — Runbook

## Automated (pytest)

```bash
pytest tests/integration/ -m integration -v
```

Requires Docker running. No other local setup needed — the fixture repo is cloned from GitHub inside the container.

## Refit Scenario Foundations

Higher-level `refit` integration work now uses a checked-in scenario manifest
contract under `tests/integration/scenarios/`.

- `happy-path-small.json` is the first Option A scenario contract
- `tests/integration/scenario_manifest.py` validates reserved refs, patch-ladder
  linearity, and run-branch naming
- `DockerManager.run_scripted_scenario(...)` is the persistent single-container
  seam for multi-step `sm refit --continue` loops

This is intentionally still a foundation layer. The actual agent-shim loop and
patch application logic will build on top of these helpers rather than bypass
them.

## Manual Walkthrough

### 1. Build the image

```bash
docker build -t slop-mop-integration-test -f tests/integration/Dockerfile .
```

### 2. Shell into the container

```bash
docker run --rm -it \
  -v "$(pwd):/slopmop-src:ro" \
  -w /test-repo \
  slop-mop-integration-test bash
```

### 3. Inside the container

```bash
# Clone the fixture repo
git clone https://github.com/ScienceIsNeato/bucket-o-slop.git .

# Install slop-mop from the mounted source
cp -r /slopmop-src /tmp/slopmop-build
pip install /tmp/slopmop-build

# Pick a branch: all-pass | all-fail | mixed
git checkout all-pass

# Init and validate
sm init --non-interactive
sm swab
```

### 4. Branch expectations

| Branch     | Expected exit | What it tests                                      |
|------------|:------------:|----------------------------------------------------|
| `all-pass` | 0            | All gates pass (happy path)                        |
| `all-fail` | 1            | Every gate uniquely broken                         |
| `mixed`    | 1            | security + dead-code + bogus-tests fail; duplication skipped |

## Bucket-o-Slop PR Code Scanning Workflow

Use this when preparing screenshots and end-to-end validation for GitHub Code Scanning.

1. Add/update `.github/workflows/slopmop-sarif.yml` in `bucket-o-slop`.
2. Validate workflow and fixture changes on `all-pass` first.
3. Port to `all-fail` and open a PR from `all-fail` into `all-pass`.
4. Capture annotations/screenshots from the PR's Code Scanning results.
5. Update `mixed` only when needed for a specific scenario.

### Exit code reference

| Code | Phase              |
|:----:|---------------------|
| 0    | All passed          |
| 1    | Validate found issues |
| 2    | pip install failed  |
| 3    | git checkout failed |
| 4    | sm init failed      |
| 5    | git clone failed    |
