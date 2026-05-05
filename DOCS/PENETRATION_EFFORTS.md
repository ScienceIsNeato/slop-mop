# Penetration Efforts

This is the working notebook for getting slop-mop into more developer and agent
workflows. Each vector should record the current theory, the next concrete
actions, how we will know whether it worked, and what we learned.

Use this as a campaign log, not polished marketing copy. Keep it blunt and
update it whenever a channel produces signal.

## Operating Loop

For each vector:

1. Name the audience and the moment where slop-mop helps.
2. Make the install path obvious.
3. Ship the smallest credible artifact for that channel.
4. Measure PyPI downloads, GitHub traffic/clones, referrers, and direct replies.
5. Record what happened, then decide whether to double down, tune, or stop.

## Measurement

There is no per-skill install counter exposed by Anthropic. For now, use
external signals instead of writing telemetry into the skill.

### PyPI Downloads

The Claude plugin is a thin wrapper around the `slopmop` PyPI package. Every
new user still needs `sm` installed for the plugin to be useful, so PyPI
downloads are the primary adoption proxy.

- Live page: https://pypistats.org/packages/slopmop
- Deeper cuts: BigQuery dataset `bigquery-public-data.pypi.file_downloads`
- README badge: `https://img.shields.io/pypi/dm/slopmop.svg`

Limitations: PyPI does not distinguish Claude-discovered users from direct CLI
users, repeat installs from active use, or which `sm` verbs people run.

### GitHub Traffic

GitHub repo Insights provide the best engagement signal:

- Traffic: unique visitors and clones over the last 14 days
- Referrers: which channels are sending people here
- Stars and forks: slower trend-line signal
- Release downloads: useful only if release assets are attached

URL: https://github.com/ScienceIsNeato/slop-mop/graphs/traffic

### Weekly Check

Five-minute Friday ritual:

1. Record trailing 7-day PyPI downloads.
2. Record GitHub unique visitors and unique cloners.
3. Screenshot or note the referrers table.
4. Record stars/forks delta.
5. Add any notable channel-specific observations below.

## Vector: Claude Plugin Marketplace

### Theory

Claude Code and Cowork users already ask agents to run tests, fix CI, respond
to review comments, and prepare PRs. The plugin turns those moments into `sm`
rails without requiring per-repo agent setup.

### Distribution Model

Skills do not ship standalone in the Claude ecosystem. They live inside a
plugin, and plugins are listed in a marketplace repo containing
`.claude-plugin/marketplace.json`. End users install with:

```text
/plugin marketplace add ScienceIsNeato/slop-mop
/plugin install slopmop
```

This works in Claude Code and Cowork. Anthropic does not run a central package
registry like npm; discovery comes from this marketplace URL plus optional
inclusion in curated lists.

References:

