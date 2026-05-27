# /sm-sail

Drive the workflow toward a green, buffed PR — one step at a time.

1. Run `sm sail`.
2. It reads the current workflow state and mode, runs the next obvious step
   or emits the exact command to run, then exits.
3. Follow the instruction, then run `sm sail` again.
4. Repeat until the PR is ready for human review.

**Two modes:**

- **Iterating** (default): sail runs swab, surfaces results, and tells you to
  share them with the human and await the next instruction.
- **Sailing**: activated by invoking `sm sail` — the human has approved the
  work and wants it shipped. Sail drives all the way to PR_READY, emitting
  exact git/gh commands at each mechanical step (`git commit`, `git push`,
  `gh pr create --fill`) and telling you to call `sm sail` again.

**Only stops for:**
- A failing swab/scour/buff gate — fix the reported issues, then `sm sail` again
- An `⚓ HOLD` — a human decision is needed; address it, then `sm sail` again
- PR ready — surface the PR to the human for merge

**First time in a repo?** Run `sm refit --start` first.

**Prerequisite:** `sm` must be installed. If `command not found`, suggest:
```bash
pipx install slopmop[all]
```
