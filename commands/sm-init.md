# /sm-init — configure slopmop for this repo

Run when you find a repo with `sm` installed but no `.sb_config.json` — or
after upgrading slopmop to pick up new gates.

1. Run `sm init --non-interactive` from the project root.
2. It auto-detects the stack (Python, JS, Go, Rust, iOS…) and writes a tuned
   `.sb_config.json`.
3. Then run `sm sail` — it reads the config and enters the loop.

Re-run after `pip install --upgrade slopmop` to pick up new gates, or after
adding a language to the repo.

`--non-interactive` skips prompts; use it in agent contexts. Without it, init
asks about test directories and coverage thresholds.

**Prerequisite:** `sm` must be installed. If `command not found`, suggest:
```bash
pipx install slopmop[all]
```
