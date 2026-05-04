# Slop-mop Claude Plugin — Distribution Guide

This is the playbook for getting `slopmop` discovered and installed by Claude
Code and Cowork users.

## Distribution model

Skills don't ship standalone in the Claude ecosystem. They live inside a
**plugin**, and plugins are listed in a **marketplace** (a git repo
containing `.claude-plugin/marketplace.json`). End users install with:

```text
/plugin marketplace add ScienceIsNeato/slop-mop
/plugin install slopmop
```

This works identically in Claude Code and in Cowork. Anthropic does not run
a central package registry like npm — discoverability comes from your own
marketplace URL plus optional inclusion in curated lists.

References:
- [Plugins reference](https://code.claude.com/docs/en/plugins-reference)
- [Create and distribute a plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces)
- [Discover and install prebuilt plugins through marketplaces](https://code.claude.com/docs/en/discover-plugins)
- [Use plugins in Claude Cowork](https://support.claude.com/en/articles/13837440-use-plugins-in-claude-cowork)

## What's already in this repo

The plugin layout lives at the repo root, alongside the Python package:

```text
slop-mop/
├── .claude-plugin/
│   ├── plugin.json          # plugin manifest
│   └── marketplace.json     # marketplace listing (owns the slopmop entry)
├── skills/
│   └── slopmop/
│       └── SKILL.md         # public skill — triggers on remediation prompts
├── commands/
│   ├── sm-sail.md
│   ├── sm-swab.md
│   ├── sm-scour.md
│   └── sm-buff.md
├── assets/
│   └── claude-skill-demo.gif    # README demo
└── slopmop/                 # the actual Python CLI
```

Note: the existing `.claude/skills/slopmop/SKILL.md` and
`.claude/commands/sm-*.md` are the **project-local** Claude Code config for
people who clone this repo directly. They mirror the public plugin content
and are fine to leave in place. If they ever drift, the source of truth is
the root-level `skills/` and `commands/` (the plugin layout).

## Steps to publish

1. **Bump the version** in three places when you ship:
   - `pyproject.toml` → `[project] version`
   - `.claude-plugin/plugin.json` → `version`
   - `.claude-plugin/marketplace.json` → `plugins[0].version`

2. **Tag the release** the way you already do for PyPI. The marketplace
   resolves to the default branch unless users pin a tag.

3. **Smoke-test the install path** in a fresh Claude Code session:

   ```text
   /plugin marketplace add ScienceIsNeato/slop-mop
   /plugin install slopmop
   ```

   Then prompt Claude with *"sail this repo"* and confirm the skill fires
   and the slash commands appear under `/sm-*`.

4. **Promote it.** Pick the channels that match your audience:

   - **Anthropic-curated marketplace** (optional, secondary). Once the
     plugin is stable, submit it to Anthropic's official marketplace via
     the channel listed in the [marketplace docs](https://code.claude.com/docs/en/plugin-marketplaces).
     This is the highest-leverage discovery surface but is not required —
     your marketplace URL works on its own.
   - **Community lists.** Two community-maintained directories that
     occasionally surface new skills: `claudeskills.info` and
     `github.com/ComposioHQ/awesome-claude-skills`. Worth a PR to each —
     they're low effort but **not** the primary distribution path. Expect
     most installs to come from your own README + announcements.
   - **Where your users already are.** Reddit (r/ClaudeAI, r/aider),
     Hacker News (only if you have a strong story angle), the Anthropic
     Discord `#skills` channel, and any AI coding newsletters.

## Visibility

See [DOCS/VISIBILITY.md](DOCS/VISIBILITY.md) for the full plan. The short
version: PyPI download stats from `pypistats.org` and GitHub repo Insights
(clones, traffic, referrers) cover trend-line questions without writing any
telemetry code. Check both weekly.

## Submission checklist

- [ ] `plugin.json` and `marketplace.json` versions match `pyproject.toml`
- [ ] `skills/slopmop/SKILL.md` description still accurately describes
  trigger phrases
- [ ] Demo gif renders correctly on GitHub (open the README on
  github.com/ScienceIsNeato/slop-mop to confirm)
- [ ] Smoke test passes in a fresh Claude Code session
- [ ] Tag pushed, GitHub release notes published

## What not to do

- Don't ship an MCP server alongside this. Slop-mop is a CLI; the skill
  pattern (instruct Claude to invoke `sm`) is correct and lighter weight.
  Reserve MCP for cases where the tool needs to be reachable from non-Claude
  clients.
- Don't include user telemetry inside the skill itself. The plugin is just
  Markdown + JSON — there's nothing to phone home from. Keep visibility
  signals external (PyPI, GitHub).
