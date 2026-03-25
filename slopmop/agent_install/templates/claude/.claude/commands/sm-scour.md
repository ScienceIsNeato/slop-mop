# /sm-scour — comprehensive pre-PR sweep

Run before opening or updating a PR.  Scour executes every gate —
everything swab runs plus PR-level checks like diff coverage and
unresolved review threads.

Examples of what scour catches:
- Security issues (`bandit`, `detect-secrets`)
- Coverage regression on changed lines
- Unresolved review threads (the `myopia:ignored-feedback` gate)
- Complex or duplicated code that slipped past fast-feedback
- Formatting or type-checking drift across the full codebase

Workflow:
1. Run `sm scour`.
2. Fix what it names — these are things that compound if shipped.
3. Only open or update a PR when `sm scour` reports clean.

Do not push while scour is red.
