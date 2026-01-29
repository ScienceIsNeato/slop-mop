# Gate Architecture Design

## 🍷 Strategic Overview

This document outlines the restructuring of slopbucket's quality gate system to be:
1. Config-first (no magic directory guessing)
2. Language-organized (clear taxonomy)
3. Dependency-aware (first-class `depends_on`)
4. Hierarchically displayable (collapsible-style UX in CLI)

## Current State

### Existing Checks

| Category | Check | Dependencies | Config Needs |
|----------|-------|--------------|--------------|
| **Python** | python-lint-format | none | include_dirs, exclude_dirs |
| | python-static-analysis | python-lint-format | include_dirs, exclude_dirs |
| | python-tests | python-lint-format | test_dirs |
| | python-coverage | python-tests | test_dirs, threshold |
| | python-complexity | none | include_dirs, max_rank |
| | python-security | none | include_dirs, scanner |
| | python-test-types | none | test_dirs |
| **JavaScript** | js-lint-format | none | include_dirs, exclude_dirs |
| | js-tests | js-lint-format | test_dirs |
| | js-coverage | js-tests | test_dirs, threshold |
| | frontend-check | none | frontend_dirs |
| **General** | template-validation | none | templates_dir |
| | duplication | none | include_dirs, threshold |
| **Meta** | smoke-tests | none | test_dirs |
| | integration-tests | smoke-tests | test_dirs |
| | e2e-tests | integration-tests | test_command |

## Proposed Config Schema

### .sb_config.json Structure

```json
{
  "version": "1.0",
  "default_profile": "commit",

  "python": {
    "enabled": true,
    "include_dirs": ["src", "slopbucket"],
    "exclude_dirs": [],
    "gates": {
      "lint-format": { "enabled": true },
      "static-analysis": { "enabled": true },
      "tests": { "enabled": true, "test_dirs": ["tests"] },
      "coverage": { "enabled": true, "threshold": 80 },
      "complexity": { "enabled": false, "max_rank": "C", "max_complexity": 15 },
      "security": { "enabled": false, "scanner": "bandit" }
    }
  },

  "javascript": {
    "enabled": false,
    "include_dirs": [],
    "exclude_dirs": ["node_modules"],
    "gates": {
      "lint-format": { "enabled": false },
      "tests": { "enabled": false },
      "coverage": { "enabled": false, "threshold": 70 },
      "frontend": { "enabled": false, "frontend_dirs": [] }
    }
  },

  "general": {
    "enabled": false,
    "gates": {
      "templates": { "enabled": false, "templates_dir": null },
      "duplication": { "enabled": false, "include_dirs": ["."], "threshold": 5 }
    }
  },

  "profiles": {
    "commit": ["python:lint-format", "python:tests", "python:coverage"],
    "pr": ["all"],
    "quick": ["python:lint-format"]
  }
}
```

### Gate Naming Convention

Gates are now namespaced by language: `python:lint-format`, `javascript:tests`, `general:templates`

### Config Resolution

1. Gate-specific config (highest priority)
2. Language-level include_dirs/exclude_dirs
3. Built-in fallbacks (safe defaults - everything disabled)

### Validation Rules

1. **include_dirs required**: If gate uses include_dirs and none configured → ERROR
   ```
   ❌ python:lint-format: No include_dirs configured.
   💡 Add to .sb_config.json: "python": { "include_dirs": ["src"] }
   ```

2. **exclude_dirs subset check**: If exclude dir not under include dir → WARNING
   ```
   ⚠️  Exclude pattern 'vendor/' doesn't match any include_dirs. Filter will have no effect.
   ```

3. **threshold validation**: Numeric thresholds must be valid ranges
   ```
   ❌ python-coverage: Invalid threshold 150. Must be 0-100.
   ```

## Dependency System

### depends_on Semantics

```python
class PythonCoverageCheck(BaseCheck):
    @property
    def depends_on(self) -> List[str]:
        return ["python-tests"]  # Won't run if tests fail
```

### Execution Order

```
                 ┌─────────────────────┐
                 │   python-lint-format │
                 └──────────┬──────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
   ┌──────────────────┐ ┌───────┐ ┌───────────────┐
   │static-analysis   │ │ tests │ │   complexity  │
   └──────────────────┘ └───┬───┘ └───────────────┘
                            │
                            ▼
                     ┌──────────┐
                     │ coverage │
                     └──────────┘
```

### Fail-Fast Behavior

When a dependency fails:
1. All dependents are marked SKIPPED (not ERROR)
2. Reason clearly stated: "Skipped: dependency 'python-tests' failed"
3. Other independent checks continue running

## Language Categories

### Taxonomy

