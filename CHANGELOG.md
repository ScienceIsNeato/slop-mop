# Changelog

All notable changes to slopmop are recorded here. The release workflow reads
the section matching the version being cut and uses it as the GitHub Release
body, so **a release cannot be published without a matching section here.**

Format: one `## X.Y.Z` section per release, newest first.

## 2.13.2

### The fix that matters: ask git what the source is

Gates hand their tool a path and trust the tool's ignore flag to skip the
rest. Those flags are POST-FILTERS — `isort --skip`, `detect-secrets
--exclude-files`, `flake8 --extend-exclude` all still walk and open the files
first. So a repo with a nested `.venv`, an uploads directory, or agent
worktrees pays full price for directories its config explicitly excluded, and
the gate blows its timeout. Every name list we add loses to the next repo's
layout: `.venv` vs `env`, `storage`, `.claude/worktrees`, `test-results`.

**The repository already knows.** `resolve_tool_paths()` now asks
`git ls-files -co --exclude-standard` and hands tools exactly the project's
own files, falling back to a walk when git is unavailable. On the repo that
surfaced this, git listed **139 Python files in 24ms where walking found
20,445** — and the isort check went from **47.8s to 0.22s**. One helper, used
by every gate, so this class of failure is fixed once rather than per gate.

### Bug fixes

- **flake8 silently checked nothing on nested layouts** — `_get_python_targets`
  only inspected TOP-LEVEL entries, adding a directory for being named
  src/tests/test/lib or holding `__init__.py`. A repo keeping code one level
  down (`server/app` beside `client/`) matched none of them, so the target list
  came back empty and the gate reported "no critical errors" without looking at
  a single file. Selection is now by content.

- **A formatter/linter that runs out of time is no longer reported as a
  finding** — a killed `isort` surfaced as "Import order issues found" with
  no file to look at, and a killed `black` as "Formatting check failed",
  sending people hunting for drift that was never detected. Each tool now
  says it ran out of time and names the knob that fixes it. Same pathology as
  the detect-secrets timeout fixed in 2.13.1, in the lint/format gate.

### New configuration

- **`tool_timeout` on `laziness:sloppy-formatting.py`** (default 60) — a
  large tree can format in 40-55s standalone and tip past the fixed ceiling
  once `scour` runs gates in parallel. Raising the timeout is the honest fix;
  the alternative was narrowing what gets formatted.

## 2.13.1

### Bug fixes

