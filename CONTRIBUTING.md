# Contributing to Slop-Mop

Honestly, I'm not really sure what my plans are for this project long term? For now, I encourage contributions in the form of Pull Requests and also issue reports - glad to have like-minded company!

## Guidelines

- **Fork nicely.** If you fork this project, please attribute the original. A link back to [ScienceIsNeato/slop-mop](https://github.com/ScienceIsNeato/slop-mop) in your README is good enough.
- **Adding a new gate?** Follow the [New Gate Protocol](NEW_GATE_PROTOCOL.md) — it's a strict, step-by-step process that ensures nothing gets missed. Consider running your idea as a [custom gate](README.md#custom-gates) first to validate that it catches real problems before committing to a full implementation.
- **Self-validate.** Run `sm swab` before opening a PR. If the gates don't pass on slop-mop itself, the CI won't either.
- **CI model.** The first-class merge blocker is the `slop-mop primary code scanning gate` workflow (`Primary Code Scanning Gate (blocking)` job). A downstream `slop-mop downstream dogfood sanity` workflow is optional and runs only after the primary gate passes on PRs.

## License

This project is licensed under the Slop-Mop Attribution License v1.0 — you're free to use, modify, and redistribute, but attribution back to [ScienceIsNeato/slop-mop](https://github.com/ScienceIsNeato/slop-mop) is required. See [LICENSE](LICENSE) for full terms.