```
sb help
├── 🐍 Python
│   ├── python-lint-format     🎨 Code formatting (black, isort, flake8)
│   ├── python-static-analysis 🔍 Type checking (mypy)
│   ├── python-tests          🧪 Test execution (pytest)
│   ├── python-coverage       📊 Coverage analysis
│   ├── python-complexity     🌀 Cyclomatic complexity
│   ├── python-security       🔒 Security scanning
│   └── python-test-types     📝 Test type hints
│
├── 📦 JavaScript
│   ├── js-lint-format        🎨 Linting (ESLint, Prettier)
│   ├── js-tests              🧪 Test execution (Jest)
│   ├── js-coverage           📊 Coverage analysis
│   └── frontend-check        ⚡ Quick frontend validation
│
├── 🔧 General
│   ├── template-validation   📄 Jinja2 syntax checking
│   └── duplication           📋 Code duplication detection
│
└── 🎭 Integration
    ├── smoke-tests           💨 Quick smoke tests
    ├── integration-tests     🔗 Integration tests
    └── e2e-tests             🎭 End-to-end tests
```

### Category Metadata

```python
class CheckCategory(Enum):
    PYTHON = ("python", "🐍", "Python")
    JAVASCRIPT = ("javascript", "📦", "JavaScript")
    GENERAL = ("general", "🔧", "General")
    INTEGRATION = ("integration", "🎭", "Integration")
```

## BaseCheck Changes

### New Properties

```python
class BaseCheck(ABC):
    @property
    @abstractmethod
    def category(self) -> str:
        """Category: 'python', 'javascript', 'general', 'integration'"""
        pass
    
    @property
    def config_schema(self) -> Dict[str, Any]:
        """JSON Schema for this check's config options."""
        return {}
    
    def validate_config(self, project_root: str) -> Optional[str]:
        """Validate config. Return error message or None if valid."""
        return None
```

### Config Helper Methods

```python
def get_include_dirs(self, project_root: str) -> List[str]:
    """Get include dirs from config, with validation."""
    dirs = self.config.get("include_dirs") or self.config.get("defaults", {}).get("include_dirs")
    if not dirs:
        raise ConfigError(f"{self.name}: No include_dirs configured")
    return [d for d in dirs if os.path.isdir(os.path.join(project_root, d))]

def get_exclude_dirs(self, project_root: str) -> List[str]:
    """Get exclude dirs, validating they're subsets of include dirs."""
    include_dirs = self.get_include_dirs(project_root)
    exclude_dirs = self.config.get("exclude_dirs", [])
    # Warn about non-matching excludes
    return exclude_dirs

def get_threshold(self, key: str, default: int, min_val: int = 0, max_val: int = 100) -> int:
    """Get numeric threshold with validation."""
    value = self.config.get(key, default)
    if not min_val <= value <= max_val:
        raise ConfigError(f"{self.name}: {key}={value} must be {min_val}-{max_val}")
    return value
```

## Implementation Plan

### Phase 1: Config Schema & Validation
1. Create `slopbucket/core/config.py` with schema and validation
2. Add config loading to sb.py
3. Update BaseCheck with config helpers

### Phase 2: Check Categories
1. Add `category` property to all checks
2. Create category enum/registry
3. Update display helpers

### Phase 3: CLI Display
1. Update `sb help` for hierarchical display
2. Update `sb config --show` for category grouping
3. Add `sb help <category>` support

### Phase 4: Validation Integration
1. Wire up config validation before check execution
2. Implement include_dirs/exclude_dirs validation
3. Add threshold validation

## Open Questions

### Resolved ✅

1. **Custom profiles**: Defer for later. Built-in profiles (commit, pr, quick) are sufficient for now.

2. **Discovery behavior**: No auto-discovery when new checks are added to codebase. Auto-discovery **only** happens during `sb init`. Adding new gates to an existing project is a manual config step.

3. **Include_dirs defaults**: Everything comes **disabled by default** with `include_dirs: null`. 
   - `sb init` uses canonical language-specific detection
   - Never default to `.` - could accidentally scan terabyte filesystems
   - Explicit > implicit

### Design Principles (Updated)

1. **Nothing runs until configured**: All gates disabled by default
2. **Setup does discovery**: `sb init` is the only auto-detection point  
3. **Safe defaults**: `enabled: false, include_dirs: null`
4. **Canonical detection**: Per-language smart discovery in setup only
   - Python: Look for setup.py, pyproject.toml, src/, then scan for .py files
   - JavaScript: Look for package.json, then find src/app/lib with .js/.ts
   - Ignore: .venv, venv, node_modules, __pycache__, .git, dist, build
5. **Fail-safe validation**: Running unconfigured gate = ERROR with clear fix instructions