- [Plugins reference](https://code.claude.com/docs/en/plugins-reference)
- [Create and distribute a plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces)
- [Discover and install prebuilt plugins through marketplaces](https://code.claude.com/docs/en/discover-plugins)
- [Use plugins in Claude Cowork](https://support.claude.com/en/articles/13837440-use-plugins-in-claude-cowork)

### Repo Assets

```text
slop-mop/
├── .claude-plugin/
│   ├── plugin.json
│   └── marketplace.json
├── skills/
│   └── slopmop/
│       └── SKILL.md
├── commands/
│   ├── sm-refit.md
│   ├── sm-sail.md
│   ├── sm-swab.md
│   ├── sm-scour.md
│   ├── sm-buff.md
│   └── sm-barnacle.md
├── assets/
│   └── claude-skill-demo.gif
└── slopmop/
```

Root-level `skills/` and `commands/` are the plugin source of truth. Repo-local
Claude config may mirror them, but it should not become the publishing source.

### Publish Checklist

- [ ] Version matches in `pyproject.toml`, `.claude-plugin/plugin.json`, and
  `.claude-plugin/marketplace.json`.
- [ ] `skills/slopmop/SKILL.md` still names concrete trigger tools like
  `pytest`, `gh`, `mypy`, and `black`.
- [ ] Demo gif renders correctly on GitHub.
- [ ] Fresh Claude Code smoke test passes:
  `/plugin marketplace add ScienceIsNeato/slop-mop`, then
  `/plugin install slopmop`, then prompt with `sail this repo`.
- [ ] Tag pushed and GitHub release notes published.

### Promotion TODOs

- [ ] Submit to Anthropic's official curated marketplace once the plugin is
  stable enough for broader discovery.
- [ ] Open PRs or submissions to community directories:
  `claudeskills.info` and `github.com/ComposioHQ/awesome-claude-skills`.
- [ ] Post in Anthropic Discord `#skills` with a short demo and the install
  commands.
- [ ] Try Reddit posts in r/ClaudeAI and r/aider if the story is concrete,
  not just announcement-shaped.
- [ ] Consider Hacker News only with a strong angle; raw launch posts are weak.

### Success Signals

- PyPI downloads rise after plugin promotion.
- GitHub unique cloners rise after marketplace links are shared.
- Referrers show Claude/Discord/community-list traffic.
- Users ask questions or file issues mentioning Claude Code or Cowork.

### Do Not Do

- Do not ship an MCP server for this just to look more integrated. Slop-mop is
  a CLI; the skill pattern is lighter and correct for Claude.
- Do not include hidden user telemetry in the plugin. If better attribution is
  needed later, use an explicit landing page or opt-in CLI telemetry.

## Vector: PyPI / Direct CLI

### Theory

Some users will not care about Claude at all; they need a local quality rail
for AI-heavy repos. The fastest path is still `pipx install slopmop[all]`.

### TODOs

- [ ] Keep the README install path short and above the fold.
- [ ] Make the PyPI project page render the same core story as GitHub.
- [ ] Watch PyPI downloads after every release and announcement.
- [ ] Track which docs pages users land on from PyPI if referrer data shows it.

### Success Signals

- PyPI downloads climb without corresponding GitHub clone spikes.
- Issues mention direct CLI usage rather than Claude plugin install.
- People ask about integrating `sm` into existing CI or repo templates.

## Vector: GitHub / OSS Discovery

### Theory

People browsing AI coding tools need to understand slop-mop in one screen:
what problem it solves, what command to run, and why it is different from a
pile of linters.

### TODOs

- [ ] Keep badges honest and useful: CI, coverage, PyPI version, downloads,
  release, license, Claude plugin.
- [ ] Keep the README demo asset current.
- [ ] Watch GitHub referrers weekly for unexpected channels.
- [ ] Convert repeated GitHub questions into docs sections.

### Success Signals

- Stars/forks increase after README or demo updates.
- Referrers show GitHub search, curated lists, blog posts, or newsletters.
- New issues reference the README language or demo directly.

## Vector: Community Lists and Newsletters

### Theory

Curated lists help users find tools while they are already evaluating agent
workflows. The goal is not a giant spike; it is durable presence in places
people revisit.

### TODOs

- [ ] Draft a short listing blurb that avoids generic quality-gate language.
- [ ] Submit to Claude skill/plugin directories.
- [ ] Submit to AI coding tool newsletters when there is a release hook.
- [ ] Record submission date, URL, maintainer response, and resulting traffic.

### Success Signals

- Referrer table shows the list/newsletter domain.
- PyPI downloads rise in the same week.
- Users arrive with vocabulary from the listing blurb.

## Vector: Direct User Conversations

### Theory

The best early signal may come from people already feeling agent-code pain.
Manual outreach can reveal whether the positioning lands before broader
promotion burns attention.

### TODOs

- [ ] Identify 5-10 likely users maintaining AI-assisted repos.
- [ ] Ask what currently breaks in their agent workflow before pitching.
- [ ] Offer one concrete command path: `sm init`, `sm swab`, `sm scour`.
- [ ] Record objections and missing docs.

### Success Signals

- Users try `sm` in a real repo.
- Feedback produces concrete gate or workflow improvements.
- Objections repeat, making the next docs/product fix obvious.

## Future Attribution Ideas

Do not build these until a decision is blocked on better data.

- Landing page with separate Claude Code, Cowork, and CLI install buttons.
- UTM-tagged links for community posts and directory submissions.
- Plausible or PostHog on the landing page.
- Explicit opt-in `sm telemetry enable` for verb/gate invocation counts.
- Anthropic marketplace install metrics, if they become available.