# New Gate Protocol

Strict protocol for adding a new quality gate to slop-mop. Follow sequentially — each step depends on the previous. An agent following this protocol should be able to add a new gate with zero ambiguity.

---

## Phase 0: Deciding Whether to Build It

Before writing any code, answer these questions honestly.

### Selection Criteria

| Criterion | Must Pass |
|---|---|
| **Fast** — adds ≤2s to a typical commit validation run | ✅ |
| **Canonical** — wraps an established, well-maintained tool (not a custom script) when one exists | ✅ |
| **Value > Friction** — catches real problems agents actually create, not theoretical ones | ✅ |
| **Reliable on *nix** — works on macOS and Linux without platform-specific hacks | ✅ |
| **Deterministic** — same input produces same pass/fail, no flaky results | ✅ |
| **Actionable output** — failure message tells an LLM exactly what to fix | ✅ |

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
- **How to re-validate** — the `sm validate` command to re-run just this gate

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

| Member | Type | Description |
|---|---|---|
| `name` | `@property` | Lowercase hyphenated identifier. **No category prefix.** |
| `display_name` | `@property` | Human-readable with emoji |
| `category` | `@property` | `GateCategory` enum value |
| `is_applicable(project_root)` | method | Returns `bool` |
| `run(project_root)` | method | Returns `CheckResult` |

**Optional overrides:**

| Member | Default | |
|---|---|---|
| `depends_on` | `[]` | List of `full_name` strings |
| `config_schema` | `[]` | List of `ConfigField` |
| `can_auto_fix()` | `False` | |
| `auto_fix(project_root)` | `False` | |
| `skip_reason(project_root)` | Generic message | |

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
3. Add to `install_requires` or `extras_require` in `setup.py`

### 2.5 Run Tests, Iterate

```bash
pytest tests/unit/test_<name>_check.py -v   # Your tests pass
pytest tests/ -x -q                          # No regressions
sm validate --self                           # Full self-validation
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
sm validate --self                    # All gates pass
sm help <category>:<name>            # Help text looks right
sm validate <category>:<name>        # Gate runs independently
sm validate commit                   # Profile includes the gate
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
- [ ] Class docstring written as help text (includes config reasoning)
- [ ] Exported from category __init__.py
- [ ] Registered in slopmop/checks/__init__.py
- [ ] Added to profiles in _register_aliases()
- [ ] External tools whitelisted in ALLOWED_EXECUTABLES (if applicable)
- [ ] External tools in requirements.txt and setup.py (if applicable)
- [ ] README gate table updated
- [ ] README profiles table updated (if applicable)
- [ ] Example failure output captured
- [ ] sm validate --self passes
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

6. **Output not actionable** — Failed gate says "3 issues found" but doesn't say where or how to fix them. Useless to an LLM.

7. **Not handling tool-not-installed** — Always check `returncode == 127`. Return `CheckStatus.ERROR` with `fix_suggestion="pip install <tool>"`.

8. **Stale README** — Added the gate, wrote the tests, forgot to update documentation. Next session wastes time wondering why `sm help` shows it but README doesn't.

9. **Config default mismatch** — Getter method hardcodes a fallback that differs from `ConfigField.default`.

10. **Tests that run real tools** — Unit tests must mock `_run_command`. Only integration tests invoke actual binaries.
