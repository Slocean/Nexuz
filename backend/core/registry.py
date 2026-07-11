"""Block registry: scan blocks/ and register SCHEMA + handler."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Any, Callable

BLOCK_REGISTRY: dict[str, dict[str, Any]] = {}


def register_block(schema: dict[str, Any], handler: Callable) -> None:
    block_type = schema["type"]
    BLOCK_REGISTRY[block_type] = {"schema": schema, "handler": handler}


def register_all_blocks() -> dict[str, dict[str, Any]]:
    """Import every module under backend.blocks and register SCHEMA/handler."""
    BLOCK_REGISTRY.clear()

    # Ensure package import works whether run as module or script
    blocks_pkg = "backend.blocks"
    try:
        package = importlib.import_module(blocks_pkg)
    except ImportError:
        # Fallback: load files directly from blocks directory
        return _register_from_path(Path(__file__).resolve().parent.parent / "blocks")

    package_path = Path(package.__file__).parent
    for module_info in pkgutil.iter_modules([str(package_path)]):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{blocks_pkg}.{module_info.name}")
        if hasattr(module, "SCHEMA") and hasattr(module, "handler"):
            register_block(module.SCHEMA, module.handler)

    return BLOCK_REGISTRY


def _register_from_path(blocks_dir: Path) -> dict[str, dict[str, Any]]:
    import sys

    parent = str(blocks_dir.parent.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    for path in sorted(blocks_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        mod_name = f"backend.blocks.{path.stem}"
        module = importlib.import_module(mod_name)
        if hasattr(module, "SCHEMA") and hasattr(module, "handler"):
            register_block(module.SCHEMA, module.handler)
    return BLOCK_REGISTRY


def get_schemas() -> list[dict[str, Any]]:
    return [entry["schema"] for entry in BLOCK_REGISTRY.values()]


def get_handler(block_type: str) -> Callable | None:
    entry = BLOCK_REGISTRY.get(block_type)
    return entry["handler"] if entry else None
