"""Configuration management for slopmop quality gates.

This module provides:
- Config loading and validation
- Per-category configuration with sub-gates
- Directory validation (include/exclude)
- Threshold validation

Config structure (.sb_config.json):
{
  "version": "1.0",
  "default_profile": "commit",
  "overconfidence": {
    "enabled": true,
    "include_dirs": ["src"],
    "gates": {
      "py-tests": { "enabled": true },
      "py-types": { "enabled": true }
    }
  }
}
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, cast

# Single source of truth for GateCategory — re-export from checks.base
from slopmop.checks.base import GateCategory  # noqa: F401

logger = logging.getLogger(__name__)

# Config file name
CONFIG_FILE = ".sb_config.json"


class ConfigError(Exception):
    """Raised when configuration is invalid."""

    def __init__(self, message: str, fix_suggestion: Optional[str] = None):
        super().__init__(message)
        self.fix_suggestion = fix_suggestion


# Directories that should always be excluded from scanning
ALWAYS_EXCLUDE: Set[str] = {
    ".venv",
    "venv",
    ".env",
    "env",
    "node_modules",
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    "dist",
    "build",
    ".tox",
    ".nox",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "htmlcov",
    ".coverage",
    "*.egg-info",
    ".eggs",
}


@dataclass
class GateConfig:
    """Configuration for a single quality gate within a language."""

    enabled: bool = False

    # Gate-specific settings (optional, depend on gate type)
    threshold: Optional[int] = None  # For coverage gates
    max_rank: Optional[str] = None  # For complexity (A-F)
    max_complexity: Optional[int] = None  # Numeric complexity limit
    test_dirs: Optional[List[str]] = None  # For test-related gates
    templates_dir: Optional[str] = None  # For template validation
    frontend_dirs: Optional[List[str]] = None  # For frontend checks
    scanner: Optional[str] = None  # For security (bandit/semgrep)
    test_command: Optional[str] = None  # For custom test commands
    include_dirs: Optional[List[str]] = None  # Override language include_dirs

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GateConfig":
        """Create GateConfig from dictionary."""
        return cls(
            enabled=data.get("enabled", False),
            threshold=data.get("threshold"),
            max_rank=data.get("max_rank"),
            max_complexity=data.get("max_complexity"),
            test_dirs=data.get("test_dirs"),
            templates_dir=data.get("templates_dir"),
            frontend_dirs=data.get("frontend_dirs"),
            scanner=data.get("scanner"),
            test_command=data.get("test_command"),
            include_dirs=data.get("include_dirs"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, omitting None values."""
        result: Dict[str, Any] = {"enabled": self.enabled}
        if self.threshold is not None:
            result["threshold"] = self.threshold
        if self.max_rank is not None:
            result["max_rank"] = self.max_rank
        if self.max_complexity is not None:
            result["max_complexity"] = self.max_complexity
        if self.test_dirs is not None:
            result["test_dirs"] = self.test_dirs
        if self.templates_dir is not None:
            result["templates_dir"] = self.templates_dir
        if self.frontend_dirs is not None:
            result["frontend_dirs"] = self.frontend_dirs
        if self.scanner is not None:
            result["scanner"] = self.scanner
        if self.test_command is not None:
            result["test_command"] = self.test_command
        if self.include_dirs is not None:
            result["include_dirs"] = self.include_dirs
        return result


