# Contributing to Slop-Mop

## Adding a New Quality Gate

This guide walks through the complete process of adding a new check to slop-mop. Follow every step — skipping even one (especially registration or README updates) is the most common source of "it works locally but doesn't show up" bugs.

### Overview

A check is a Python class that:
1. Inherits from `BaseCheck` (and optionally a mixin like `PythonCheckMixin`)
2. Implements 5 required properties/methods
3. Gets registered in the check registry
4. Gets added to one or more profiles

The system auto-derives everything else — help text, config generation, skip reasons, the full gate name — from your class metadata.

---

### Step 1: Create the Check Module

Create a new file in the appropriate category directory:

```
slopmop/checks/
├── python/          # Python-specific gates
├── javascript/      # JavaScript-specific gates
├── quality/         # Language-agnostic quality gates
├── security/        # Security scanning gates
├── general/         # General-purpose gates
└── pr/              # PR-level gates
```

Example: `slopmop/checks/quality/my_check.py`

### Step 2: Implement the Check Class

Every check must implement these **5 required members**:

```python
from typing import Any, Dict, List

from slopmop.checks.base import BaseCheck, ConfigField
from slopmop.core.result import CheckResult, CheckStatus, GateCategory


class MyCheck(BaseCheck):
    """One-line description shown in `sm help my-check`.

    Detailed description shown in `sm help quality:my-check`.
    Can be multi-line. Explain what the check does, why it matters,
    and what tools it wraps (if any).
    """

    @property
    def name(self) -> str:
        # Lowercase, hyphenated. NO category prefix — that's auto-derived.
        return "my-check"

    @property
    def display_name(self) -> str:
        # Human-readable with emoji. Shown in console output.
        return "🔮 My Check"

    @property
    def category(self) -> GateCategory:
        # Determines the full_name prefix (e.g., "quality:my-check")
        return GateCategory.QUALITY

    def is_applicable(self, project_root: str) -> bool:
        # Return True if this check should run for this project.
        # Use this to auto-skip when the check doesn't apply
        # (e.g., no Python files, no package.json, etc.)
        return True

    def run(self, project_root: str) -> CheckResult:
        # Execute the check. Return a CheckResult.
        import time
        start = time.time()

        result = self._run_command(["my-tool", "--flag"], cwd=project_root)
        duration = time.time() - start

        if result.returncode == 127:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                error="my-tool not found",
                fix_suggestion="pip install my-tool",
            )

        if result.success:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output="No issues found",
            )

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=result.stdout,
            error=result.stderr,
            fix_suggestion="Run: my-tool --fix",
        )
```

#### Optional Overrides

| Member | Default | Purpose |
|---|---|---|
| `depends_on` | `[]` | List of `full_name` strings this check must run after |
| `config_schema` | `[]` | List of `ConfigField` for check-specific settings |
| `can_auto_fix()` | `False` | Whether the check supports `--fix` |
| `auto_fix(project_root)` | `False` | Perform auto-fix, return success bool |
| `skip_reason(project_root)` | Generic | Human-readable reason when `is_applicable()` returns `False` |

#### Config Schema

Every check automatically gets three standard fields (`enabled`, `auto_fix`, `config_file_path`). Override `config_schema` to add your own:

```python
@property
def config_schema(self) -> List[ConfigField]:
    return [
        ConfigField(
            name="min_confidence",
            field_type="integer",
            default=80,
            description="Minimum confidence to report (60-100)",
            min_value=60,
            max_value=100,
        ),
        ConfigField(
            name="exclude_patterns",
            field_type="string[]",
            default=["**/venv/**"],
            description="Glob patterns to exclude",
        ),
    ]
```

Read values via `self.config.get("min_confidence", 80)`. The config lives in `.sb_config.json`:

```json
{ "quality": { "gates": { "my-check": { "min_confidence": 80 } } } }
```

#### Using Mixins

For Python-specific checks, inherit `PythonCheckMixin` **before** `BaseCheck`:

```python
from slopmop.checks.base import BaseCheck, PythonCheckMixin

class MyPythonCheck(PythonCheckMixin, BaseCheck):
    # Gets _find_python() for venv-aware Python resolution
    # Gets is_applicable() that checks for .py files
    # Gets skip_reason() for "no Python files found"
    ...
```

Similarly `JavaScriptCheckMixin` for JavaScript checks.

### Step 3: Export from Category `__init__.py`

Add your check to the category's `__init__.py`:

```python
# slopmop/checks/quality/__init__.py
from slopmop.checks.quality.my_check import MyCheck

__all__ = [..., "MyCheck"]
```

### Step 4: Register in `slopmop/checks/__init__.py`

Add your check to the appropriate `_register_*_checks()` function:

```python
def _register_crosscutting_checks(registry: CheckRegistry) -> None:
    # ... existing registrations ...
    registry.register(MyCheck)
```

Then add it to the appropriate profile aliases in `_register_aliases()`:

```python
registry.register_alias(
    "commit",
    [
        # ... existing gates ...
        "quality:my-check",  # ← Add here
    ],
)
```

**Common profiles:**
- `commit` — runs on every commit (most checks go here)
- `pr` — runs on PR validation (includes everything in commit + PR-specific gates)
- `quick` — ultra-fast lint-only
- `quality` — all quality gates

### Step 5: Whitelist External Tools

