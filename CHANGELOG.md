# Changelog

All notable changes to slopmop are recorded here. The release workflow reads
the section matching the version being cut and uses it as the GitHub Release
body, so **a release cannot be published without a matching section here.**

Format: one `## X.Y.Z` section per release, newest first.

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
