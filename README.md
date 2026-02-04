# 🧹 Slop-Mop

**AI-Focused Quality Gate Framework**

A language-agnostic, bolt-on code validation tool designed to catch AI-generated slop before it lands in your codebase. Provides fast, actionable feedback for both human developers and AI coding assistants.

## Philosophy

- **Fail fast**: Stop at the first failure to save time
- **Maximum value, minimum time**: Prioritize quick, high-impact checks
- **AI-friendly output**: Clear errors with exact fixes
- **Zero configuration required**: Works out of the box
- **Simple, iterative workflow**: Use aliases, fix failures one at a time

## Quick Start

```bash
# 1. Clone slopmop into your project
git submodule add https://github.com/ScienceIsNeato/slop-mop.git

# 2. Run interactive setup (auto-detects project type)
cd slopmop && pip install -e . && sm init

# 3. Run validation (use profiles, not gate lists!)
sm validate commit       # Fast commit validation ← USE THIS
sm validate pr           # Full PR validation
```

## AI Agent Workflow

**🤖 For AI coding assistants: This is the intended workflow.**

### The Simple Pattern

```bash
# Just run the profile - don't overthink it!
sm validate commit
```

That's it. When a check fails, slopmop tells you exactly what to do next:

```
┌──────────────────────────────────────────────────────────┐
│ 🤖 AI AGENT ITERATION GUIDANCE                           │
├──────────────────────────────────────────────────────────┤
│ Profile: commit                                          │
│ Failed Gate: python-coverage                             │
├──────────────────────────────────────────────────────────┤
│ NEXT STEPS:                                              │
│                                                          │
│ 1. Fix the issue described above                         │
│ 2. Validate: sm validate python-coverage                 │
│ 3. Resume:   sm validate commit                          │
│                                                          │
│ Keep iterating until all checks pass.                    │
└──────────────────────────────────────────────────────────┘
```

### What NOT to Do

```bash
# ❌ DON'T do this - it's verbose and misses the point
sm validate -g python:lint-format,python:static-analysis,python:tests,python:coverage

# ✅ DO this - simple, iterative, self-guiding
sm validate commit
```

### The Iteration Loop

1. **Run the profile**: `sm validate commit`
2. **See what fails**: Output shows exactly which gate failed
3. **Fix the issue**: Follow the guidance in the error output
4. **Validate the fix**: `sm validate <failed-gate>` (just that one gate)
5. **Resume the profile**: `sm validate commit` (to catch any remaining issues)
6. **Repeat until green**: Keep iterating until all checks pass

This fail-fast, iterative approach is faster than running everything, easier to reason about, and produces cleaner commits.

## Usage

The `sb` command uses a verb-based interface with **profiles** (not gate lists!):

```bash
# Validation - USE PROFILES
sm validate commit                    # ← Primary workflow (fast)
sm validate pr                        # ← Before opening/updating PR
sm validate quick                     # ← Ultra-fast lint only
sm validate python                    # ← Python-only validation
sm validate javascript                # ← JS-only validation

# For specific gates (rare - prefer profiles)
sm validate python-coverage           # Validate single gate
sm validate --self                    # Validate slopmop itself

# Setup commands
sm init                               # Interactive project setup
sm init --non-interactive             # Auto-configure with defaults

# Configuration commands
sm config --show                      # Show enabled gates and settings
sm config --enable python-security    # Enable a quality gate
sm config --disable js-tests          # Disable a quality gate

# Help commands
sm help                               # List all quality gates
sm help python-lint-format            # Detailed help for specific gate
sm help commit                        # Show what's in a profile
```

## Interactive Setup

The `sm init` command provides intelligent project configuration:

```bash
# Interactive mode (prompts for settings)
sm init

# Non-interactive mode (uses detected defaults)
sm init --non-interactive

# Pre-populated answers (for CI/automation)
sm init --config setup_config.json --non-interactive
```

### What it detects:

- **Python projects**: setup.py, pyproject.toml, requirements.txt, \*.py files
- **JavaScript projects**: package.json, tsconfig.json, _.js/_.ts files
- **Test frameworks**: pytest, Jest
- **Test directories**: tests/, test/, spec/, **tests**/

### Pre-populated config (setup_config.json):

```json
{
  "default_profile": "commit",
  "test_dirs": ["tests", "integration_tests"],
  "coverage_threshold": 80,
  "disabled_gates": ["python-security"]
}
```

## Available Quality Gates

### Python Gates

