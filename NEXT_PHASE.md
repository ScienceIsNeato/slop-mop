# Next Phase: Foundation, Diagnosis, and the Unified Voice

## Progress Since Draft

This document started as a forward-looking design memo. Parts of it are now
already shipped in the current tree, so treat it as a mixed document: some
items below are still roadmap, others are historical design context.

Already landed relative to this draft:
- The two-tier architecture vocabulary is in the code: `BaseCheck.role` defaults
  to diagnostic, foundation-vs-diagnostic badges surface in status/output, and
  tests cover the distinction.
- The unified output adapter direction is largely implemented: `RunReport` is
  the shared enriched representation feeding console, JSON, and SARIF output.
- Remediation-aware output now exists in user-facing flows: remediation ordering,
  explicit `first_to_fix` guidance, and aligned verify commands show up in
  `swab`, `scour`, and `buff` output.

Still genuinely open:
- Work Item 1b: smart init / existing-tool discovery and delegation.
- Work Item 2: deeper didactic output so gates explain not just what failed,
  but why it matters and exactly what to do in a fully structured way.
- Remaining gaps in Work Item 3 are mostly about enriching the structured
  diagnosis protocol, not building the adapter layer from scratch.

## Philosophical Context

Slop-mop exists because LLMs were trained to close tickets, not to steward codebases. The tool provides "Tyrion in a box" — automated strategic oversight for AI-generated code. It works. But a recurring criticism from models during design sessions reveals a legitimate architectural gap:

> "These are just linters with flaw names. Pylint exists. Mypy exists. You're rebranding `pip install black` as catching 'laziness.'"

There's a kernel of truth here, and it points to something real: **slop-mop currently conflates two fundamentally different kinds of work.**

---

## The Two Kinds of Checks

### Tier 1: Foundation Checks (the "Bedrock")

These ensure the ground beneath you is solid. They answer binary questions:
- Does the code compile?
- Does it pass lint?
- Do the tests run?
- Are types annotated?

These aren't novel. They're prerequisites. The critic is right that `black` and `mypy` have existed for years — but the critic misses *why they're here*. Without deterministic, repeatable proof that the code is structurally sound, the higher-order checks produce noise. You can't detect bogus tests if no test runner is configured. You can't measure coverage gaps if coverage isn't collected. Foundation checks are the floor that everything else stands on.

**The insight the critic misses:** The value isn't that slop-mop *invented* linting. The value is that slop-mop *guarantees* linting happens — identically, every time, regardless of whether the target repo has its own pylint config, whether the model "forgot" to run tests, whether CI is configured. The tool wraps the user's existing infrastructure (or provides a fallback) and makes it deterministic. The flaw labeling isn't rebranding — it's *indexing by consequence*. We don't care that `black` is a formatter. We care that unformatted code is a symptom of laziness, and that laziness is the flaw category that tells an LLM *why* its code was rejected, not just *that* it was rejected.

### Tier 2: Diagnostic Checks (the "Insight")

These are what make slop-mop something other than a shell script calling `pylint && pytest`. They answer *judgment* questions:
- Are these tests actually testing anything, or are they theater? (`bogus-tests`)
- Did someone quietly weaken a gate threshold? (`gate-dodging`)
- Is this function doing too many things? (`code-sprawl`, `complexity-creep`)
- Did the code just duplicate logic that already exists? (`source-duplication`)
- Are there debugger breakpoints left in production code? (`debugger-artifacts`)
- Did the model ignore PR review feedback? (`ignored-feedback`)

These checks have no equivalent in the traditional tooling ecosystem. They exist because LLMs exhibit specific, predictable failure modes that conventional static analysis was never designed to detect. A human developer rarely commits `console.log` breakpoints to production — but an LLM does it constantly. A human developer rarely writes `def test_add(): pass` — but an LLM will generate empty test bodies to satisfy a "write tests" instruction. These are *behavioral* checks, not *structural* checks.

---

## Work Item 1: Formalize the Two-Tier Architecture

Status: mostly shipped, except Work Item 1b.

### Current State

All checks inherit from `BaseCheck` and are organized by `Flaw` (overconfidence, deceptiveness, laziness, myopia) and `GateCategory` (which mirrors `Flaw` 1:1 plus `GENERAL`). There is no architectural signal distinguishing "this wraps `black`" from "this does novel AST analysis for empty test bodies." The `ToolContext` enum (`PURE`, `SM_TOOL`, `PROJECT`, `NODE`) describes *how* a tool is resolved, not *what kind of work* it does.