If your check runs an external executable via `_run_command()`, add it to `ALLOWED_EXECUTABLES` in `slopmop/subprocess/validator.py`:

```python
ALLOWED_EXECUTABLES: FrozenSet[str] = frozenset({
    # ... existing entries ...
    "my-tool",     # Quality: my-check gate
})
```

Also add the tool to `requirements.txt` and `setup.py` (under `install_requires` or `extras_require`).

### Step 6: Write Tests

Create `tests/unit/test_my_check.py`. Tests should cover:

```python
import pytest
from unittest.mock import patch, MagicMock
from slopmop.checks.quality.my_check import MyCheck
from slopmop.core.result import CheckStatus, GateCategory


@pytest.fixture
def check():
    return MyCheck({})


class TestMyCheck:
    # --- Identity & Metadata ---
    def test_name(self, check):
        assert check.name == "my-check"

    def test_full_name(self, check):
        assert check.full_name == "quality:my-check"

    def test_display_name(self, check):
        assert "My Check" in check.display_name

    def test_category(self, check):
        assert check.category == GateCategory.QUALITY

    # --- Config ---
    def test_config_schema_fields(self, check):
        names = [f.name for f in check.config_schema]
        assert "min_confidence" in names

    def test_default_config(self, check):
        # Test default values are read correctly
        ...

    def test_custom_config(self):
        check = MyCheck({"min_confidence": 90})
        # Test custom values override defaults
        ...

    # --- Applicability ---
    def test_is_applicable_with_files(self, check, tmp_path):
        (tmp_path / "example.py").write_text("x = 1")
        assert check.is_applicable(str(tmp_path))

    def test_not_applicable_without_files(self, check, tmp_path):
        assert not check.is_applicable(str(tmp_path))

    # --- Run (mocked) ---
    def test_run_clean(self, check, tmp_path):
        mock_result = MagicMock(returncode=0, success=True, stdout="", stderr="")
        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.PASSED

    def test_run_findings(self, check, tmp_path):
        mock_result = MagicMock(
            returncode=1, success=False,
            stdout="file.py:10: issue found", stderr=""
        )
        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.FAILED

    def test_run_tool_not_installed(self, check, tmp_path):
        mock_result = MagicMock(returncode=127, success=False, stdout="", stderr="")
        with patch.object(check, "_run_command", return_value=mock_result):
            result = check.run(str(tmp_path))
        assert result.status == CheckStatus.ERROR
        assert "install" in result.fix_suggestion.lower()
```

**Key testing principles:**
- Mock `_run_command` — don't run real tools in unit tests
- Use `tmp_path` for filesystem tests
- Test both happy and error paths
- Verify `fix_suggestion` text is actionable

### Step 7: Update README.md

Add your gate to the appropriate table in the "Available Gates" section:

```markdown
| `quality:my-check` | 🔮 Description of what it checks |
```

If you added it to profiles, update the profiles table too.

### Step 8: Verify Everything Works

```bash
# Run tests
pytest tests/unit/test_my_check.py -v

# Run all tests to check for regressions
pytest

# Verify the gate shows up in help
sm help quality:my-check

# Run it against a test project
sm validate quality:my-check

# Run the full profile it belongs to
sm validate commit

# Self-validate slop-mop
sm validate --self
```

---

### Checklist

Copy this into your PR description:

```markdown
- [ ] Check class created with all 5 required members
- [ ] Exported from category `__init__.py`
- [ ] Registered in `slopmop/checks/__init__.py`
- [ ] Added to appropriate profile(s) in `_register_aliases()`
- [ ] External tools added to `ALLOWED_EXECUTABLES` (if applicable)
- [ ] External tools added to `requirements.txt` / `setup.py` (if applicable)
- [ ] Unit tests written (identity, config, applicability, run scenarios)
- [ ] README.md gate table updated
- [ ] README.md profile table updated (if added to profile)
- [ ] `sm validate --self` passes
```

---

### Common Pitfalls

1. **Forgot to register** — Class exists but `registry.register(MyCheck)` never called. Gate won't appear anywhere.

2. **Forgot to add to profiles** — Registered but not in the `commit`/`pr` alias list. `sm validate quality:my-check` works, `sm validate commit` skips it.

3. **Missing subprocess whitelist** — Check calls `_run_command(["newtool", ...])` but `newtool` isn't in `ALLOWED_EXECUTABLES`. Runtime `SecurityError`.

4. **Category prefix in name** — `name` should be `"my-check"`, not `"quality:my-check"`. The prefix is auto-derived from `category`.

5. **Wrong mixin order** — `class MyCheck(PythonCheckMixin, BaseCheck)` ✅ not `class MyCheck(BaseCheck, PythonCheckMixin)` ❌

6. **Config default mismatch** — If `_get_threshold()` hardcodes a fallback, it must match `ConfigField.default`.

7. **Not handling tool-not-installed** — Always check `returncode == 127` and return `CheckStatus.ERROR` with a `fix_suggestion` like `"pip install <tool>"`.

8. **Tests that run real tools** — Unit tests should mock `_run_command`. Only integration tests invoke actual binaries.

9. **Forgot to export from `__init__.py`** — Added `quality/my_check.py` but didn't import it in `quality/__init__.py`.

10. **Stale README** — Added the gate, ran the tests, forgot to update the docs. Future-you (or your AI partner) will waste a session wondering why `sm help` shows it but the README doesn't mention it.
