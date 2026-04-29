# Security Policy

## Supported Versions

slop-mop currently supports security fixes on a best-effort basis for:

- the latest published PyPI release
- `main` before the next release is cut

The broader compatibility and support contract lives in
[DOCS/COMPATIBILITY.md](DOCS/COMPATIBILITY.md).

Pre-1.0 releases do not have long-term support branches. If a fix is only
practical on the latest release line, older releases may be closed as
unsupported rather than backported.

## Reporting a Vulnerability

If you believe you found a real security issue in slop-mop itself:

1. Prefer GitHub's private vulnerability reporting flow for this repository.
2. If private reporting is unavailable, open a minimal public issue that says a
   security report is needed and avoid posting secrets, exploit strings, or full
   reproduction details in public.
3. If the report involves a leaked credential or token, rotate it before filing
   the report.

Include:

- the affected slop-mop version
- how slop-mop was installed (`pipx`, editable install, wheel, etc.)
- the platform and Python version
- a minimal reproduction or proof-of-impact
- whether the issue affects local execution, CI, published artifacts, or only a
  specific gate/tool integration

## Response Expectations

This is a single-maintainer project with no guaranteed response SLA, but
serious reports will be handled as quickly as practical.

The general policy is:

- acknowledge valid reports quickly when possible
- fix in `main` first
- publish a PyPI release when the fix is ready and verified
- document any breaking mitigation steps in the release notes

## What Belongs in a Public Issue Instead

Use a normal public issue for:

- false positives from security gates
- missing allowlists or noisy rules
- documentation gaps around `bandit`, `detect-secrets`, `semgrep`, or related
  tooling
- hardening ideas that are not active vulnerabilities
