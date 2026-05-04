# Visibility & Adoption Tracking

There is no per-skill install counter exposed by Anthropic. To answer
"how many people are using slopmop?" we triangulate from three external
signals that don't require us to write any telemetry code or ask users to
opt in.

## The three signals

### 1. PyPI download stats — primary signal

The Claude plugin is a thin wrapper around the `slopmop` PyPI package. Every
new user, regardless of how they discovered the plugin, eventually has to
`pipx install slopmop` to make `sm` runnable. Daily downloads are the
single best proxy for active users.

- Live page: https://pypistats.org/packages/slopmop
- BigQuery (deeper cuts): the `bigquery-public-data.pypi.file_downloads`
  dataset. Free up to 1 TB/month.
- Badge for the README:
  ```markdown
  ![PyPI downloads/month](https://img.shields.io/pypi/dm/slopmop.svg)
  ```

What it doesn't tell you: who's using it via Claude vs directly, repeat use,
or which `sm` verbs people actually run. It's a top-of-funnel number.

### 2. GitHub repo Insights — engagement signal

GitHub gives you these for free under the **Insights** tab:

- **Traffic** — unique visitors and clones over the last 14 days. Clones
  are a strong proxy for "someone followed an install link." 14-day window
  only, so screenshot or export weekly if you want longer history.
- **Referrers** — where the traffic came from. Confirms which channels are
  actually working (Hacker News, Reddit, the Anthropic Discord, blog
  mentions).
- **Stars and forks** — slower signal but useful for long-term trend lines.
- **Releases** — download count per release asset (only relevant if you
  attach binaries).

URL: https://github.com/ScienceIsNeato/slop-mop/graphs/traffic

### 3. Marketplace add-events (proxy)

Currently no API exposes "how many people ran `/plugin marketplace add
ScienceIsNeato/slop-mop`." The closest proxies:

- The README image fetches (the demo gif). Hosted on raw.githubusercontent —
  not directly counted by GitHub but visible in CDN logs if you ever proxy
  through Cloudflare.
- GitHub clone count over time — installing the plugin clones the
  marketplace repo, so each fresh install is a clone.

If Anthropic later exposes install metrics through the official marketplace,
adopt those — for now, clones is the cleanest proxy.

## Recommended weekly check

Five-minute Friday ritual:

1. Open https://pypistats.org/packages/slopmop — note the trailing 7-day
   download total. Compare to last week.
2. Open https://github.com/ScienceIsNeato/slop-mop/graphs/traffic — note
   unique visitors and unique cloners. Screenshot the chart.
3. Glance at the **Referrers** table. Anything new? That's the channel you
   should double down on (or reach out to the author of).
4. Stars/forks delta. Slow signal but worth a 30-second glance.

Drop the four numbers into a `STATUS.md` row or a quick spreadsheet so the
trend line builds itself.

## What this won't catch

- Air-gapped enterprise installs that mirror PyPI internally (zero pypistats
  signal, zero GitHub signal).
- Users who installed once and never use it again. Downloads ≠ DAU.
- Which gates people are actually running. If this becomes a real question,
  consider an opt-in `sm telemetry enable` command in the CLI itself —
  that's a separate engineering project with privacy-policy implications and
  is intentionally **not** in scope for the plugin.

## When to upgrade the approach

External signals are the right fit until you have a specific decision that
needs better data. Concrete triggers:

- "Should we deprecate gate X?" → opt-in CLI telemetry that reports gate
  invocation counts.
- "Are users on Cowork or Claude Code?" → distinguish via a tiny landing
  page (e.g., `slopmop.dev/install`) with separate UTM-tagged install
  buttons. Plausible/PostHog free tier covers this.
- "What's our enterprise footprint?" → talk to Anthropic about pulling
  marketplace install counts directly.

Don't build any of that until a decision is actually blocked on it. PyPI +
GitHub Insights are enough for the first ~6 months of adoption.