| Gate                       | Description                               |
| -------------------------- | ----------------------------------------- |
| `python-lint-format`       | 🎨 Code formatting (black, isort, flake8) |
| `python-static-analysis`   | 🔍 Type checking (mypy)                   |
| `python-tests`             | 🧪 Test execution (pytest)                |
| `python-coverage`          | 📊 Coverage analysis (80% threshold)      |
| `python-diff-coverage`     | 📊 Coverage on changed files only         |
| `python-new-code-coverage` | 📊 Coverage for new code in PR            |
| `python-complexity`        | 📐 Cyclomatic complexity (radon)          |
| `python-security`          | 🔒 Security scan (bandit, semgrep)        |
| `python-security-local`    | 🔒 Fast local security scan               |

### JavaScript Gates

| Gate             | Description                              |
| ---------------- | ---------------------------------------- |
| `js-lint-format` | 🎨 Linting/formatting (ESLint, Prettier) |
| `js-tests`       | 🧪 Test execution (Jest)                 |
| `js-coverage`    | 📊 Coverage analysis                     |
| `frontend-check` | 🖥️ Frontend validation                   |

### General Gates

| Gate                  | Description                           |
| --------------------- | ------------------------------------- |
| `duplication`         | 📋 Code duplication detection (jscpd) |
| `template-validation` | 📄 Template syntax validation         |
| `smoke-tests`         | 💨 Quick smoke tests                  |
| `integration-tests`   | 🔗 Integration tests                  |
| `e2e-tests`           | 🎭 End-to-end tests                   |

### Profiles (Quality Gate Groups)

| Profile      | Description            | Gates Included                                                     |
| ------------ | ---------------------- | ------------------------------------------------------------------ |
| `commit`     | Fast commit validation | lint, static-analysis, tests, coverage, complexity, security-local |
| `pr`         | Full PR validation     | All Python + JS gates                                              |
| `quick`      | Ultra-fast lint check  | lint, security-local                                               |
| `python`     | All Python gates       | All python-\* gates                                                |
| `javascript` | All JavaScript gates   | All js-\* gates + frontend                                         |
| `e2e`        | End-to-end tests       | smoke, integration, e2e                                            |

## Architecture

```
slopmop/
├── setup.py                    # Package setup
├── slopmop/
│   ├── sb.py                   # CLI entry point (verb-based)
│   ├── core/
│   │   ├── executor.py         # Parallel check execution
│   │   ├── registry.py         # Check registration
│   │   └── result.py           # Result types
│   ├── checks/
│   │   ├── base.py             # Abstract base class
│   │   ├── python/             # Python checks
│   │   ├── javascript/         # JavaScript checks
│   │   └── general/            # Language-agnostic checks
│   ├── subprocess/
│   │   ├── validator.py        # Command security (allowlist)
│   │   └── runner.py           # Secure execution
│   └── reporting/
│       └── console.py          # Output formatting
└── tests/                      # Test suite
```

## Security

slopmop uses a whitelist-based security model for subprocess execution:

- Only known, safe executables can be run (python, npm, black, etc.)
- No shell=True execution
- All arguments are validated for injection patterns
- Add custom executables via configuration if needed

## Configuration

slopmop works out of the box with **zero required configuration**.

Configuration is stored in `.sb_config.json` in your project root:

```json
{
  "version": "1.0",
  "default_profile": "commit",

  "python": {
    "enabled": true,
    "include_dirs": ["src"],
    "gates": {
      "lint-format": { "enabled": true },
      "tests": { "enabled": true, "test_dirs": ["tests"] },
      "coverage": { "enabled": true, "threshold": 80 }
    }
  }
}
```

Use `sm config` to view and update settings:

- `sm config --show` - View current configuration
- `sm config --enable python-security` - Enable a gate
- `sm config --disable js-tests` - Disable a gate
- `sm config --json myconfig.json` - Load config from file

## Adding Custom Checks

```python
from slopmop.checks.base import BaseCheck
from slopmop.core.result import CheckResult, CheckStatus
from slopmop.core.registry import register_check

@register_check
class MyCustomCheck(BaseCheck):
    @property
    def name(self) -> str:
        return "my-check"

    @property
    def display_name(self) -> str:
        return "🔧 My Custom Check"

    def is_applicable(self, project_root: str) -> bool:
        return True  # Or check for specific files

    def run(self, project_root: str) -> CheckResult:
        # Your check logic here
        return CheckResult(
            name=self.name,
            status=CheckStatus.PASSED,
            duration=0.1,
            output="Check passed!"
        )
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run self-validation (slopmop validates itself!)
sm validate --self
```

## Migration from ship_it.py

See [MIGRATION_AND_REFACTOR_PLANNING.md](MIGRATION_AND_REFACTOR_PLANNING.md) for the complete migration guide from the original `ship_it.py` and `maintAInability-gate.sh` implementation.

## License

MIT
