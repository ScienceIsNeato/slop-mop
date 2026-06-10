# Slop-Mop Machine Interface

> **Status:** implemented. Every JSON-emitting verb wraps its output in
> the `slopmop/v3` envelope, each carries a published data schema, and a
> CI conformance test validates real output against those schemas.
> **Schema version of record:** `slopmop/v3` — see
> [Schema versioning: the v3 envelope](#schema-versioning-the-v3-envelope).

Slop-mop is driven far more often by agents than by humans typing in a
terminal.  That path used to work unevenly: validation verbs spoke one
JSON convention, `status` spoke a different one, and the remaining verbs
mostly emitted prose an agent had to scrape.  This document specifies the
single, versioned machine interface that every verb now shares, so an
agent can drive the whole tool by contract instead of by screen-reading.

---

## Design goal: format predictability

The single test this interface must pass:

> An agent about to take a change from edit to merged will touch many
> `sm` verbs. **Before running a single one, can it know the exact
> format of every response — regardless of content?**

The answer must be **yes**, with one honest distinction:

- **The envelope is byte-shape identical across every verb.** `{schema,
  command, status, exit_code, data, next_steps, diagnostics}` never
  varies. This is a flat guarantee.
- **The `data` block legitimately differs per verb.** `swab`'s gate
  results are not `doctor`'s env checks; forcing them into one shape
  would make them lie. So "is every response identical?" is correctly
  *no* — and that is not the question that matters.

What makes the interface first-class is that the `data` shape for each
verb is **declared and fetchable ahead of time**, so the agent's
complete knowledge is `envelope schema + N per-verb data schemas`, all
obtainable before touching any command. Content varies; shape is known
in advance. Three mechanisms deliver this (see
[Formal schema & self-description](#formal-schema--self-description)):
a published schema, self-description without execution, and a
conformance guarantee in CI.

The old `--json` / `--porcelain` failed this test on four counts the user
named directly — each of which the v3 interface now answers:

- **No schema defined** — the shape was implicit in the emitter code.
  *Now: a published JSON Schema per verb.*
- **Agents can't know the format before the fact** — no way to ask "what
  will this return?" short of running it. *Now: `sm schema <verb>` /
  `<verb> --describe`.*
- **No guarantee of output details** — nothing asserted the emitter kept
  emitting what it emitted yesterday. *Now: the CI conformance test.*
- **Different outputs for different commands** — no shared frame. *Now:
  the invariant envelope.*

---

## The problem this solved: two conventions used to disagree

Before the v3 envelope, there were two machine-output conventions in the
tree, and they conflicted.

| | `swab` / `scour` | `status` |
|---|---|---|
| Flag | `--json` (explicit opt-in) | `--json-output`, **and** auto-switches to JSON when stdout is not a TTY |
| Shape | `{summary, results, schema: "slopmop/v1", level, …}` | ad-hoc `{project_root, gates, workflow, ci, …}` — **no `schema`, no envelope** |
| Terse modes | `--porcelain`, `--sarif`, `--json-file` | none |

Consequences an agent hit in practice:

- Piping `sm swab` yielded human prose unless the agent knew to pass
  `--json`; piping `sm status` silently yielded JSON.  Same tool, opposite
  defaults.
- The two JSON shapes didn't share a frame, and only one carried a schema
  version — so a consumer couldn't write one parser.
- `sail`, `doctor`, `refit`, `buff`, `config`, and `audit` were largely
  prose-only.  The verb whose entire job is "what do I do next" (`sail`)
  had no structured answer.

The architecture to fix this **already existed in the codebase** — it was
just applied in two places out of fourteen:

- `reporting/adapters.py` formalises a "compute in `RunReport`, format in
  the adapter" split for validation.
- `cli/status.py` independently grew the same shape: `_gather_*()`
  functions return pure data dicts, `_print_*()` functions render them,
  and `_build_status_dict()` serialises.

The design below was **"make every verb do what `validate` and `status`
already half-did, against one shared envelope"** — and that is what
shipped.

---

## 1. One envelope, every verb

Every verb's machine output is wrapped in a single versioned frame:

```jsonc
{
  "schema": "slopmop/v3",
  "command": "swab",              // the verb that ran
  "status": "fail",               // ok | fail | error | info
  "exit_code": 1,                 // mirrors the process exit code, so a
                                  //   consumer reading captured stdout
                                  //   need not also inspect $?
  "data": { /* verb-specific payload — see §4 */ },
  "next_steps": [
    { "action": "inspect", "command": "…", "reason": "first-to-fix log" }
  ],
  "diagnostics": [                // execution-context warnings, NOT findings
    { "code": "cached_results_present", "level": "warn",
      "message": "…", "suggested_command": "sm swab --no-cache" }
  ]
}
```

Rules:

- **`data` is the only verb-specific part.** The four sibling keys
  (`schema`, `command`, `status`, `exit_code`, `next_steps`,
  `diagnostics`) are identical across every verb. One parser, every
  command.
- **Validation's current top level moves under `data` unchanged.**
  `summary`, `results`, `passed_gates`, `first_to_fix`, `cache`,
  `baseline_filter` keep their exact keys — they are simply nested.
- **`runtime_warnings` generalises to top-level `diagnostics`.** Today
  only validation emits runtime warnings (cache present, timeout budget
  skipped). The same envelope slot lets *every* verb surface "gh not
  installed", "no PR detected", "stale baseline" identically.
- **`next_steps` become structured objects**, not bare strings. An agent
  acts on `command` without parsing English. `action` is a small closed
  vocabulary (`inspect`, `rerun`, `fix`, `advance`, `install`, …).

### `status` values

| `status` | meaning | typical `exit_code` |
|---|---|---|
| `ok` | the verb's success condition held (gates passed, no issues) | 0 |
| `fail` | the verb ran and found blocking problems (gate failures) | 1 |
| `error` | the verb could not complete (missing dep, bad args, crash) | 1–2 |
| `info` | observatory verb that has no pass/fail (`status`, `capabilities`) | 0 |

---

## 2. Flag convention

Machine output is requested with a plain `--json` boolean on the
validation and report verbs (`swab`, `scour`, `status`, …). `swab` and
`scour` also keep their `--porcelain`, `--sarif`, and `--json-file`
booleans. The discovery commands need no flag at all:

- **`sm schema`, `sm capabilities`, and `<verb> --describe` always emit
  JSON.** They exist only to be read by machines, so there is no human
  mode to opt out of.
- **`status` auto-switches to JSON off a TTY.** Pipe `sm status` and you
  get the envelope without passing a flag; the other verbs keep `--json`
  explicit.

A unified `--format {human,json,porcelain,sarif}` option that would
collapse those booleans, plus a `SLOPMOP_FORMAT` override and a universal
non-TTY auto-switch, was scoped during design but **not built** — the
existing per-mode booleans proved sufficient for the agent and skill
consumers that drive the tool. If a single format selector is ever
wanted, this is where the enum lands; the booleans would become aliases.

---

## 3. Discovery: `sm capabilities`

The biggest current gap is that an agent cannot enumerate what slop-mop
*can do* without scraping `sm help <gate>` prose. Add a static,
side-effect-free catalog endpoint:

```
sm capabilities
```

```jsonc
{
  "schema": "slopmop/v3",
  "command": "capabilities",
  "status": "info",
  "exit_code": 0,
  "data": {
    "version": "2.3.2",
    "verbs": [
      { "name": "swab", "summary": "…", "level": "core",
        "formats": ["human", "json", "porcelain", "sarif"],
        "exit_codes": { "0": "all passed", "1": "failure/error", "2": "bad args" },
        "data_schema": { "$ref": "https://slopmop.dev/schemas/v3/data/swab.json" } }
    ],
    "gates": [
      { "name": "laziness:todo_left_behind", "category": "laziness",
        "level": "swab", "role": "diagnostic",
        "description": "…", "why_it_matters": "…",
        "applicable_when": "…" }
    ],
    "config_keys": [ /* the .sb_config.json / [tool.slopmop] schema */ ]
  }
}
```

Every field here already lives on the check classes — `role`,
`why_it_matters`, `is_applicable`, `GateCategory`, `GateLevel` are all
read today when `status` builds its inventory. This endpoint serialises
the registry instead of formatting it for human eyes. An agent reads it
**once** to learn the entire surface, then drives every verb by contract.

---

## Formal schema & self-description

This is what turns "consistent JSON" into a contract, and what makes the
[predictability test](#design-goal-format-predictability) pass. Three
pieces:

### 1. A published, versioned schema

The envelope is a real JSON Schema document (draft 2020-12) checked into
the repo with a versioned `$id`:

```
schemas/v3/envelope.json        # the invariant outer frame
schemas/v3/data/swab.json       # per-verb data payloads, one file each
schemas/v3/data/doctor.json
schemas/v3/data/…
```

A verb's *full* output schema is the envelope with its `data` slot
replaced by that verb's data-schema (`allOf` / `$ref` composition) — so
"the outer frame is invariant" is enforced structurally, not by
convention. The `$id` carries `slopmop/v3`; an agent asserts on it to
detect drift.

### 2. Self-description without execution

An agent must be able to learn a format *without running the command*:

```
sm schema                       # → the envelope JSON Schema
sm schema <verb>                # → that verb's full output schema
sm <verb> --describe            # → that verb's full output schema; does NOT run the verb
sm capabilities                 # → every verb + a $ref to each data-schema (see §3)
```

`sm <verb> --describe` is the literal mechanism for "know the format
before the fact": it is a dry call that returns the schema and exits,
running none of the verb's work.

### 3. A conformance guarantee

A schema nobody enforces is just documentation. A CI test validates
**every verb's real output against its declared schema**, for both
passing and failing runs:

```
for each verb:
    run it, capture its JSON output
    assert output validates against schema(verb)
```

This is what answers "no guarantee of output details": the guarantee is
the test, not the prose. If a verb's emitter drifts from its schema, CI
fails. Optionally, a `SLOPMOP_VALIDATE_OUTPUT=1` debug mode runs the same
assertion at runtime for local development.

Together: an agent reads `sm schema` + `sm capabilities` once, and now
knows the exact shape of every response from every command — content
aside — with CI guaranteeing they won't diverge from it.

---

## 4. Per-verb `data` payloads

The envelope is the easy part; the work is specifying each verb's
`data`. Priority order is by agent value, not implementation order.

1. **`status`** — already returns a dict; add the envelope + `schema`.
   Nearly free; serves as the migration proof.
2. **`sail`** — `{current_state, next_action, ran_verb, result}`. `sail`
   *is* the "what next" verb; an agent driving the loop needs this
   structured above all else.
3. **`doctor`** — `{checks: [{name, ok, detail, fix}], all_ok}`. Pure
   diagnostics; structures naturally.
4. **`buff`** — `{pr, ci: {passed, failed, pending, failures},
   review_threads: […]}`. `status._gather_ci_data` is the seed.
5. **`refit`** — workflow phase + iteration plan as data.
6. **`config` / `audit`** — round-trippable config dict / health snapshot.

---

## Schema versioning: the v3 envelope

**Decision (shipped):** the schema of record is `slopmop/v3`. Validation's
former top-level fields (`summary`, `results`, `passed_gates`,
`first_to_fix`, …) now live under `data`, and every JSON-emitting verb
wraps its payload in the same envelope. There was no dual-emit window —
`--json` produces the v3 envelope directly.

Rationale: the machine surface is consumed almost entirely by slop-mop's
own skills and agents, which are versioned alongside the tool. Carrying a
compat shim for the old flat shapes would have meant two code paths and
two test matrices to serve consumers that move in lockstep with the
release anyway. A clean cut was cheaper than a deprecation window nobody
benefits from.

The `schema` field is how a consumer detects which shape it holds; v3
consumers assert on it (`"slopmop/v3"`) to catch drift. The envelope
frame is enforced structurally by the published JSON Schema, not by
convention — see [Formal schema & self-description](#formal-schema--self-description).

---

## Rollout phases

All phases below shipped. They are kept as a record of how the interface
was built.

1. **Envelope + schema plumbing** in `reporting/` — `build_envelope`, the
   `schemas/v3/envelope.json` document, the `sm schema` verb, and the
   conformance test harness (initially with only validation conforming).
   *(Done.)*
2. **`sm capabilities` + per-verb `--describe`** — serialise the registry
   and wire each verb's `data_schema` `$ref`. *(Done.)*
3. **Migrate `status` → envelope** — `schemas/v3/data/status.json` plus a
   conformance-test entry. Proved the pattern end to end. *(Done.)*
4. **Wire `swab` / `scour` / `doctor` / `captain` / `barnacle` / `buff` /
   `refit` / `audit`** — each verb shipped a data layer, its
   `schemas/v3/data/<verb>.json`, and a conformance-test entry. A verb was
   not "done" until CI validated its real output against its schema.
   *(Done.)*
5. **Cleanup** — the dead `slopmop/v2` schema marker and the unused
   `RunReport.schema_version` field were removed once every verb emitted
   the v3 envelope. The unified `--format` enum and old-flag aliases
   described in earlier drafts of §2 were never built; the per-mode
   booleans were kept as-is. *(Done.)*
