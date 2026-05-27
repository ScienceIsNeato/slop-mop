# /sm-sail

Drive the workflow toward a green, buffed PR — one step at a time.

1. Run `sm sail`.
2. It reads the current workflow state, runs the next obvious step or emits
   the exact command to run, then exits.
3. Follow the instruction, then run `sm sail` again.
4. Repeat until the PR is ready for human review.

**What sail does:** `sm sail` activates SAILING mode on entry and drives the
workflow to PR_READY. At each step it emits the exact command to run
(`git add -A && git commit -m '...'`, `git push`, `gh pr create --fill`)
then tells you to call `sm sail` again.

**What `sm swab` does:** When run directly (not via sail), `sm swab` surfaces
results and tells you to commit, share them with the human, and await the next
instruction — the tacking-mode guidance lives there.

**Only stops for:**
- A failing swab/scour/buff gate — fix the reported issues, then `sm sail` again
- An `⚓ HOLD` — a human decision is needed; address it, then `sm sail` again
- PR ready — surface the PR to the human for merge

**First time in a repo?** Run `sm refit --start` first.

**Prerequisite:** `sm` must be installed. If `command not found`, suggest:
```bash
pipx install slopmop[all]
```
