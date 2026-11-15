"""Recipe discovery, loading, and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RecipeConfig:
    name: str
    version: str
    description: str
    path: Path
    instructions_file: Path
    gpu_default: bool = False
    network_default: bool = False
    timeout: str = "2h"
    resources: dict[str, Any] = field(default_factory=lambda: {
        "memory": "8g",
        "cpus": "4",
        "pids": "4096",
    })


class RecipeError(Exception):
    """Raised when recipe cannot be loaded or is invalid."""
    pass


def load_recipe(recipes_dir: Path, name: str) -> RecipeConfig:
    """Load and validate a recipe from the given directory."""
    recipe_dir = recipes_dir / name
    if not recipe_dir.is_dir():
        raise RecipeError(f"Recipe '{name}' not found at {recipe_dir}")

    config_path = recipe_dir / "config.json"
    instructions_path = recipe_dir / "INSTRUCTIONS.md"

    if not instructions_path.is_file():
        raise RecipeError(f"Recipe '{name}' is missing required 'INSTRUCTIONS.md' file.")

    if not config_path.is_file():
        raise RecipeError(f"Recipe '{name}' is missing required 'config.json' file.")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise RecipeError(f"Failed to parse {config_path}: {e}") from e

    return RecipeConfig(
        name=data.get("name", name),
        version=data.get("version", "1.0.0"),
        description=data.get("description", "No description provided."),
        path=recipe_dir.resolve(),
        instructions_file=instructions_path.resolve(),
        gpu_default=bool(data.get("gpu", False)),
        network_default=bool(data.get("network", False)),
        timeout=str(data.get("timeout", "2h")),
        resources=data.get("resources", {
            "memory": "8g",
            "cpus": "4",
            "pids": "4096",
        }),
    )


def list_recipes(recipes_dir: Path) -> list[RecipeConfig]:
    """Scan and list all valid recipes in recipes_dir."""
    recipes: list[RecipeConfig] = []
    if not recipes_dir.is_dir():
        return recipes

    for item in sorted(recipes_dir.iterdir()):
        if item.is_dir() and (item / "INSTRUCTIONS.md").is_file():
            try:
                recipes.append(load_recipe(recipes_dir, item.name))
            except RecipeError:
                continue

    return recipes
