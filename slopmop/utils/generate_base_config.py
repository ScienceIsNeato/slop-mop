"""Generate base configuration from check class introspection.

This module implements the IaC (Infrastructure as Code) pattern for slopmop
configuration. The check classes themselves are the source of truth - this
utility introspects them to generate valid configuration files.

Usage:
    python -m slopmop.utils.generate_base_config [output_path]
"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import all checks to ensure they're registered
# noqa: E402 - must come after registry import
from slopmop.checks import ensure_checks_registered  # noqa: E402
from slopmop.checks.base import BaseCheck, ConfigField, GateCategory
from slopmop.core.config import CONFIG_FILE
from slopmop.core.registry import CheckRegistry, get_registry

logger = logging.getLogger(__name__)


def _config_field_to_default(field: ConfigField) -> Any:
    """Convert a ConfigField to its default value for JSON output."""
    return field.default


def _config_field_to_schema(field: ConfigField) -> Dict[str, Any]:
    """Convert a ConfigField to a JSON schema entry (for documentation)."""
    schema: Dict[str, Any] = {
        "type": field.field_type,
        "default": field.default,
        "description": field.description,
    }

    if field.required:
        schema["required"] = True
    if field.min_value is not None:
        schema["min"] = field.min_value
    if field.max_value is not None:
        schema["max"] = field.max_value
    if field.choices:
        schema["choices"] = field.choices

    return schema


def generate_gate_config(check: BaseCheck) -> Dict[str, Any]:
    """Generate configuration section for a single gate.

    Args:
        check: The check instance to generate config for

    Returns:
        Dict with all config fields set to their defaults
    """
    config: Dict[str, Any] = {}

    for field in check.get_full_config_schema():
        config[field.name] = field.default

    return config


# Always exclude slop-mop from its own checks when used as a submodule
DEFAULT_EXCLUDE_DIRS = ["slop-mop"]


def generate_language_config(
    checks: List[BaseCheck],
    category: GateCategory,
) -> Dict[str, Any]:
    """Generate configuration section for a language/category.

    Args:
        checks: List of checks belonging to this category
        category: The GateCategory

    Returns:
        Dict with language-level and gate-level config
    """
    language_config: Dict[str, Any] = {
        "enabled": False,  # Disabled by default
        "include_dirs": [],
        "exclude_dirs": DEFAULT_EXCLUDE_DIRS.copy(),
        "gates": {},
    }

    for check in checks:
        gate_name = check.name
        language_config["gates"][gate_name] = generate_gate_config(check)

    return language_config


def generate_base_config(registry: Optional[CheckRegistry] = None) -> Dict[str, Any]:
    """Generate complete base configuration from registry introspection.

    Args:
        registry: Optional registry to use (defaults to global registry)

    Returns:
        Complete configuration dictionary
    """
    if registry is None:
        # Ensure all checks are registered (idempotent)
        ensure_checks_registered()
        registry = get_registry()

    config: Dict[str, Any] = {
        "version": "1.0",
        "default_profile": "commit",
    }

    # Group checks by category
    checks_by_category: Dict[GateCategory, List[BaseCheck]] = {
        cat: [] for cat in GateCategory
    }

    # Instantiate all registered checks and group by category
    for name, check_class in registry._check_classes.items():
        try:
            check_instance = check_class({})
            checks_by_category[check_instance.category].append(check_instance)
        except Exception as e:
            logger.warning(f"Failed to instantiate check '{name}': {e}")

    # Generate config for each category
    for category in GateCategory:
        checks = checks_by_category[category]
        if checks:
            config[category.key] = generate_language_config(checks, category)

    return config


def generate_config_schema(registry: Optional[CheckRegistry] = None) -> Dict[str, Any]:
    """Generate JSON schema documentation for the config file.

    This is useful for validation and documentation purposes.

    Args:
        registry: Optional registry to use (defaults to global registry)

    Returns:
        JSON schema dictionary
    """
    if registry is None:
        ensure_checks_registered()
        registry = get_registry()

    # Build schema structure
    gate_schemas: Dict[str, Dict[str, Any]] = {}

    for name, check_class in registry._check_classes.items():
        try:
            check_instance = check_class({})
            gate_schemas[check_instance.full_name] = {
                "display_name": check_instance.display_name,
                "category": check_instance.category.display,
                "depends_on": check_instance.depends_on,
                "can_auto_fix": check_instance.can_auto_fix(),
                "fields": {
                    field.name: _config_field_to_schema(field)
                    for field in check_instance.get_full_config_schema()
                },
            }
        except Exception as e:
            logger.warning(f"Failed to get schema for '{name}': {e}")

    return gate_schemas


def backup_config(config_path: Path) -> Optional[Path]:
    """Create a backup of existing config file.

    Args:
        config_path: Path to the config file

    Returns:
        Path to backup file, or None if no backup was needed
    """
    if not config_path.exists():
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = config_path.parent / f".sb_config.json.backup.{timestamp}"

    shutil.copy2(config_path, backup_path)
    logger.info(f"Backed up existing config to: {backup_path}")

    return backup_path


def generate_template_config(
    registry: Optional[CheckRegistry] = None,
) -> Dict[str, Any]:
    """Generate template configuration with all gates disabled.

    This creates a .sb_config.json.template file that shows all available
    configuration options. This file should be committed to git.

    Args:
        registry: Optional registry to use (defaults to global registry)

    Returns:
        Complete configuration dictionary with all gates disabled
    """
    # Just use the base config - it already has everything disabled by default
    return generate_base_config(registry)


def write_template_config(
    project_root: Path,
    registry: Optional[CheckRegistry] = None,
) -> Path:
    """Write the template configuration file.

    Args:
        project_root: Project root directory
        registry: Optional registry to use

    Returns:
        Path to the written template file
    """
    template_path = project_root / ".sb_config.json.template"
    config = generate_template_config(registry)

    with open(template_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    logger.info(f"Generated template config: {template_path}")
    return template_path


def write_config(
    output_path: Path,
    config: Dict[str, Any],
    backup: bool = True,
) -> Path:
    """Write configuration to file.

    Args:
        output_path: Path to write config to
        config: Configuration dictionary
        backup: Whether to backup existing config

    Returns:
        Path to the written config file
    """
    if backup and output_path.exists():
        backup_config(output_path)

    with open(output_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")  # Trailing newline

    logger.info(f"Generated config: {output_path}")
    return output_path


def main(output_path: Optional[str] = None, backup: bool = True) -> Path:
    """Main entry point for config generation.

    Args:
        output_path: Optional path for output (defaults to .sb_config.json)
        backup: Whether to backup existing config

    Returns:
        Path to the generated config file
    """
    if output_path is None:
        resolved_path = Path.cwd() / CONFIG_FILE
    else:
        resolved_path = Path(output_path)

    config = generate_base_config()
    return write_config(resolved_path, config, backup=backup)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    output = sys.argv[1] if len(sys.argv) > 1 else None
    result_path = main(output)
    print(f"Generated: {result_path}")
