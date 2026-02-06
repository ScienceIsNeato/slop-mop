"""Reporting utilities for slop-mop CLI output."""

# Shared output strings used across multiple CLI commands
PROJECT_LABEL = "📂 Project: {project_root}"


def print_project_header(project_root: str) -> None:
    """Print the standard project root line used in CLI headers."""
    print(PROJECT_LABEL.format(project_root=project_root))
