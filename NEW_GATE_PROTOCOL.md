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
3. Does it need to run *inside* the project's own Python environment (pytest, coverage, project-specific imports)? **Yes** → `PROJECT`. Use `get_project_python()`. Call `check_project_venv_or_warn()` at the top of `run()`.
4. Does it need Node.js / npm packages? **Yes** → `NODE`.

**PROJECT checks must include the venv guard:**

```python
def run(self, project_root: str) -> CheckResult:
    start_time = time.time()

    # PROJECT check: bail early when no project venv exists
    venv_warn = self.check_project_venv_or_warn(project_root, start_time)
    if venv_warn is not None:
        return venv_warn

    # ... normal check logic ...
```

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

7. **Not handling tool-not-installed** — Always check `returncode == 127`. Return `CheckStatus.ERROR` with `fix_suggestion="pip install <tool>"`.

8. **Stale Documentation (Current list includes: README)** — Added the gate, wrote the tests, forgot to update documentation. Next session wastes time wondering why `sm help` shows it but README doesn't.

9. **Config default mismatch** — Getter method hardcodes a fallback that differs from `ConfigField.default`.

10. **Tests that run real tools** — Unit tests must mock `_run_command`. Only integration tests invoke actual binaries.
