"""Template loading and discovery."""

from __future__ import annotations

from pathlib import Path

import yaml

from wiggy.templates.base import ArtifactTemplate

# Constants
TEMPLATE_DIRNAME = "templates"
TEMPLATE_YAML = "template.yaml"

# Map format names to file extensions for content files
FORMAT_EXTENSIONS: dict[str, str] = {
    "markdown": ".md",
    "json": ".json",
    "xml": ".xml",
    "text": ".txt",
}


def get_package_templates_path() -> Path:
    """Get path to package-bundled default templates."""
    return Path(__file__).parent / "default"


def get_global_templates_path() -> Path:
    """Get path to global user templates: ~/.wiggy/templates/."""
    return Path.home() / ".wiggy" / TEMPLATE_DIRNAME


def get_local_templates_path() -> Path:
    """Get path to project-specific templates: ./.wiggy/templates/."""
    return Path.cwd() / ".wiggy" / TEMPLATE_DIRNAME


def get_template_search_paths() -> list[Path]:
    """Return template search paths in priority order (highest first).

    Resolution order:
    1. Local project templates (./.wiggy/templates/) - highest priority
    2. Global user templates (~/.wiggy/templates/)
    """
    paths = []

    local = get_local_templates_path()
    if local.exists():
        paths.append(local)

    global_templates = get_global_templates_path()
    if global_templates.exists():
        paths.append(global_templates)

    return paths


def discover_template_dirs(base_path: Path) -> dict[str, Path]:
    """Discover template directories within a base path.

    Returns dict mapping template name -> template directory path.
    Only includes directories containing template.yaml.
    """
    templates: dict[str, Path] = {}
    if not base_path.exists():
        return templates

    for item in base_path.iterdir():
        if item.is_dir():
            template_yaml = item / TEMPLATE_YAML
            if template_yaml.exists():
                templates[item.name] = item

    return templates


def _load_content_file(template_dir: Path, fmt: str) -> str:
    """Load the content file for a template based on its format.

    Looks for content.{ext} where ext is determined by format.
    Falls back to any content.* file if exact match not found.
    """
    ext = FORMAT_EXTENSIONS.get(fmt, ".txt")
    content_file = template_dir / f"content{ext}"
    if content_file.exists():
        return content_file.read_text(encoding="utf-8").strip()

    # Fallback: try any content.* file
    for candidate in template_dir.glob("content.*"):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()

    return ""


def load_template_from_dir(template_dir: Path) -> ArtifactTemplate | None:
    """Load an ArtifactTemplate from a template directory.

    Returns None if template.yaml is missing or invalid.
    """
    template_yaml = template_dir / TEMPLATE_YAML
    if not template_yaml.exists():
        return None

    try:
        with template_yaml.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if not isinstance(data, dict):
                return None
    except yaml.YAMLError:
        return None

    name = str(data.get("name", ""))
    description = str(data.get("description", ""))
    fmt = str(data.get("format", "text"))

    tags_raw = data.get("tags", [])
    if isinstance(tags_raw, list):
        tags = tuple(str(t) for t in tags_raw)
    else:
        tags = ()

    content = _load_content_file(template_dir, fmt)

    return ArtifactTemplate(
        name=name,
        description=description,
        format=fmt,
        content=content,
        tags=tags,
        source=template_dir,
    )


def get_all_templates() -> dict[str, ArtifactTemplate]:
    """Discover and load all templates from filesystem locations.

    Resolution order (later wins for same name):
    1. Global (~/.wiggy/templates/)
    2. Project (./.wiggy/templates/)

    Returns dict mapping template name -> ArtifactTemplate.
    """
    templates: dict[str, ArtifactTemplate] = {}

    # 1. Global templates (lower priority)
    global_templates = discover_template_dirs(get_global_templates_path())
    for name, template_dir in global_templates.items():
        tmpl = load_template_from_dir(template_dir)
        if tmpl:
            templates[name] = tmpl

    # 2. Local/project templates (highest priority, overrides global)
    local_templates = discover_template_dirs(get_local_templates_path())
    for name, template_dir in local_templates.items():
        tmpl = load_template_from_dir(template_dir)
        if tmpl:
            templates[name] = tmpl

    return templates


def get_template_by_name(name: str) -> ArtifactTemplate | None:
    """Get a specific template by name, using resolution order.

    Checks local first, then global.
    """
    # Check local first (highest priority)
    local_path = get_local_templates_path() / name
    if local_path.exists():
        tmpl = load_template_from_dir(local_path)
        if tmpl:
            return tmpl

    # Check global
    global_path = get_global_templates_path() / name
    if global_path.exists():
        tmpl = load_template_from_dir(global_path)
        if tmpl:
            return tmpl

    return None


def get_available_template_names() -> list[str]:
    """Get list of all available template names (from all locations)."""
    return sorted(get_all_templates().keys())


def copy_default_templates_to_user(overwrite: bool = False) -> list[str]:
    """Copy package default templates to user's global templates directory.

    Args:
        overwrite: If True, overwrite existing templates. If False, skip existing.

    Returns:
        List of template names that were copied.
    """
    import shutil

    package_path = get_package_templates_path()
    global_path = get_global_templates_path()
    global_path.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []

    for template_name, template_dir in discover_template_dirs(package_path).items():
        dest_dir = global_path / template_name

        if dest_dir.exists() and not overwrite:
            continue

        if dest_dir.exists():
            shutil.rmtree(dest_dir)

        shutil.copytree(template_dir, dest_dir)
        copied.append(template_name)

    return copied