- **detect-secrets no longer times out on repos that exclude their build
  output** (#244) — scan-path pruning only looked at *top-level* entries, but
  excluded artifacts almost always live one level down: `client/build` beside
  `client/lib`, `server/.venv` beside `server/app`. The parent was handed over
  whole, so the scanner re-hashed exactly the directories the config had
  excluded and blew the 60s ceiling anyway. Pruning is now nested — a
  directory containing an excluded descendant is expanded into its surviving
  children, while a directory with nothing excluded below it is still passed
  as a single path. Depth- and count-capped, falling back to the previous
  shallow list if a repo fans out past the cap.
- **A detect-secrets timeout is no longer reported as a finding** (#244) — a
  killed scan reached no verdict, so it says nothing about whether a secret
  exists, but it surfaced as SLOP DETECTED with `(location unknown)` as the
  only detail. It now **WARNS** and names the lever that fixes it
  (`exclude_dirs`), matching how the module already treats a scanner that
  fails to start. **Upgrade note:** a repo whose secret scan was timing out
  moves from FAILED to WARNED.

## 2.13.0

Everything below except the `mcp` advisory came out of running `sm refit`
cold against a repository nobody here had seen — `botingw/rulebook-ai` — and
hitting the tool's own defects along the way. Ten were filed as barnacles
against this repo. The case-study artifacts are in `DOCS/case-studies/`.

### Behavior changes

- **A security scanner that fails to start is no longer a finding** (#332) —
  when bandit, semgrep or pip-audit could not be imported, the gate reported
  "N security scanner(s) found issues" with a fabricated finding naming a
  vulnerability that did not exist, while concealing that nothing had been
  scanned. The guard for this already existed in the codebase and was never
  called. Startup failures now produce a **WARNED** result naming the install
  command. **Upgrade note:** a repo whose environment is missing a scanner
  moves from FAILED to WARNED — the gate stops failing, so check `sm doctor`
  if you were relying on that failure. A scanner that ran and genuinely
  errored still FAILS.
- **Findings across byte-identical copies of a file are collapsed** (#331) —
  repos that vendor or distribute duplicated trees reported the same defect
  once per copy (one unused import in seven identical template copies read as
  five to seven findings). Survivors carry an `[also in N identical copies]`
  note. **Upgrade note:** reported finding counts will drop on such repos.
  The underlying files are unchanged; only the deduplicated count is new.
- **Version drift in `sm doctor` warns instead of failing** (#331) — a
  patch-level mismatch between an installed tool and its pin blocked
  `sm refit` outright. Missing and rejected tools still FAIL.
- **`missing-annotations` reports a could-not-run as ERROR** (#331) — when
  mypy exited non-zero for a non-type reason (duplicate module names, config
  errors) the gate reported `FAILED: 0 type error(s) found` with empty
  output. It now returns ERROR carrying mypy's own message. Genuine type
  errors still FAIL.
- **The hull grade label carries a findings count and delta** (#331) — e.g.
  `F — scuttled · 20 findings (down 37)`. The **letter grades are unchanged**,
  so `minimum-grade` in the GitHub Action behaves exactly as before.

### Fixes

- **`string-duplication` reported paths that did not exist** (#332) — two
  layered bugs: `os.path.relpath` was called with no start directory, so
  paths resolved against the process working directory; and on macOS the
  scanner's resolved `/private/var/...` tempdir spelling did not match the
  unresolved `/var/...` one, leaving `/private` glued to the front of every
  project path. Paths are now project-relative, with both spellings remapped
  and symlinked roots resolved on both sides.
- **`dangling-references` could not tell code from prose** (#332) — Python
  subscript-then-call — indexing a dict of handlers, then calling the result
  — matches the inline-link pattern exactly, so a code sample using that form
  inside a fenced block was reported as a broken link, with the call's
  argument name as the supposed target. Fenced blocks are now skipped and
  inline code spans blanked, with multi-backtick and line-wrapping spans
  handled. (Written without the literal form: the released version flagged
  this very entry.)
- **`sm refit --iterate` named the wrong failing gate** (#332) — a targeted
  scour runs the requested gate *and its dependencies*, so a failing
  dependency was reported under the iterated gate's name, pointing at that
  gate's log, which had not been rewritten and still showed the previous
  run's output. The failing gate and log now come from the artifact's
  `first_to_fix`.
- **`sm init` disabled gates, then `sm refit` blocked on init's own choice**
  (#331) — auto-disabled gates now record that provenance, and refit treats a
  tool-owned disable as resolved rather than pending review. A gate you
  disabled yourself is still yours, and stays that way across re-runs.
- **`ambiguity-mines` did not mention `exclude_dirs`** (#331) — vendored and
  distributed copies should be excluded rather than refactored, which is what
  its sibling `repeated-code` already advised. The hint now names the option
  and prints the command.

### Chores

- **Ignore three `mcp` server-transport advisories** (#330) — PYSEC-2026-3481,
  3482 and 3483 have no upgrade path: `mcp` arrives transitively from semgrep,
  which pins `mcp==1.23.3` exactly, still true as of semgrep 1.172.0. The
  ignore must be re-checked when semgrep unpins `mcp`; until then the weekly
  scheduled scan would fail every week on an advisory nothing can act on.
- **Case-study artifacts and barnacle write-up** (#331, #333) — baseline and
  final scour artifacts plus the full ledger, including a correction to a
  test-count claim that credited us with a repair we had not made.

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

- **Preflight and `sm config` honored less of the config than the executor** (#324, #326,
  #327) — three divergences in "is this gate enabled / what config applies"
  are fixed: `sm refit --start`/doctor readiness ignored `[tool.slopmop]` in
  pyproject.toml; preflight and `sm config` ignored category-level
  `enabled: false`; and the venv-detection logic in the pyright gate could
  drift from the shared helpers. All of these now delegate to single
  canonical implementations (`slopmop/core/gate_config.py`,
  `slopmop.checks.mixins.detect_venv_path`).
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
