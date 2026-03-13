I hit a milestone on a side project today and it got me wondering — does it make sense to ask "what's my personal AI force multiplier these days?" I *feel* like it helps me get more done, but I feel all sorts of silly nonsense, and I don't have a good feel for how to put a real number on it. But it occurred to me that a frontier model could probably take a pretty good crack at it — it has access to my actual GitHub contribution data, its training data would have included tons of studies on solo developer productivity metrics, and it doesn't have as much motivation to lie to itself about how productive it is...

So I gave it access to my GitHub profile and the side project repo I've been working on and sent it this prompt:

> Generate an estimate for how long it would have taken for me to have done all of this work by myself, with no rubber duck or sounding board other than stack overflow. Show me the estimate in terms of both man hours and calendar days. Show your work and justify your selections on the free variables.

The project is a Python CLI tool — ~44K lines of actual code (non-blank, non-comment — 22K source, 21K tests), 35 quality gates, SARIF reporting, CI/CD. 45 days from first commit to v0.8.0 on PyPI.

It pulled my contribution history across 10 years for calibration:

| Year | Contributions | Context |
|------|--------------|---------|
| 2016 | 47 | Employed, Poker/HalloweenTracker |
| 2017 | 62 | Employed, hardware projects |
| 2018 | 136 | Employed, HauntManager/LiDAR (peak pre-AI year) |
| 2019 | 8 | Employed, basically dormant |
| 2020 | 9 | Employed, basically dormant |
| 2021 | 44 | Employed, HauntManager revival |
| 2022 | 3 | Employed, flatlined |
| 2023 | 132 | Employed, GANGLIA (early AI tools) |
| 2024 | 102 | Left FTE, GANGLIA/HalloweenTracker |
| 2025 | 2,162 | No FTE, heavy AI-assisted |
| 2026 (10 wks) | 327+ | No FTE, slop-mop |

Important context: I haven't had a full-time job for about 2 years. So the 2024+ numbers reflect more available time, not just AI. Similarly, the 2016-2023 numbers are side-project-only output from someone with a day job. That matters for the calendar estimates.

Before looking at estimates, I wanted to ground this in something more concrete than commit counts. Commits are not a useful throughput metric — I can commit the same line 20 times and add nothing, or a single commit can contain a million lines. So I ran `git log --shortstat` across all my repos locally, split into pre-AI (pre-2023, original code only — no forks or vendored libs) and post-AI (2023+):

| Era | Repos | Commits | Insertions | Deletions | Gross LOC/commit | Net LOC/commit | Churn |
|-----|-------|---------|-----------|-----------|-----------------|---------------|-------|
| Pre-AI | 8 | 97 | 26,956 | 1,479 | **278** | **263** | 5.5% |
| Post-AI | 8 | 2,271 | 997,115 | 453,255 | **439** | **239** | 45.5% |

The pre-AI repos are things like HauntManager (Michael Myers animatronic controller, 60 commits), HalloweenPupUpMonster (5 commits), CandyDispenser (2 commits) — just me, writing code solo, committing when it works.

Caveats: the post-AI data probably has cloned/vendored code inflating things a bit. But that distinction kind of starts to fade when everything is machine-generated anyway — the workflow doesn't really differentiate between "I wrote this" and "the AI wrote this and I reviewed it."

Three things jump out:

1. **Net LOC per commit is almost identical**: 263 pre-AI vs 239 post-AI. Each commit produces roughly the same amount of surviving code regardless of era. The AI doesn't make bigger commits — it just makes them faster.

2. **Churn went from 5% to 45%**: Pre-AI, I barely deleted anything. Post-AI, nearly half the insertions get deleted in subsequent commits. That's the AI iterating — generate, test, throw away, regenerate. Not waste exactly, more like rapid prototyping baked into the workflow. But it means gross LOC massively overstates actual output.

3. **The multiplier is in velocity, not commit size**: If each commit nets ~250 LOC regardless, the question becomes: how many commits per hour of human engagement? Pre-AI I averaged ~12 commits/year across 8 repos while employed. Post-AI I'm doing ~757/year. Even normalizing for having ~3x more available time now (no day job), that's still a ~20x velocity increase per available hour.

**The estimates:**

It used McConnell's *Software Estimation* SLOC/hr ranges as the baseline: 15-30 LOC/hr for a motivated senior dev on a personal project in a language they know, including debug/design/test time. Broke it down by component complexity, applied a 1.3x rework factor for not having any design partner (justified by the 45% churn above — the repo already has 34% churn *with* an AI catching bad directions in real-time, solo would be worse), and added non-LOC overhead (architecture, spec research, integration debugging).

| | Optimistic | Best Estimate | Pessimistic |
|--|-----------|---------------|-------------|
| **Blended SLOC/hr** | 30 | 22 | 15 |
| **Base hours** | 1,640 | 2,400 | 3,280 |
| **Rework factor** | 1.15x | 1.30x | 1.45x |
| **Non-LOC overhead** | 180 | 270 | 400 |
| **Total man-hours** | **2,066** | **3,390** | **5,156** |

For the "actual" side: 41 active days at roughly 5-8 hrs/day of human engagement (prompting, reviewing, testing, directing) = **200-330 hrs**, best estimate ~275 hrs.

| Metric | Solo (est.) | With AI (actual) | Multiplier |
|--------|------------|-----------------|------------|
| Man-hours (best) | ~3,390 | ~275 | **12x** |
| Man-hours (optimistic) | ~2,066 | ~330 | **6.3x** |
| Man-hours (pessimistic) | ~5,156 | ~200 | **26x** |

**Calendar time** — this is where the employment context matters:

| Scenario | Pace | Calendar |
|----------|------|---------|
| Employed, side project (2016-2022 baseline) | ~5 hrs/wk sustained | **13 years** (or never — my history shows I don't sustain projects that long) |
| Unemployed, solo, no AI | ~25 hrs/wk | **~2.6 years** |
| Unemployed + AI (actual) | ~39 hrs/wk | **45 days** |

The apples-to-apples comparison for my current situation is the "unemployed, solo" row — ~2.6 years vs 45 days, about a **21x calendar multiplier**. The "employed, side project" scenario is scarier: 136 contributions in 2018, then 8 in 2019. 44 in 2021, then 3 in 2022. The project would stall and probably die.

One thing it said that I hadn't really put together before or heard articulated quite this way:

> The hardest thing to estimate is whether this project would exist at all. Your 10-year contribution history shows a clear pattern: bursts of high engagement followed by long dormancy. The AI didn't just multiply your throughput. It compressed the feedback loop tight enough that the project never left the burst phase.

The raw man-hours multiplier of ~12x (best estimate) is higher than I expected going in. A previous pass had it at 6.5x but was using 40 LOC/hr (too generous for "everything-in" solo productivity) and wasn't accounting for the full rework penalty of having no design partner at all.

But I'm genuinely curious — what would *you* use as the free variables here? Is 22 SLOC/hr too generous or too conservative for a motivated senior dev on a personal Python project? Is 1.3x rework the right penalty for no code review? What framework would you even use for this? And what numbers are you seeing on your end?

Would also love a better prompt if anyone has one. I feel like there's a version of this question that actually gets at the real answer instead of a fancy estimate.
