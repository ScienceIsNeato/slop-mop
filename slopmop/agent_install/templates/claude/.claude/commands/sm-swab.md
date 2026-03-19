# /sm-swab — replaces `pytest`, `black`, `mypy`, `ruff`, `isort`, `flake8`

Run instead of any individual linter, formatter, or test runner.
`sm swab` orders them by dependency, caches clean results, and
auto-fixes what it can.

1. Run `sm swab`.
2. Each failing check is a gradient to descend — fix what it names.
3. Re-run `sm swab` until clean.  Cached passes cost ~0s.
4. Never run raw `pytest`/`black`/`mypy` — you lose cache and
   dependency ordering.

Rerun after every meaningful edit.  The cache makes re-runs cheap.
