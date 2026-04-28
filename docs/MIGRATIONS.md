# Upgrade Migrations

When a new slop-mop release changes **gate names**, **config structure**, or
**category assignments**, users with existing `.sb_config.json` files need an
automated migration path.  This document describes how to author one.

## Architecture

Migrations live in `slopmop/migrations/__init__.py` as entries in the
`_MIGRATIONS` list.  Each entry is an `UpgradeMigration` with:

| Field | Purpose |
|-------|---------|
| `key` | Human-readable identifier (shown in `sm upgrade` output) |
| `min_version` | Lowest version this migration applies from (inclusive) |
| `max_version` | Version this migration targets (exclusive lower, inclusive upper) |
| `apply` | `Callable[[Path], None]` — receives the project root |

### Execution model

`sm upgrade` installs the new package, then calls
`run_upgrade_migrations(project_root, old_version, new_version)`.  Migrations
run in **deterministic stepwise order**: sorted by `(max_version, min_version,
key)`, each advancing the "current version" cursor so later migrations see the
intermediate state.

A user upgrading from 0.10.0 → 0.13.0 in one jump will run all three
migrations in order: 0.11, 0.12, 0.13.

### Idempotency

Migrations should be **safe to re-run**.  If the config already has the new
structure, the migration should no-op.  `sm upgrade` backs up state before
running migrations, but a well-written migration never needs the backup.

## Authoring a migration

### 1. Write the migration function

```python
def _my_migration(project_root: Path) -> None:
    config_path = project_root / _CONFIG_FILE
    if not config_path.exists():
        return

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    changed = False

    # --- Your transformation logic here ---
    # Handle hierarchical format:  data["category"]["gates"]["old-name"]
    # Handle flat format:          data["category:old-name"]
    # Handle disabled_gates list:  data["disabled_gates"]
    # ---

    if changed:
        config_path.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )
```

**Important**: Handle both config formats.  Users may have the hierarchical
format (`{"laziness": {"gates": {"foo": {...}}}}`) or the legacy flat format
(`{"laziness:foo": {...}}`).  Check for and transform both.

### 2. Register the migration

Append to `_MIGRATIONS` in `slopmop/migrations/__init__.py`:

```python
_MIGRATIONS: List[UpgradeMigration] = [
    # ... existing migrations ...
    UpgradeMigration(
        key="my-descriptive-key",
        min_version="0.12.0",   # users upgrading FROM this version or later
        max_version="0.13.0",   # the release that introduces the breaking change
        apply=_my_migration,
    ),
]
```

### 3. Write tests

Add tests to `tests/unit/test_upgrade_migrations.py`:

- Hierarchical config format
- Flat config format
- `disabled_gates` list (if applicable)
- No config file (should no-op)
- Config without the old structure (should no-op)
- End-to-end via `run_upgrade_migrations()`

### 4. Regenerate the config template

If gate names changed, regenerate `.sb_config.json.template`:

```bash
python3 -m slopmop.utils.generate_base_config
```

### 5. Verify

The migration coverage check (`python3 scripts/check_migration_coverage.py`)
will fail if you change gate names in the template without updating
`slopmop/migrations/__init__.py`.

Run it locally, or run `sm scour` as part of the normal PR pass.

## Example: gate rename (0.11 → 0.12)

The first real migration renamed `myopia:source-duplication` into two gates:

- `laziness:repeated-code` (jscpd clone detection)
- `myopia:ambiguity-mines.py` (AST function-name duplication)

See `_rename_source_duplication()` in `slopmop/migrations/__init__.py` for the
reference implementation.