### Proposed Change

Introduce a `CheckRole` (or `CheckTier`, `CheckKind` — name TBD) classification:

```python
class CheckRole(Enum):
    """Whether a check provides foundational hygiene or diagnostic insight.

    FOUNDATION checks wrap standard development tooling (linters, type
    checkers, test runners, formatters).  They answer binary, structural
    questions: does it compile, does it lint, do tests pass.  They are
    prerequisites — without them, diagnostic checks produce noise.

    DIAGNOSTIC checks detect AI-specific failure modes that conventional
    tools miss.  They answer judgment questions: are the tests real, did
    someone weaken a threshold, is this code duplicated from elsewhere.
    They are the reason slop-mop exists as a distinct tool rather than a
    shell script calling pylint && pytest.
    """

    FOUNDATION = "foundation"
    DIAGNOSTIC = "diagnostic"
```

Every `BaseCheck` subclass declares a `role: ClassVar[CheckRole]`. The classification is:

| Check | Role | Rationale |
|-------|------|-----------|
| `sloppy-formatting.py` | FOUNDATION | Wraps black/isort/flake8 |
| `sloppy-formatting.js` | FOUNDATION | Wraps prettier/eslint |
| `missing-annotations.py` | FOUNDATION | Wraps mypy |
| `type-blindness.py` | FOUNDATION | Wraps pyright |
| `type-blindness.js` | FOUNDATION | Wraps tsc |
| `untested-code.py` | FOUNDATION | Wraps pytest |
| `untested-code.js` | FOUNDATION | Wraps jest |
| `coverage-gaps.py` | FOUNDATION | Wraps pytest-cov + diff-cover |
| `coverage-gaps.js` | FOUNDATION | Wraps jest --coverage |
| `hand-wavy-tests.js` | FOUNDATION | Wraps jest |
| `sloppy-frontend.js` | FOUNDATION | Wraps eslint react plugin |
| `dead-code.py` | FOUNDATION | Wraps vulture |
| `complexity-creep.py` | FOUNDATION | Wraps radon |
| `vulnerability-blindness.py` | FOUNDATION | Wraps bandit/pip-audit |
| `dependency-risk.py` | FOUNDATION | Wraps pip-audit |
| `broken-templates.py` | FOUNDATION | Wraps jinja2 compiler |
| `bogus-tests.py` | DIAGNOSTIC | AST analysis for test theater |
| `bogus-tests.js` | DIAGNOSTIC | AST analysis for test theater |
| `debugger-artifacts` | DIAGNOSTIC | Pattern scan for leftover debug code |
| `gate-dodging` | DIAGNOSTIC | Git-diff analysis of config weakening |
| `code-sprawl` | DIAGNOSTIC | AST function-length analysis |
| `silenced-gates` | DIAGNOSTIC | Config audit for disabled gates |
| `source-duplication` | DIAGNOSTIC | Cross-file similarity detection |
| `string-duplication.py` | DIAGNOSTIC | Cross-file string extraction |
| `ignored-feedback` | DIAGNOSTIC | PR comment resolution tracking |
| `just-this-once.py` | DIAGNOSTIC | TODO/FIXME/hack pattern detection |
| `stale-docs` (if exists) | DIAGNOSTIC | Doc freshness analysis |

### Architectural Impact

