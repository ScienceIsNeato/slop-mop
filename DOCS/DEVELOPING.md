# Developing Slop-Mop

This guide is for maintainers and contributors working on slop-mop itself.

## Multi-Repo Isolation (Canonical Setup)

If you work across many repos and branches, use this model to prevent
cross-project interference:

1. Create a separate venv per project.
2. For most repos, install a pinned PyPI version:

```bash
pip install "slopmop==<version>"
```

3. For active slop-mop development, install editable from a branch-specific
   git worktree:

```bash
cd ~/Documents/SourceCode/slop-mop
git worktree add ~/Documents/SourceCode/slop-mop-wt-my-feature feat/my-feature

cd /path/to/target-project
python -m venv .venv
source .venv/bin/activate
pip install -e ~/Documents/SourceCode/slop-mop-wt-my-feature
```

Do not point multiple envs at a single moving checkout (for example
`pip install -e ~/Documents/SourceCode/slop-mop`) if you frequently switch
branches there.

Verify what each project is actually using:

```bash
python -c "import slopmop; print(slopmop.__file__)"
pip show slopmop
```

## Clean Slate (One-Time Reset)

If your machine has mixed old installs, reset once and then follow the model above.

```bash
# inspect current command resolution
type -a sm
which sm

# remove old global installs
pipx uninstall slopmop || true
python3 -m pip uninstall -y slopmop || true

# reinstall machine-level CLI runner
pipx install slopmop[all]
```

After that, in each project venv choose one of:

- stable: `pip install "slopmop==<version>"`
- active development: `pip install -e /path/to/slop-mop-worktree`

## Working In This Repo

When you are developing `slop-mop` itself, do not let a pipx-installed `sm`
win command resolution inside this checkout.

This repo now provides two local overrides:

```bash
source .envrc      # or: activate
type -a sm         # should show ./scripts/sm before ~/.local/bin/sm

./sm swab
sm swab
```

What this does:

- `.envrc` prepends `./scripts` to `PATH`, so `sm` resolves to the repo-local runner
- `./sm` is a root-level convenience wrapper that delegates to `scripts/sm`
- pipx remains installed machine-wide, but it is shadowed while you work in this folder

If command resolution still looks wrong:

```bash
source .envrc
hash -r
type -a sm
```

## Lock Behavior For Agents

`sm` uses a repo-level lock (`.slopmop/sm.lock`) to prevent overlapping runs in
one repository.

Behavior summary:

- If another run is active, `sm` exits with a busy message and ETA.
- Stale lock detection checks:
  1. lock PID is dead
  2. lock PID is alive but not an `sm/slopmop` process (PID reuse guard)
  3. lock age exceeds expected-duration threshold
- If process identity cannot be determined (`ps` unavailable/failing), lock logic
  fails closed and assumes the holder may still be valid.

Operational guidance:

- Start a new run only after lock owner exits.
- If a run crashed and lock is orphaned, remove lock file manually:

```bash
rm .slopmop/sm.lock
```

- Prefer a single orchestrator per repo at a time; avoid concurrent agent runs
  in the same working tree.
