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
# Clone as a submodule
git submodule add https://github.com/ScienceIsNeato/slopbucket.git

# Run commit validation
python slopbucket/setup.py --checks commit

# Or install globally
cd slopbucket && pip install -e .
slopbucket --checks commit
```

## Usage

```bash
# Run fast commit validation
python setup.py --checks commit

# Run full PR validation (all checks)
python setup.py --checks pr

# Run specific checks
python setup.py --checks python-lint-format python-tests

# List all available checks
python setup.py --list-checks

# List all check aliases
python setup.py --list-aliases

# Get help
python setup.py --help
```

## Available Checks

### Python Checks

| Check | Description |
|-------|-------------|
| `python-lint-format` | 🎨 Code formatting with black, isort, flake8 |
| `python-static-analysis` | 🔍 Type checking with mypy |
| `python-tests` | 🧪 Test execution with pytest |
| `python-coverage` | 📊 Coverage analysis (80% threshold) |

### JavaScript Checks

| Check | Description |
|-------|-------------|
| `js-lint-format` | 🎨 Linting/formatting with ESLint, Prettier |
| `js-tests` | 🧪 Test execution with Jest |

### Check Aliases

| Alias | Checks Included |
|-------|-----------------|
| `commit` | python-lint-format, python-static-analysis, python-tests, python-coverage |
| `pr` | All checks |
| `quick` | python-lint-format only |
| `python` | All Python checks |
| `javascript` | All JavaScript checks |

## Architecture

```
slopbucket/
├── setup.py                    # Entry point
├── slopbucket/                 # Main package
│   ├── cli.py                  # Command-line interface
│   ├── core/
│   │   ├── executor.py         # Parallel check execution
│   │   ├── registry.py         # Check registration
│   │   └── result.py           # Result types
│   ├── checks/                 # Check implementations
│   │   ├── base.py             # Abstract base class
│   │   ├── python/             # Python checks
│   │   └── javascript/         # JavaScript checks
│   ├── subprocess/
│   │   ├── validator.py        # Command security
│   │   └── runner.py           # Secure execution
│   └── reporting/
│       └── console.py          # Output formatting
└── tests/                      # Test suite
```

## Security

slopbucket uses a whitelist-based security model for subprocess execution:

- Only known, safe executables can be run (python, npm, black, etc.)
- No shell=True execution
- All arguments are validated for injection patterns
- Add custom executables via configuration if needed

## Configuration

Create a `slopbucket.toml` in your project root:

```toml
[slopbucket]
version = "1.0.0"

[checks]
enabled = ["python-lint-format", "python-tests"]

[checks.python-coverage]
threshold = 80

[aliases]
my-check = ["python-lint-format", "python-tests"]
```

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
