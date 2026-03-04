"""Configuration management for slopmop quality gates.

This module provides:
- Config loading and validation
- Per-category configuration with sub-gates
- Threshold validation

Config structure (.sb_config.json):
{
  "version": "1.0",
  "overconfidence": {
    "enabled": true,
    "gates": {
      "untested-code.py": { "enabled": true },
      "type-blindness.py": { "enabled": true }
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

        return cls(
            enabled=data.get("enabled", False),
            gates=gates,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: Dict[str, Any] = {
            "enabled": self.enabled,
        }
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
    categories: Dict[str, CategoryConfig] = field(
        default_factory=lambda: cast(Dict[str, CategoryConfig], {})
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
        CategoryConfig.  Non-category keys (version, disabled_gates,
        etc.) are handled separately.
        """
        category_keys = {cat.key for cat in GateCategory}
        categories: Dict[str, CategoryConfig] = {}

        for key, value in data.items():
            if key in category_keys and isinstance(value, dict):
                categories[key] = CategoryConfig.from_dict(cast(Dict[str, Any], value))

        return cls(
            version=data.get("version", "1.0"),
            categories=categories,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: Dict[str, Any] = {
            "version": self.version,
        }
        for key, cat_config in self.categories.items():
            if cat_config.enabled or cat_config.gates:
                result[key] = cat_config.to_dict()
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
