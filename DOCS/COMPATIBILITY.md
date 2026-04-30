# Compatibility and Support

Starting with 1.0.0, slop-mop treats its documented CLI, config, and release
surfaces as stable. The project can still evolve, but user-visible breakage
needs a migration path or a clearly documented major release boundary.

## Support Scope

The actively supported surfaces are:

- the latest published PyPI release
- `main`, when validating an upcoming release or an unreleased fix

The latest minor release receives active fixes. Fixes land in `main` first;
older release lines may be closed as unsupported instead of backported unless a
security or severe data-loss issue warrants a targeted patch.

## Versioning Expectations

slop-mop follows semantic versioning for the documented public surface.

### Patch releases

Patch releases should avoid intentional breakage in:

- the core CLI verbs (`sm init`, `sm swab`, `sm scour`, `sm buff`, `sm sail`,
  `sm upgrade`)
- existing config keys and gate names
- release/install behavior from supported package entry points

Bug fixes, dependency bumps, and additive flags are fine. Intentional breakage
in a patch release needs a very strong reason, a migration or compatibility
shim when practical, and explicit release notes.

### Minor releases

Minor releases may add or deprecate:

- gate names
- config structure
- machine-readable output formats
- agent-install templates and workflow scaffolding

When a minor release changes behavior:

- ship an automated `sm upgrade` migration when the change is automatable
- update [DOCS/MIGRATIONS.md](MIGRATIONS.md) when migration authoring rules
  change
- call out the change in release notes
- document any manual follow-up when automation is not practical

## Config and Output Compatibility

For 1.x releases:

- committed config templates may gain new optional settings between minor
  releases
- existing user configs should keep working via migration whenever practical
- JSON, SARIF, and porcelain output should avoid incompatible changes inside a
  minor release line

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

The project should avoid surprise removals.

The expectation is:

- additive changes can land immediately
- renames/removals should come with a migration when possible
- release notes should call out behavior changes that require user action
