# Compatibility and Support

slop-mop is still pre-1.0. The project is trying to be disciplined about
compatibility, but it is not claiming a frozen surface yet.

This document is the public contract for what users should expect from releases
before 1.0.0.

## Support Scope

The actively supported surfaces are:

- the latest published PyPI release
- `main`, when validating an upcoming release or an unreleased fix

Pre-1.0 releases do not have long-term support branches. Fixes land in `main`
first. Older releases may be closed as unsupported instead of backported.

## Versioning Expectations Before 1.0

slop-mop uses semantic-looking versions, but pre-1.0 rules are intentionally
stricter than "anything goes" and looser than a true 1.x contract.

### Patch releases

Patch releases should avoid intentional breakage in:

- the core CLI verbs (`sm init`, `sm swab`, `sm scour`, `sm buff`, `sm sail`,
  `sm upgrade`)
- existing config keys and gate names
- release/install behavior from supported package entry points

Bug fixes, dependency bumps, and additive flags are fine. Intentional breakage
in a patch release needs a very strong reason and should be called out
explicitly in release notes.

### Minor releases

Minor releases may still evolve:

- gate names
- config structure
- machine-readable output formats
- agent-install templates and workflow scaffolding

When that happens:

- ship an automated `sm upgrade` migration when the change is automatable
- update [DOCS/MIGRATIONS.md](MIGRATIONS.md) when migration authoring rules
  change
- call out the change in release notes
- document any manual follow-up when automation is not practical

## Config and Output Compatibility

Before 1.0.0:

- committed config templates may change between minor releases
- existing user configs should keep working via migration whenever practical
- JSON and SARIF output should be treated as evolving integration surfaces

If a change intentionally breaks an integration surface, the release notes
should say so plainly rather than hiding it inside a generic changelog entry.

## Platform and Tooling Support

slop-mop is published as a Python CLI and is expected to work from the
supported package entry points:

- `pipx install slopmop[all]`
- `pip install slopmop[all]`
- editable installs for contributors

The package metadata currently declares Python `3.10` through `3.14`.

Continuous verification is strongest on:

- Linux
- Windows
- GitHub Actions-based CI usage

macOS and other environments are intended to work, but they are not currently
release-blocking CI surfaces. Treat them as best-effort until the CI matrix says
otherwise.

## Deprecation Policy

Pre-1.0 does not guarantee a long deprecation window, but the project should
still avoid surprise removals.

The expectation is:

- additive changes can land immediately
- renames/removals should come with a migration when possible
- release notes should call out behavior changes that require user action

## 1.0 Trigger

When slop-mop reaches 1.0.0, this document should be tightened into a stable
1.x compatibility contract with:

- explicit backward-compatibility promises
- a documented support window
- a clearer policy for deprecations and removals
