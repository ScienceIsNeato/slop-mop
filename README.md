# 🪣 slopbucket

**AI-Focused Quality Gate Framework**

A language-agnostic, bolt-on code validation tool designed to catch AI-generated slop before it lands in your codebase. Provides fast, actionable feedback for both human developers and AI coding assistants.

## Philosophy

- **Fail fast**: Stop at the first failure to save time
- **Maximum value, minimum time**: Prioritize quick, high-impact checks
- **AI-friendly output**: Clear errors with exact fixes
- **Zero configuration required**: Works out of the box

## Quick Start

```bash
# 1. Clone slopbucket into your project
git submodule add https://github.com/ScienceIsNeato/slopbucket.git

# 2. Run setup (auto-configures for your project)
cd slopbucket && python setup.py

# 3. Run validation
sb validate              # Full suite
sb validate commit       # Fast commit validation
sb validate pr --verbose # PR validation with details
```

## Usage

The `sb` command uses a verb-based interface:

```bash
# Validate commands
sb validate                           # Run full validation suite
sb validate commit                    # Run commit profile (fast)
sb validate pr                        # Run PR profile (thorough)
sb validate --quality-gates python-tests,python-coverage
sb validate --self                    # Validate slopbucket itself

# Configuration commands
sb config --show                      # Show enabled gates and settings
sb config --enable python-security    # Enable a quality gate
sb config --disable js-tests          # Disable a quality gate
sb config --json config.json          # Update config from JSON file

# Help commands
sb help                               # List all quality gates
sb help python-lint-format            # Detailed help for specific gate
sb help commit                        # Show what's in a profile
```

## Available Quality Gates

### Python Gates

| Gate | Description |
|------|-------------|
| `python-lint-format` | 🎨 Code formatting (black, isort, flake8) |
| `python-static-analysis` | 🔍 Type checking (mypy) |
| `python-tests` | 🧪 Test execution (pytest) |
| `python-coverage` | 📊 Coverage analysis (80% threshold) |
| `python-diff-coverage` | 📊 Coverage on changed files only |
| `python-new-code-coverage` | 📊 Coverage for new code in PR |
| `python-complexity` | 📐 Cyclomatic complexity (radon) |
| `python-security` | 🔒 Security scan (bandit, semgrep) |
| `python-security-local` | 🔒 Fast local security scan |

### JavaScript Gates

| Gate | Description |
|------|-------------|
| `js-lint-format` | 🎨 Linting/formatting (ESLint, Prettier) |
| `js-tests` | 🧪 Test execution (Jest) |
| `js-coverage` | 📊 Coverage analysis |
| `frontend-check` | 🖥️ Frontend validation |

### General Gates

| Gate | Description |
|------|-------------|
| `duplication` | 📋 Code duplication detection (jscpd) |
| `template-validation` | 📄 Template syntax validation |
| `smoke-tests` | 💨 Quick smoke tests |
| `integration-tests` | 🔗 Integration tests |
| `e2e-tests` | 🎭 End-to-end tests |

### Profiles (Quality Gate Groups)

| Profile | Description | Gates Included |
|---------|-------------|----------------|
| `commit` | Fast commit validation | lint, static-analysis, tests, coverage, complexity, security-local |
| `pr` | Full PR validation | All Python + JS gates |
| `quick` | Ultra-fast lint check | lint, security-local |
| `python` | All Python gates | All python-* gates |
| `javascript` | All JavaScript gates | All js-* gates + frontend |
| `e2e` | End-to-end tests | smoke, integration, e2e |

## Architecture

```
slopbucket/
├── setup.py                    # Interactive setup + setuptools
├── slopbucket/
│   ├── sb.py                   # sb CLI (verb-based interface)
│   ├── cli.py                  # Legacy CLI (--checks style)
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
└── tests/                      # Test suite (191 tests, 80% coverage)
```

## Security

slopbucket uses a whitelist-based security model for subprocess execution:

- Only known, safe executables can be run (python, npm, black, etc.)
- No shell=True execution
- All arguments are validated for injection patterns
- Add custom executables via configuration if needed

## Configuration

slopbucket works out of the box with **zero required configuration**.

Configuration is stored in `slopbucket.json` in your project root:

```json
{
  "disabled_gates": ["js-tests"],
  "paths": {
    "tests": "tests/",
    "src": "src/"
  },
  "thresholds": {
    "coverage": 80,
    "complexity": "C"
  }
}
```

Use `sb config` to view and update settings:
- `sb config --show` - View current configuration
- `sb config --enable python-security` - Enable a gate
- `sb config --disable js-tests` - Disable a gate
- `sb config --json myconfig.json` - Load config from file

## Adding Custom Checks

```python
from slopbucket.checks.base import BaseCheck
from slopbucket.core.result import CheckResult, CheckStatus
from slopbucket.core.registry import register_check

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

# Run self-validation (slopbucket validates itself!)
python setup.py --checks commit
```

## Migration from ship_it.py

See [MIGRATION_AND_REFACTOR_PLANNING.md](MIGRATION_AND_REFACTOR_PLANNING.md) for the complete migration guide from the original `ship_it.py` and `maintAInability-gate.sh` implementation.

## License

MIT