@dataclass
class CategoryConfig:
    """Configuration for a flaw category (overconfidence, laziness, etc.)."""

    enabled: bool = False
    include_dirs: List[str] = field(default_factory=lambda: cast(List[str], []))
    exclude_dirs: List[str] = field(default_factory=lambda: cast(List[str], []))
    gates: Dict[str, GateConfig] = field(
        default_factory=lambda: cast(Dict[str, GateConfig], {})
    )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CategoryConfig":
        """Create CategoryConfig from dictionary."""
        gates: Dict[str, GateConfig] = {}
        gates_data = cast(Dict[str, Any], data.get("gates", {}))
        for gate_name, gate_data in gates_data.items():
            if isinstance(gate_data, dict):
                gates[gate_name] = GateConfig.from_dict(cast(Dict[str, Any], gate_data))

        include_dirs: List[str] = cast(List[str], data.get("include_dirs", []))
        exclude_dirs: List[str] = cast(List[str], data.get("exclude_dirs", []))

        return cls(
            enabled=data.get("enabled", False),
            include_dirs=include_dirs,
            exclude_dirs=exclude_dirs,
            gates=gates,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: Dict[str, Any] = {
            "enabled": self.enabled,
            "include_dirs": self.include_dirs,
        }
        if self.exclude_dirs:
            result["exclude_dirs"] = self.exclude_dirs
        if self.gates:
            result["gates"] = {
                name: gate.to_dict() for name, gate in self.gates.items()
            }
        return result

    def get_gate_config(self, gate_name: str) -> GateConfig:
        """Get configuration for a specific gate."""
        return self.gates.get(gate_name, GateConfig())

    def is_gate_enabled(self, gate_name: str) -> bool:
        """Check if a specific gate is enabled (requires language enabled too)."""
        if not self.enabled:
            return False
        return self.get_gate_config(gate_name).enabled


# Backward-compatible alias
LanguageConfig = CategoryConfig


@dataclass
class SlopmopConfig:
    """Top-level slopmop configuration.

    Categories are stored dynamically — any GateCategory key
    (overconfidence, deceptiveness, laziness, myopia, pr, general)
    is looked up from the categories dict rather than hardcoded fields.
    """

    version: str = "1.0"
    default_profile: str = "commit"
    categories: Dict[str, CategoryConfig] = field(
        default_factory=lambda: cast(Dict[str, CategoryConfig], {})
    )
    profiles: Dict[str, List[str]] = field(
        default_factory=lambda: cast(Dict[str, List[str]], {})
    )

    @classmethod
    def load(cls, project_root: str) -> "SlopmopConfig":
        """Load configuration from .sb_config.json.

        Args:
            project_root: Path to project root directory

        Returns:
            SlopmopConfig instance (empty defaults if no config file)
        """
        config_path = Path(project_root) / CONFIG_FILE

        if not config_path.exists():
            logger.debug(f"No {CONFIG_FILE} found, using defaults")
            return cls()

        try:
            data = json.loads(config_path.read_text())
            return cls.from_dict(data)
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in {CONFIG_FILE}: {e}")
            return cls()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SlopmopConfig":
        """Create config from dictionary.

        Any key that matches a GateCategory key is loaded as a
        CategoryConfig.  Non-category keys (version, default_profile,
        profiles, disabled_gates, etc.) are handled separately.
        """
        category_keys = {cat.key for cat in GateCategory}
        categories: Dict[str, CategoryConfig] = {}

        for key, value in data.items():
            if key in category_keys and isinstance(value, dict):
                categories[key] = CategoryConfig.from_dict(cast(Dict[str, Any], value))

        return cls(
            version=data.get("version", "1.0"),
            default_profile=data.get("default_profile", "commit"),
            categories=categories,
            profiles=data.get("profiles", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: Dict[str, Any] = {
            "version": self.version,
            "default_profile": self.default_profile,
        }
        for key, cat_config in self.categories.items():
            if cat_config.enabled or cat_config.gates:
                result[key] = cat_config.to_dict()
        if self.profiles:
            result["profiles"] = self.profiles
        return result

    def save(self, project_root: str) -> None:
        """Save configuration to .sb_config.json."""
        config_path = Path(project_root) / CONFIG_FILE
        config_path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
        logger.info(f"Configuration saved to {config_path}")

    def get_category_config(self, category_key: str) -> CategoryConfig:
        """Get configuration for a flaw category."""
        return self.categories.get(category_key, CategoryConfig())

    # Backward-compatible alias
    get_language_config = get_category_config

    def is_gate_enabled(self, category_key: str, gate_name: str = "") -> bool:
        """Check if a gate is enabled (category:gate format or separate args)."""
        if ":" in category_key:
            category_key, gate_name = category_key.split(":", 1)
        cat_config = self.get_category_config(category_key)
        return cat_config.is_gate_enabled(gate_name)

    def get_gate_include_dirs(self, category_key: str, gate_name: str) -> List[str]:
        """Get include_dirs for a gate, with fallback to category level."""
        cat_config = self.get_category_config(category_key)
        gate_config = cat_config.get_gate_config(gate_name)
        if gate_config.include_dirs:
            return gate_config.include_dirs
        return cat_config.include_dirs

    def get_gate_exclude_dirs(self, category_key: str) -> List[str]:
        """Get exclude_dirs for a category (merged with always-exclude)."""
        cat_config = self.get_category_config(category_key)
        return list(ALWAYS_EXCLUDE) + cat_config.exclude_dirs


def validate_include_dirs(
    gate_name: str,
    include_dirs: List[str],
    project_root: str,
) -> List[str]:
    """Validate and resolve include directories.

    Args:
        gate_name: Name of the gate in "language:gate" format
        include_dirs: Configured include directories
        project_root: Project root path

    Returns:
        List of validated, existing directories

    Raises:
        ConfigError: If include_dirs is empty
    """
    if not include_dirs:
        # Parse category from gate_name (e.g., "laziness:py-lint" -> "laziness")
        category = gate_name.split(":")[0] if ":" in gate_name else gate_name
        raise ConfigError(
            f"{gate_name}: No include_dirs configured",
            fix_suggestion=(
                f'Run "./sm init" to configure, or add to .sb_config.json:\n'
                f'  "{category}": {{ "include_dirs": ["src"] }}'
            ),
        )

    valid_dirs: List[str] = []
    for dir_path in include_dirs:
        full_path = Path(project_root) / dir_path
        if full_path.is_dir():
            valid_dirs.append(dir_path)
        else:
            logger.warning(f"{gate_name}: include_dir '{dir_path}' does not exist")

    if not valid_dirs:
        raise ConfigError(
            f"{gate_name}: None of the configured include_dirs exist",
            fix_suggestion=f"Configured dirs: {include_dirs}. Check paths in .sb_config.json.",
        )

    return valid_dirs


def validate_exclude_dirs(
    gate_name: str,
    exclude_dirs: List[str],
    include_dirs: List[str],
    project_root: str,
) -> List[str]:
    """Validate exclude directories are subsets of include directories.

    Args:
        gate_name: Name of the gate (for warnings)
        exclude_dirs: Configured exclude directories
        include_dirs: Configured include directories
        project_root: Project root path

    Returns:
        List of valid exclude patterns (with warnings for non-matching)
    """
    # Add always-excluded dirs
    all_excludes = list(ALWAYS_EXCLUDE) + exclude_dirs

    # Check if exclude dirs make sense relative to include dirs
    for exclude in exclude_dirs:
        found_match = False
        for include in include_dirs:
            # Check if exclude is under include or matches a pattern
            include_path = Path(project_root) / include
            exclude_path = Path(project_root) / exclude

            if exclude_path.is_relative_to(include_path) or include == ".":
                found_match = True
                break

        if not found_match:
            logger.warning(
                f"{gate_name}: exclude_dir '{exclude}' is not under any include_dir. "
                f"Filter may have no effect."
            )

    return all_excludes


def validate_threshold(
    gate_name: str,
    value: Optional[int],
    default: int,
    min_val: int = 0,
    max_val: int = 100,
) -> int:
    """Validate a numeric threshold.

    Args:
        gate_name: Name of the gate (for error messages)
        value: Configured threshold value
        default: Default value if not configured
        min_val: Minimum allowed value
        max_val: Maximum allowed value

    Returns:
        Validated threshold value

    Raises:
        ConfigError: If threshold is out of range
    """
    if value is None:
        return default

    if not isinstance(value, int):
        raise ConfigError(
            f"{gate_name}: threshold must be an integer, got {type(value).__name__}",
            fix_suggestion=f"Set threshold to a number between {min_val} and {max_val}",
        )

    if not min_val <= value <= max_val:
        raise ConfigError(
            f"{gate_name}: threshold {value} out of range [{min_val}-{max_val}]",
            fix_suggestion=f"Set threshold between {min_val} and {max_val}",
        )

    return value


def validate_complexity_rank(gate_name: str, rank: Optional[str]) -> str:
    """Validate complexity rank (A-F).

    Args:
        gate_name: Name of the gate
        rank: Configured rank

    Returns:
        Validated rank (uppercase)

    Raises:
        ConfigError: If rank is invalid
    """
    valid_ranks = {"A", "B", "C", "D", "E", "F"}
    default = "C"

    if rank is None:
        return default

    rank_upper = rank.upper()
    if rank_upper not in valid_ranks:
        raise ConfigError(
            f"{gate_name}: invalid max_rank '{rank}'",
            fix_suggestion=f"Valid ranks are: {', '.join(sorted(valid_ranks))}",
        )

    return rank_upper
