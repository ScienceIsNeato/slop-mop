# Integration Tests — Runbook

## Automated (pytest)

```bash
pytest tests/integration/ -m integration -v
```

Requires Docker running. No other local setup needed — the fixture repo is cloned from GitHub inside the container.

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

# Pick a branch: main | all-fail | mixed
git checkout main

# Init and validate
sm init --non-interactive
sm swab
```

### 4. Branch expectations

| Branch     | Expected exit | What it tests                                      |
|------------|:------------:|----------------------------------------------------|
| `main`     | 0            | All gates pass (happy path)                        |
| `all-fail` | 1            | Every gate uniquely broken                         |
| `mixed`    | 1            | security + dead-code + bogus-tests fail; duplication skipped |

### Exit code reference

| Code | Phase              |
|:----:|---------------------|
| 0    | All passed          |
| 1    | Validate found issues |
| 2    | pip install failed  |
| 3    | git checkout failed |
| 4    | sm init failed      |
| 5    | git clone failed    |
