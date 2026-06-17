# Changelog

All notable changes to slopmop are recorded here. The release workflow reads
the section matching the version being cut and uses it as the GitHub Release
body, so **a release cannot be published without a matching section here.**

Format: one `## X.Y.Z` section per release, newest first.

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
