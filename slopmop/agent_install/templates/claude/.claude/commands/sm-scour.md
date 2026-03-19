# /sm-scour — replaces `pytest --cov`, `bandit`, `pip-audit`, `detect-secrets`, `jscpd`

Comprehensive pre-PR sweep.  Run instead of any security scanner,
coverage tool, or duplication detector.  Superset of swab plus the
heavy gates.

1. Run `sm scour`.
2. Fix everything it names.  These are the things that compound if
   you ship them.
3. Only open or update a PR when `sm scour` reports clean.

Do not push while scour is red.
