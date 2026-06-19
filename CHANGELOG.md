# Changelog

All notable changes to slopmop are recorded here. The release workflow reads
the section matching the version being cut and uses it as the GitHub Release
body, so **a release cannot be published without a matching section here.**

Format: one `## X.Y.Z` section per release, newest first.

## 2.7.0

### Hooks

- **Scour on push** (#298) — native pre-push hook now runs the full `sm scour`
  after the merged-branch guard. Reuses the swab cache so only scour-only and
  changed gates run fresh (~135ms cached vs ~3.6s cold, 27× speedup).
- **Machine-wide install** (#298) — `sm commit-hooks install --global` writes
  hooks to `~/.slopmop/git-hooks/` and sets `git config --global core.hooksPath`
  so every repo on the machine gets swab on commit + scour on push. Global hooks
  delegate to each repo's own `.git/hooks` first (preserving other tools' hooks),
  skip non-onboarded repos, and write passthrough delegation scripts for all
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
