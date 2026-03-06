# New Gate Protocol

Strict protocol for adding a new quality gate to slop-mop. Follow sequentially — each step depends on the previous. An agent following this protocol should be able to add a new gate with zero ambiguity.

---

## Phase 0: Deciding Whether to Build It

Before writing any code, answer these questions honestly.

### Consider a Custom Gate First

If you're not sure the gate belongs in slop-mop permanently, **start by running it as a custom gate**. Define it as a shell command in `.sb_config.json`, use it on a real project for a few weeks, and evaluate:

- Does it catch real problems consistently?
- Is the output actionable without manual interpretation?
- Would it be useful across *multiple* projects, not just yours?

If the answer to all three is yes, that's a strong signal to promote it to a built-in gate. Open a feature request or PR with evidence from your custom gate usage — what it caught, what the false-positive rate was, how agents responded to its output.

See the [Custom Gates section in the README](README.md#custom-gates) for the config format.

### Selection Criteria

| Criterion                                                                                        | Must Pass |
| ------------------------------------------------------------------------------------------------ | --------- |
| **Fast** — adds ≤2s to a typical commit validation run                                           | ✅        |
| **Canonical** — wraps an established, well-maintained tool (not a custom script) when one exists | ✅        |
| **Value > Friction** — catches real problems agents actually create, not theoretical ones        | ✅        |
| **Reliable on \*nix** — works on macOS and Linux without platform-specific hacks                 | ✅        |
| **Deterministic** — same input produces same pass/fail, no flaky results                         | ✅        |
| **Actionable output** — failure message tells an LLM exactly what to fix                         | ✅        |

If any criterion fails, stop. File an issue to discuss whether the gate belongs here.

### Choosing the Underlying Tool

1. **Prefer PyPI-installable tools** — `pip install <tool>` is the simplest dependency story
2. **Prefer tools with machine-readable output** — JSON, structured text, or clear exit codes
3. **Avoid tools that require external services** — no API keys, no network calls (exception: `security:full` at PR level)
4. **Check maintenance status** — last release within 12 months, active issue tracker

---

## Phase 1: Design the Gate (Before Any Code)

### 1.1 Decide on Identity

- **Category**: `python`, `javascript`, `quality`, `security`, `general`, `pr`, or `integration`
- **Name**: lowercase, hyphenated, no category prefix (e.g., `dead-code` not `quality:dead-code`)
- **Full name**: auto-derived as `{category}:{name}`
- **Display name**: emoji + human-readable (e.g., `💀 Dead Code (≥80% confidence)`)

### 1.2 Decide on Configuration

What's configurable? What are sensible defaults? Every config value needs a reason — don't add knobs "just in case."

Document the reasoning behind each default value in the config field's `description` and in the check class docstring. Future agents and humans will need to understand why the threshold is 80 and not 50.

### 1.3 Plan the Output

**This is the most important design decision.** The output is what an LLM reads when the gate fails. It must contain everything needed to fix the problem immediately, with no additional research required.

Design the error output to include:

- **What failed** — specific files and line numbers
- **Why it failed** — the rule and threshold that was violated
- **How to fix it** — exact command, code change, or approach
- **How to re-check** — the `sm swab -g` command to re-run just this gate

**Do not build the output string manually.** Build a list of `Finding` objects and pass it to `_create_result(findings=...)`. The console output string is auto-generated from the findings (`file:line:col: message` per line), the JSON output gets structured data, and SARIF gets `physicalLocation` for GitHub Code Scanning — all from one call. See §2.2b.

#### The `fix_suggestion` contract

Your `fix_suggestion` is the gate-wide strategy. It is read by an agent that already has your full `output` in context. It is **not** a pointer to somewhere else.

**MUST:** tell the agent what kind of fix resolves this class of failure. "Extract the longest branch into a helper function." "Write tests that exercise the uncovered paths." The agent reads this, looks at the findings list, and acts.

**MUST NOT:** say `"Run: <same tool> -v to see details"`. You already ran the tool. You already have the details. If the agent has to re-run the tool to learn what to fix, your gate wasted its first run. Parse the tool's output into `Finding` objects — that's where the details go.

**May** say `Run: black . && isort .` — that's a *different* command that *applies the fix*. Auto-fix commands are fine. Re-run-for-output commands are not.

#### The per-finding `fix_strategy`

Some findings can be more specific than the gate-wide `fix_suggestion` allows. `Finding.fix_strategy` is a one-sentence recipe scoped to that single finding.

**Only populate it with what you can compute.** A complexity checker knows the score and the limit — `"Complexity is 21, limit is 10 — shed at least 11"`. A coverage checker with the source file on disk can `ast.parse` it and name the enclosing function — `"Lines 42-48 in handle_retry() are uncovered"`. A bandit wrapper with the rule ID can look up the canonical fix — `"Replace yaml.load() with yaml.safe_load()"`.

**Omit it when you'd be guessing.** Don't invent test file paths. Don't assume naming conventions. `fix_strategy=None` is honest; a fabricated path sends the agent on a hunt for a file that doesn't exist. The finding's `message` and `file:line` already locate the problem — silence is better than confident noise.

### 1.4 Decide on Profiles

Which profiles should include this gate?

- `commit` — most gates go here (runs every commit)
- `pr` — everything in commit + PR-specific checks
- `quick` — lint-only, ultra-fast
- Category-specific (`python`, `javascript`, `quality`, `security`)

---

## Phase 2: Implement (TDD)

### 2.1 Create the Test File First

```
tests/unit/test_<name>_check.py
```

Write tests before the implementation. At minimum, cover:

**Identity & metadata:**

- `name`, `full_name`, `display_name`, `category` return expected values

**Config:**

- `config_schema` includes expected fields
- Default values are correct
- Custom values from config dict are respected

**Applicability:**

- `is_applicable()` returns `True` when relevant files/structure exist
- `is_applicable()` returns `False` when they don't
- Use `tmp_path` fixture for filesystem tests

**Run scenarios (mock `_run_command`):**

- Clean run → `CheckStatus.PASSED`
- Findings found → `CheckStatus.FAILED` with correct output and `fix_suggestion`
- Tool not installed (returncode 127) → `CheckStatus.ERROR` with install instruction
- Timeout → appropriate error

**Output quality:**

- Error output includes file/line info
- `fix_suggestion` is actionable
- Output is capped/truncated for large results (avoid token bloat)

### 2.2 Create the Check Module

```
slopmop/checks/<category>/<name>.py
```

Inherit from `BaseCheck` (and optionally `PythonCheckMixin` or `JavaScriptCheckMixin`).

**Required members** (5):

| Member                        | Type        | Description                                              |
| ----------------------------- | ----------- | -------------------------------------------------------- |
| `name`                        | `@property` | Lowercase hyphenated identifier. **No category prefix.** |
| `display_name`                | `@property` | Human-readable with emoji                                |
| `category`                    | `@property` | `GateCategory` enum value                                |
| `is_applicable(project_root)` | method      | Returns `bool`                                           |
| `run(project_root)`           | method      | Returns `CheckResult`                                    |

**Optional overrides:**

| Member                      | Default         |                             |
| --------------------------- | --------------- | --------------------------- |
| `depends_on`                | `[]`            | List of `full_name` strings |
| `config_schema`             | `[]`            | List of `ConfigField`       |
| `can_auto_fix()`            | `False`         |                             |
| `auto_fix(project_root)`    | `False`         |                             |
| `skip_reason(project_root)` | Generic message |                             |
| `tool_context`              | `ToolContext.PURE` | See **Tool Context** below |

### Tool Context (Required Decision)

Every gate must declare its `tool_context` — a `ClassVar` that tells slop-mop how the gate resolves its external tools. This determines runtime behavior when the gate is bolted onto a project that may or may not have its own virtual environment.

```python
from slopmop.checks.base import ToolContext

class MyCheck(BaseCheck, PythonCheckMixin):
    tool_context = ToolContext.SM_TOOL  # ← Set this explicitly
```

**Categories:**

| Context          | Meaning                                              | Tool resolution            | Example gates                 |
| ---------------- | ---------------------------------------------------- | -------------------------- | ----------------------------- |
| `ToolContext.PURE`    | No external tools needed (AST, regex, file parsing)  | N/A                        | `LocLockCheck`, `BogusTestsCheck` |
| `ToolContext.SM_TOOL` | Uses tools bundled with slop-mop (via pipx)          | `find_tool()` / bare cmd   | `SecurityLocalCheck`, `ComplexityCheck` |
| `ToolContext.PROJECT` | Runs against the project's own Python env            | `get_project_python()`     | `PythonTestsCheck`, `PythonCoverageCheck` |
| `ToolContext.NODE`    | Requires Node.js toolchain in the project            | `npx` / `node_modules`     | `SourceDuplicationCheck`, `FrontendCheck` |

**Decision guide:**

1. Does your gate call any external executable? **No** → `PURE`
2. Does it wrap a Python tool that ships with slop-mop (listed in `pyproject.toml` dependencies)? **Yes** → `SM_TOOL`. Use bare command name in `_run_command()` (e.g., `["bandit", ...]`), not `get_project_python() + -m`.
3. Does it need to run *inside* the project's own Python environment (pytest, coverage, project-specific imports)? **Yes** → `PROJECT`. Use `get_project_python()`. Call `check_project_venv_or_fail()` at the top of `run()`.
4. Does it need Node.js / npm packages? **Yes** → `NODE`.

**PROJECT checks must include the venv gate:**

```python
def run(self, project_root: str) -> CheckResult:
    start_time = time.time()

    # PROJECT check: refuse to run against a borrowed interpreter
    no_venv = self.check_project_venv_or_fail(project_root, start_time)
    if no_venv is not None:
        return no_venv

    # ... normal check logic ...
```

This is a hard stop, not a courtesy warning. If `./venv` or `./.venv` doesn't exist the gate returns `FAILED` with the exact `python -m venv` command to run. No escape hatch — an ambient `$VIRTUAL_ENV` from some other project does not count. A PROJECT check that runs pytest against the wrong interpreter produces a green checkmark that describes a different codebase; failing loudly is the only honest outcome.

### Check Role (Required Decision)

Orthogonal to `tool_context`. `ToolContext` says *how* you invoke a tool; `CheckRole` says *whether that tool is the floor or the ceiling*.

```python
from slopmop.checks.base import CheckRole

class MyCheck(BaseCheck):
    role = CheckRole.FOUNDATION  # or omit — default is DIAGNOSTIC
```

| Role | Meaning | Test |
|---|---|---|
| `FOUNDATION` | Wraps a tool that every competent project already runs in CI: black, mypy, pytest, eslint, tsc, prettier, coverage. The gate is a binary structural floor — you can't ship without it. | Would a project without slop-mop *still* run this tool? |
| `DIAGNOSTIC` | Novel analysis with no equivalent in conventional tooling. Asks questions nobody else asks. This is why slop-mop exists. | Is this something only an AI-codegen-aware checker would think to look for? |

**The default is `DIAGNOSTIC`.** A check proves itself `FOUNDATION` by wrapping something on the `black`/`mypy`/`pytest` short list. Using an external tool is not sufficient — `radon`, `vulture`, `jscpd`, `bandit` are real tools but the *questions they answer* are novel. Complexity-creep and dead-code-detection are diagnostics; "do the tests pass" is foundation.

Role appears in console output as `[floor]` / `[diag]` badges, in JSON as `result.role`, and in SARIF rule properties. Downstream consumers filter on it: "show me only the novel slop-mop insights, skip the stuff my CI already tells me."

### 2.2b Structured Findings (Required)

Every gate that fails with identifiable locations must return those locations as `Finding` objects, not as a formatted string. This is how the gate feeds three consumers at once:

| Consumer | Gets | Via |
| --- | --- | --- |
| Terminal | `file:line:col: message` per line | `Finding.__str__()`, auto-joined |
| `--json` | `[{file, line, column, message, rule_id}, ...]` | `Finding.to_dict()` |
| `--sarif` | inline PR annotations in GitHub Code Scanning | `SarifReporter` → `physicalLocation` |

**The pattern:**

```python
from slopmop.core.result import Finding

def run(self, project_root: str) -> CheckResult:
    # ... run the tool, parse its output ...
    findings: List[Finding] = []
    for problem in parsed_output:
        findings.append(Finding(
            message=problem.description,       # required
            file=problem.relative_path,        # optional — omit for project-scoped issues
            line=problem.line_number,          # optional, 1-based
            column=problem.column,             # optional, 1-based
            rule_id=problem.tool_rule_code,    # optional — e.g. "E501", "no-undef"
            fix_strategy=derive_fix(problem),  # optional — see §1.3, compute don't guess
        ))

    if findings:
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            findings=findings,                 # ← console output auto-generated from this
            error=f"{len(findings)} issue(s)",
            fix_suggestion="...",
        )
```

If the tool you're wrapping has a JSON output mode (`--format json`, `--json`, `--output-format=json`), use it — structured input means no regex parsing. ESLint, pyright, and jscpd all support this. If the tool only has text output, parse it once into `Finding`s; don't format text, then re-parse it later.

**Granularity:** one `Finding` per fixable unit. A lint error on line 42 is one finding. Ten unformatted files is ten file-level findings (no line). A misconfigured `.sb_config.json` key is one project-level finding (no file — SARIF anchors it at the repo root).

**The class docstring IS the help text.** `sm help <gate>` displays it directly. Write it like documentation, not like a code comment. Include:

- What the gate checks and why it matters
- What tool it wraps
- What the default configuration is and why
- How to fix common failures

### 2.3 Register the Check

**Three places:**

1. **Export from category `__init__.py`:**

   ```python
   # slopmop/checks/<category>/__init__.py
   from slopmop.checks.<category>.<module> import MyCheck
   __all__ = [..., "MyCheck"]
   ```

2. **Register in `slopmop/checks/__init__.py`:**
   Add `registry.register(MyCheck)` to the appropriate `_register_*_checks()` function.

3. **Add to profiles in `_register_aliases()`:**
   Append `"<category>:<name>"` to the appropriate profile lists.

### 2.4 Whitelist External Tools

If your check calls an external executable via `_run_command()`:

1. Add to `ALLOWED_EXECUTABLES` in `slopmop/subprocess/validator.py`
2. Add to `requirements.txt`
3. Add to `dependencies` in `pyproject.toml` — **this is what CI uses** (`pip install -r requirements.txt`)

### 2.5 Run Tests, Iterate

```bash
pytest tests/unit/test_<name>_check.py -v   # Your tests pass
pytest tests/ -x -q                          # No regressions
sm swab                              # Full self-validation
```

---

## Phase 3: Document

### 3.1 Gate Help (Already Done)

The class docstring is the help text. Verify it reads well:

```bash
sm help <category>:<name>
```

### 3.2 Update README.md

Add a row to the appropriate gate table in the "Available Gates" section:

```markdown
| `<category>:<name>` | <emoji> Description |
```

If you added the gate to profiles, update the profiles table and the "Commit vs PR" section.

### 3.3 Capture Example Output

Run the gate against a project where it would fail. Capture the output. This serves two purposes:

1. Proves the output is LLM-actionable
2. Provides an example for the user to show what the gate does

---

## Phase 4: Verify & Report

### 4.1 Final Validation

```bash
sm swab                          # All gates pass
sm help <category>:<name>            # Help text looks right
sm swab -g <category>:<name>         # Gate runs independently
sm swab                              # Swab includes the gate
```

### 4.2 Report to User

After implementation, show the user:

1. **How the check works** — what it catches, what tool it wraps
2. **Example output** — what a failure looks like (captured in Phase 3)
3. **How to run the help** — `sm help <category>:<name>`
4. **Where README was updated** — link to the section
5. **Config defaults and reasoning** — why each value is what it is
6. **Profile membership** — which profiles include this gate

---

## Checklist

Copy into your commit message or PR description:

```
- [ ] Selection criteria all pass (fast, canonical, valuable, reliable, deterministic, actionable)
- [ ] Tests written first (identity, config, applicability, run scenarios, output quality)
- [ ] Check class with all 5 required members
- [ ] Failures return structured `Finding` objects via `_create_result(findings=...)`
- [ ] Class docstring written as help text (includes config reasoning)
- [ ] Exported from category __init__.py
- [ ] Registered in slopmop/checks/__init__.py
- [ ] Added to profiles in _register_aliases()
- [ ] External tools whitelisted in ALLOWED_EXECUTABLES (if applicable)
- [ ] External tools in requirements.txt and pyproject.toml (if applicable)
- [ ] README gate table updated
- [ ] README profiles table updated (if applicable)
- [ ] Example failure output captured
- [ ] sm swab passes
- [ ] Report shown to user
```

---

## Common Failure Modes

These are the mistakes agents make repeatedly. Read them before you start.

1. **Forgot to register** — Class exists but `registry.register(MyCheck)` never called. Gate doesn't appear.

2. **Forgot to add to profiles** — Registered but not in `commit`/`pr` alias list. Individual validation works, profile skips it.

3. **Missing subprocess whitelist** — Check calls `_run_command(["newtool", ...])` but `newtool` isn't in `ALLOWED_EXECUTABLES`. Runtime `SecurityError`.

4. **Category prefix in name** — `name` should be `"dead-code"`, not `"quality:dead-code"`. Prefix is auto-derived from `category`.

5. **Wrong mixin order** — `class MyCheck(PythonCheckMixin, BaseCheck)` ✅ not `class MyCheck(BaseCheck, PythonCheckMixin)` ❌

6. **Output not actionable** — Failed gate says "3 issues found" but doesn't say where or how to fix them. Useless to an LLM, and SARIF gets a single repo-root alert instead of three inline annotations. Build `Finding` objects (§2.2b); the string is generated for you.

6a. **`fix_suggestion` just says "run it again"** — `"Run: pytest -v to see failures"` is an admission that your gate didn't parse its own output. You *had* the output. Parse it. The agent should never need a second tool invocation to learn what the first one found.

6b. **`fix_strategy` is a guess** — `fix_strategy="Add test to tests/test_foo.py"` when you don't know that file exists. The agent will try to edit a non-existent file. Leave `fix_strategy=None`; the `message` + `file:line` already locate the problem, and silence beats fabrication.

7. **Not handling tool-not-installed** — Always check `returncode == 127`. Return `CheckStatus.ERROR` with `fix_suggestion="pip install <tool>"`.

8. **Stale Documentation (Current list includes: README)** — Added the gate, wrote the tests, forgot to update documentation. Next session wastes time wondering why `sm help` shows it but README doesn't.

9. **Config default mismatch** — Getter method hardcodes a fallback that differs from `ConfigField.default`.

10. **Tests that run real tools** — Unit tests must mock `_run_command`. Only integration tests invoke actual binaries.