1. **`BaseCheck`** gets `role: ClassVar[CheckRole] = CheckRole.DIAGNOSTIC` (safe default — you prove you're foundational, not the other way around).

2. **Display**: Foundation checks can be visually grouped or badged differently in console output (e.g., `🧱` prefix or a grouped section header). SARIF output can tag the rule with `properties.role`.

3. **`sm status`**: Dashboard shows "Foundation coverage" (how many structural hygiene categories have a passing tool) separately from "Diagnostic findings."

4. **`sm init` discovery** (see Work Item 1b): Foundation checks are the ones that can be delegated to or discovered from existing project tooling.

### Work Item 1b: Smart Init and Tool Discovery

Status: still open.

The original version of this plan pushed too much responsibility into `sm init`
itself. That was the wrong cut. `sm init` should not become a giant central
scanner that knows where every possible tool config might live.

Canonical direction:

1. **Gate-owned init hooks**: the gate primitive exposes an init-time hook that
  returns gate-specific config defaults discovered from the repo.
2. **Gate-owned config fields**: if a gate needs a native config path or
  baseline file, that field belongs in the gate's own `config_schema`, not in
  the universal base schema.
3. **Thin init orchestrator**: `sm init` generates the template config,
  delegates discovery to gates that implement the hook, and merges discovered
  defaults without hardcoding per-gate file hunts.

That means the work here is:

1. **Move config-file discovery into gates**:
  - A security gate can look for `.secrets.baseline`, `.bandit`, or
    `[tool.bandit]` in `pyproject.toml` because it knows those files mean
    something.
  - A formatting gate can look for `.prettierrc` or `pyproject.toml [tool.black]`
    if and when that discovery is useful.
  - Gates without a meaningful native config concept implement nothing.

2. **Teach `sm init` to delegate, not inspect broadly**:
  - Iterate the enabled gates.
  - Ask each gate for init-time config overrides.
  - Apply discovered values as defaults, not hard overrides.

3. **Keep project-type detection coarse**:
  - `detect_project_type()` should stay about repo-wide facts (Python present,
    JS present, test dirs, missing tools), not gate-specific config trivia.

4. **Only after that, consider richer delegation metadata**:
  - Whether a gate is using project-managed tooling vs slop-mop-managed tooling
    can still be modeled later.
  - But that decision should be informed by gate-owned discovery, not by a
    monolithic `sm init` decision tree.

This moves slop-mop from "batteries-included heavy install" to "smart, adaptive, efficient overlay." The eventual `sm doctor` verb (out of scope here, but worth noting in the architecture) will extend this to runtime dependency health checks.

**Config shape** (strawman):

```json
{
  "gates": {
    "laziness:sloppy-formatting.py": {
      "enabled": true,
      "provider": "project",
      "provider_config": "pyproject.toml [tool.black]",
      "note": "Delegating to project's existing black+isort config"
    }
  }
}
```

`provider` values:
- `"slopmop"` — slop-mop manages the tool (default, current behavior)
- `"project"` — delegate to the project's existing tooling
- `"custom"` — user-defined command (via custom gates mechanism)

---

## Work Item 2: Didactic, Prescriptive Output

Status: partially shipped.

What is already present:
- Per-finding `fix_strategy` exists in `Finding`.
- `RunReport` and adapters already surface a single verify command and explicit
  `first_to_fix` guidance.
- The first structured-output slice is now live for Python type gates:
  `CheckResult` can carry gate-level `why_it_matters`, console output renders a
  compact Diagnosis -> Prescription -> Verification block when that structure is
  present, and the mypy/pyright gates now emit per-finding remediation text.

What remains is the stronger version proposed here: a consistent
Diagnosis → Prescription → Verification protocol across gates, rather than
today's mix of gate-level suggestions and selectively structured findings.

### The Problem

Current gate output often looks like:

```
❌ overconfidence:missing-annotations.py — 3 type error(s) found
   3 type error(s):
     slopmop/checks/base.py:42: Argument 1 to "foo" has incompatible type  [arg-type]
     slopmop/reporting/sarif.py:88: Missing return type annotation  [no-untyped-def]
     ...
   💡 Fix type annotations or add # type: ignore comments.
```

This tells the model *what's wrong* but not *exactly what to do*. The model has to:
1. Parse the error format
2. Figure out which file to open
3. Decide what the fix is
4. Know how to verify the fix worked

Every ambiguity is a chance for the model to hallucinate a fix, get it wrong, and waste a cycle.

### The Goal

Every gate output should follow a **Diagnosis → Prescription → Verification** structure:

```
❌ overconfidence:missing-annotations.py — 3 type errors

WHAT'S BROKEN:
  slopmop/checks/base.py:42 — Argument 1 to "foo" has incompatible type "str", expected "int"
  slopmop/reporting/sarif.py:88 — Function "generate" is missing a return type annotation
  slopmop/reporting/sarif.py:102 — Function "_fingerprint" is missing a return type annotation

WHY IT MATTERS:
  Missing or incorrect type annotations prevent type checkers from catching bugs
  at development time. Without them, errors surface at runtime instead of during
  static analysis — which means they surface in production.

EXACTLY WHAT TO DO:
  1. In slopmop/checks/base.py:42, change the argument type from str to int,
     or update the function signature to accept str if that's the intended type.
  2. In slopmop/reporting/sarif.py:88, add a return type annotation to "generate":
         def generate(self, summary: ExecutionSummary) -> Dict[str, Any]:
  3. In slopmop/reporting/sarif.py:102, add a return type annotation to "_fingerprint":
         def _fingerprint(self, ...) -> str:

VERIFY THE FIX:
  sm swab -g overconfidence:missing-annotations.py
```

### Design Principles for Output

1. **No questions left unanswered.** After reading gate output, an LLM should be able to produce a fix without asking for clarification.

2. **Specific over general.** "Fix type annotations" → "Add `-> Dict[str, Any]` to `generate()` in `sarif.py:88`."

3. **File paths are always relative to project root.** No absolute paths. No ambiguity about which file.

4. **Every output ends with a verification command.** The model knows exactly how to check if the fix worked.

5. **False positives are poison.** If a gate can't be sure something is wrong, it should WARN, not FAIL. A single false positive teaches the model to distrust the tool, and a distrusted tool is worse than no tool — it becomes noise that the model learns to work around rather than fix.

### Implementation Approach

This is NOT a rewrite of every check's `run()` method. It's a **structured output protocol** that checks opt into:

```python
@dataclass
class Diagnosis:
    """A single actionable issue found by a gate."""
    location: str          # "path/to/file.py:42"
    what: str              # "Function 'foo' is missing return type"
    why: str               # "Missing types prevent static analysis"
    fix: str               # "Add -> Dict[str, Any] to line 42"
    
@dataclass  
class GateOutput:
    """Structured output from a gate run."""
    diagnoses: List[Diagnosis]
    verify_command: str    # "sm swab -g overconfidence:missing-annotations.py"
    context: str           # Why this category of issue matters (shown once)
```

The `Finding` dataclass already carries `file`, `line`, `message`, and `level`. The enhancement is adding `fix_instruction` (per-finding prescriptive text) and `why` (per-gate context). The rendering layer then formats these into the Diagnosis → Prescription → Verification structure regardless of output target (console, JSON, SARIF).

This ties directly into Work Item 3:

---

## Work Item 3: Unified Output Adapter Layer

Status: largely shipped.

The core architectural move proposed here already happened: `RunReport` sits
between execution summary and output adapters, and console/JSON/SARIF now share
that enriched representation instead of independently re-deriving state.

The remaining value in this section is as design guidance for future enrichment
of the structured diagnosis protocol, not as a pending refactor of raw output
branching from scratch.

### The Problem

There are currently four output paths, constructed independently in `_run_validation()`:

1. **Console display** — `ConsoleReporter.print_summary()` + `DynamicDisplay`
2. **JSON** — `summary.to_dict()` with manual enrichment (log paths, next_steps, schema version)
3. **SARIF** — `SarifReporter.generate()` operating on the same `ExecutionSummary`
4. **Output file** — Write-to-file logic branching on which format was requested

Each path reads from `ExecutionSummary` and `CheckResult`, but applies its own formatting, filtering, and enrichment logic. This means:

- Business logic is duplicated (the JSON path manually re-derives "first failure" and "next steps" that the console path also computes)
- Adding a new field to output requires touching 3+ code paths
- The console and JSON representations can *diverge* — one might show a field the other omits
- Testing each output format requires separate integration tests that may not catch drift

### Current Data Flow

```
CheckExecutor.run_checks()
       │
       ▼
  ExecutionSummary (list of CheckResult)
       │
       ├──► ConsoleReporter.print_summary()  ──► stdout (human)
       │         [reads results, formats, prints]
       │
       ├──► summary.to_dict() + manual enrichment ──► JSON string
       │         [re-derives failures, adds schema/level/next_steps]
       │
       ├──► SarifReporter.generate()  ──► SARIF JSON
       │         [transforms results into SARIF schema]
       │
       └──► output_file write logic  ──► file
                [if-else on which format was requested]
```

### Proposed Data Flow

```
CheckExecutor.run_checks()
       │
       ▼
  ExecutionSummary
       │
       ▼
  RunReport.from_summary(summary, level, project_root)
       │    [single place that derives: failures, warnings, next_steps,
       │     log_paths, scope, timing, verify_commands — ALL enrichment]
       │
       ├──► ConsoleAdapter.render(report) ──► stdout
       ├──► JsonAdapter.render(report)    ──► JSON string
       ├──► SarifAdapter.render(report)   ──► SARIF JSON
       └──► FileAdapter.write(payload, path)  ──► file
```

### Key Design Decisions

1. **`RunReport`** is the canonical, fully-enriched representation of a run. It contains everything any adapter needs. No adapter re-derives data from raw results.

2. **Adapters are pure transforms.** `ConsoleAdapter.render(report) -> str` (or prints). `JsonAdapter.render(report) -> str`. `SarifAdapter.render(report) -> dict`. They do NOT query the filesystem, compute durations, or determine "first failure." They format.

3. **Adapter selection happens once**, based on CLI flags, before execution. The `_run_validation()` function determines which adapters are needed and passes them to a rendering pipeline rather than branching 4 ways in a 120-line if/elif/else block.

4. **New output formats** (future: JUnit XML, GitHub Actions annotations, Slack webhook) require only a new adapter class, not modifications to `_run_validation()`.

5. **Testing is trivial.** Each adapter is a pure function from `RunReport` to string/dict. Unit-test the adapters with fixture `RunReport` objects. Integration-test the pipeline once.

### Relationship to Work Item 2

The `Diagnosis` / `GateOutput` structured output protocol produces data that the `RunReport` consumes. Each `CheckResult` carries structured diagnoses. The `RunReport` aggregates them. Each adapter renders them according to its format:

- **Console**: Human-readable Diagnosis → Prescription → Verification blocks
- **JSON**: Machine-readable array of `{location, what, why, fix}` objects
- **SARIF**: Maps diagnoses to `result.message.text` with `fix_instruction` in `properties`

This means Work Item 2 (didactic output) and Work Item 3 (unified adapters) are **complementary, not conflicting** — the structured output protocol *feeds* the adapter layer.

---

## Execution Order and Dependencies

```
Work Item 1 (Two-Tier Architecture)
    │
    ├─► 1a: Add CheckRole enum + classify all checks
    │       [Low risk, additive — no behavior change]
    │
    └─► 1b: Smart init discovery
            [Medium risk — changes init flow, needs integration tests]
            [Depends on 1a for knowing which checks are FOUNDATION]

Work Item 3 (Unified Output Adapter)
    │
    ├─► 3a: Define RunReport + adapter interfaces
    │       [Design-heavy, low code risk]
    │
    ├─► 3b: Implement adapters (Console, JSON, SARIF)
    │       [Refactor — behavior should be identical, just restructured]
    │
    └─► 3c: Rewire _run_validation() to use adapter pipeline
            [Integration — the risky part, needs thorough testing]

Work Item 2 (Didactic Output)
    │
    ├─► 2a: Enhance Finding with fix_instruction field
    │       [Additive — backward compatible]
    │
    ├─► 2b: Update gates to produce structured diagnoses
    │       [Per-gate work — can be incremental, start with highest-value gates]
    │
    └─► 2c: Update adapters to render Diagnosis → Prescription → Verify
            [Depends on 3b existing]
```

Recommended execution: **1a → 3a → 3b → 3c → 2a → 2b (incremental) → 1b**

1a is additive and sets the vocabulary. 3a-3c restructures the output pipeline (refactor — easier to do before adding new output fields). 2a-2b enriches the data flowing through the already-unified pipeline. 1b is the most complex and benefits from all prior work being stable.

---

## What This Is Not

- **Not a rewrite.** The check execution engine (`CheckExecutor`, `CheckRegistry`, dependency resolution, fail-fast, time budgets) is solid and unchanged.
- **Not removing flaws.** The flaw taxonomy (overconfidence, deceptiveness, laziness, myopia) remains the primary organizing principle. `CheckRole` is orthogonal — it answers "what kind of work" not "what kind of failure."
- **Not adding new gates.** Gate count stays the same. We're reclassifying and improving the output of existing ones.
- **Not breaking backward compatibility.** JSON schema gets a version bump if fields change. Existing `--json` consumers see enriched output, not different output.

## What This Is

A transition from "bag of checks with flaw labels" to "layered quality system with a unified voice." Foundation checks prove the ground is solid. Diagnostic checks find what only slop-mop can find. And every output — console, JSON, SARIF — speaks with one voice, one data source, and one purpose: **leave the LLM with zero questions and exactly one thing to do next.**
