# Changelog

All notable changes to slopmop are recorded here. The release workflow reads
the section matching the version being cut and uses it as the GitHub Release
body, so **a release cannot be published without a matching section here.**

Format: one `## X.Y.Z` section per release, newest first.

## 2.12.0

### New gate checks

- **`unpinned-action-ref` in `myopia:github-actions-hygiene`** (#326) — GitHub
  Actions referenced by mutable tag/branch refs (`@v5`, `@main`) are now
  findings; an immutable pin is a full 40-hex commit SHA. Local (`./`) and
  `docker://` refs are exempt, and deliberate moving tags (e.g. a first-party
  action) can be exempted via the new `allow_unpinned` config list.
  **Upgrade note:** repos with tag-pinned actions will see new findings —
  remediation is pin-to-SHA or allowlist.

### Fixes

- **Preflight/config honored less config than the executor** (#324, #326,
  #327) — three divergences in "is this gate enabled / what config applies"
  are fixed: `sm refit --start`/doctor readiness ignored `[tool.slopmop]` in
  pyproject.toml; preflight and `sm config` ignored category-level
  `enabled: false`; and the venv-detection logic in the pyright gate could
  drift from the shared helpers. All of these now delegate to single
  canonical implementations (`core/gate_config.py`, `mixins.detect_venv_path`).
- **Uppercase 40-hex SHAs count as pinned** (#326) — git SHAs are
  case-insensitive hex.

### Internals

- **One gate-name parser** (#327) — the `category:gate` format is parsed by
  `GateRef` everywhere (25+ ad-hoc `split(":")` sites removed), and the dead
  structured-config enablement API (zero consumers, inverted defaults) is
  deleted.
- **Named timeout tiers** (#327) — `checks/timeouts.py` replaces ~60 scattered
  timeout literals with six intent-named constants; no value changes.
- **Real-registry smoke tests + self-sufficient functional tests** (#326) —
  registration/priority regressions can no longer hide behind mocked
  registries or test-ordering luck.
- **CI hygiene** (#324, #325) — the action dogfood enforces a minimum grade
  (no more green badge over a failed verdict) and provisions project deps via
  the action's `project-install` input (#327); the release workflow fails
  loudly if the action-pin bump produces no change; artifact retention capped.

## 2.11.0

### Gate dependencies

- **The string-duplication scanner is a declared npm dependency** (#316) — the
  `myopia:string-duplication` gate now declares `find-duplicate-strings` (npm,
  pinned) in its `requirements()`, so it appears in `sm doctor --required-deps`
  and the v2 GitHub Action installs it. The vendored copy under `tools/` is a
  development convenience whose built output is gitignored, so it isn't present
  in a fresh clone or a pip/pipx-installed slop-mop — without this the gate
  warned-and-skipped in CI.

### Fixes

- **`.slopmop/` gitignore management recognizes the contents form** (#316) —
  `ensure_slopmop_gitignored` now treats `.slopmop/*` (used by repos that commit
  a file under `.slopmop/`, e.g. `required-deps.json` for the v2 Action) as
  already-ignored, instead of appending a duplicate `.slopmop/` rule each run.

## 2.10.0

### Gate dependencies

- **`sm doctor --required-deps` is applicability-aware** (#315) — the dependency
  manifest now excludes tools belonging to gates that don't apply to the repo
  (e.g. the Dart/Flutter gates when there's no `pubspec.yaml`). A gate that
  won't run doesn't make its tools "required", so the manifest — and the v2
  GitHub Action that installs from it — reflects exactly what the repo actually
  needs, instead of warning about system tools for gates that never execute.

## 2.9.0

### Gate dependencies

- **Every gate now declares the external tools it needs** (#305–#310) — each
  gate exposes a `requirements()` contract: the tool name, how it's installed
  (system / Python / npm / env var), an exact version pin, and whether it's
  required or merely degrades the gate when absent. This replaces the scattered,
  hardcoded tool lists with one source of truth per gate, covering the linters
  and formatters (ruff, black, isort, flake8, autoflake), the analyzers (mypy,
  pyright, vulture, radon), the security scanners (bandit, semgrep,
  detect-secrets, pip-audit), the string-duplication runtime (node), the
  Dart/Flutter toolchain, and actionlint.
- **`sm doctor --required-deps` emits a dependency manifest** (#311) — a
  schema-versioned JSON document listing exactly the tools your repo's enabled
  gates need, by exact pin, for the config you actually run. Deterministic and
  byte-stable, so CI and the GitHub Action can install precisely the right
  toolset (and cache on it) instead of installing everything and hoping. This is
  the single source of truth the v2 Slop-Mop Action installs from.
- **Missing `pyright` is now a hard failure, not a silent skip** (#308) — when a
  gate genuinely *requires* a tool and it isn't installed, the gate reports a
  could-not-run **ERROR** that fails the verdict, rather than quietly passing.
  Optional tools still degrade gracefully (the gate warns and runs). A broken CI
  environment can no longer mask a gate that never actually ran.
- **`sm doctor` reads the same contract** (#310) — doctor's gate-readiness and
  tool-inventory checks now derive entirely from `requirements()` and honour
  your repo's resolved config (`.sb_config.json` merged with `[tool.slopmop]` in
  `pyproject.toml`), so "which tools are missing" reflects exactly what the gates
  will see — and a tool a disabled gate would have needed is no longer flagged.

## 2.8.0

### Workflow

- **`sm sail` drives to green on its own** (#302) — `sm sail` is now autonomous.
  A single invocation runs the next workflow step (swab → scour → CI watch →
  review triage) and keeps going until it parks on something only you can do —
  fix a failing gate, commit, push, open the PR, resolve a review thread — or
  the PR is ready for human review. It no longer stops after one step, so you
  run one command instead of re-invoking it between every check. Commit, push,
  and PR creation stay manual (they need an authored message and body), so sail
  never mutates git or publishes on its own.
- **One verb, the rest under the hood** (#302) — the agent-facing surface
  collapses onto `sm sail`. `swab`, `scour`, and `buff` still exist for surgical
  work, but the drive-to-green loop, the definition of done (a change isn't done
  until sail reports *PR ready for human review*), and the command guidance all
  route through sail. `/sm-sail` is the primary loop; `/sm-buff` is demoted to
  the under-the-hood triage reference.

## 2.7.0

### Hooks

- **Scour on push** (#298) — native pre-push hook now runs the full `sm scour`
  after the merged-branch guard. Reuses the swab cache so only scour-only and
  changed gates run fresh (~135ms cached vs ~3.6s cold, 27× speedup).
- **Machine-wide install** (#298) — `sm commit-hooks install --global` writes
  hooks to `~/.slopmop/git-hooks/` and sets `git config --global core.hooksPath`
  so every onboarded repo on the machine gets swab on commit + scour on push.
  Global hooks delegate to each repo's own `.git/hooks` first (preserving other
  tools' hooks), skip non-onboarded repos, and write passthrough delegation scripts for all
  other hook types (commit-msg, prepare-commit-msg, post-checkout, etc.) so
  `core.hooksPath` doesn't silently swallow them. `--global` also works on
  install/uninstall.
- **Status + UX** (#298) — `sm commit-hooks status` now surfaces an active
  global install; per-repo install warns when global hooks are already shadowing
  `.git/hooks`.

## 2.6.0

### New gates

- **`myopia:conflicting-metadata`** (#291) — flags pages that disagree with
  themselves about their own URL: canonical vs `og:url`, canonical vs the
  sitemap (trailing-slash / scheme drift, including `sitemapindex` children),
  and `noindex` pages still listed in the sitemap. PURE, scour-level; auto-skips
  repos with no HTML.
- **`overconfidence:dangling-references`** (#289) — flags broken relative
  Markdown links and images whose target isn't on disk (the classic
  rename/move leftover). False-positive-free by construction; auto-skips repos
  with no Markdown.

### Hooks

- **Merged/deleted-branch commit guard** (#287) — the pre-commit hook now
  refuses commits onto a branch that's already merged or whose remote was
  deleted, so work doesn't pile onto a closed-out branch.

### CI / infra

- Dogfood the published `slop-mop-action@v1` in CI (#285).
- Cancel superseded workflow runs to cut Actions spend (#286).

Both new gates are opt-out and applicability-gated: existing projects pick them
up automatically on the next `sm scour` after upgrading, and only where
relevant (HTML / Markdown present).
