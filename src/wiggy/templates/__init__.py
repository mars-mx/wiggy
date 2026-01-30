"""Artifact template definitions and discovery."""

from wiggy.templates.base import ArtifactTemplate
from wiggy.templates.loader import (
    copy_default_templates_to_user,
    get_all_templates,
    get_available_template_names,
    get_global_templates_path,
    get_local_templates_path,
    get_package_templates_path,
    get_template_by_name,
    get_template_search_paths,
)

__all__ = [
    "ArtifactTemplate",
    "copy_default_templates_to_user",
    "get_all_templates",
    "get_available_template_names",
    "get_global_templates_path",
    "get_local_templates_path",
    "get_package_templates_path",
    "get_template_by_name",
    "get_template_search_paths",
]

# Default template names for reference
DEFAULT_TEMPLATES: tuple[str, ...] = (
    "documentation",
    "prd",
)
