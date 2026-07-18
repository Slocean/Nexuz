"""Block registry: scan built-in blocks/ and user_blocks/ for SCHEMA + handler."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import pkgutil
import sys
from pathlib import Path
from typing import Any, Callable

BLOCK_REGISTRY: dict[str, dict[str, Any]] = {}
logger = logging.getLogger(__name__)

EXAMPLE_ECHO_PY = '''\
"""Example user block — copy & rename to add your own."""

SCHEMA = {
    "type": "example_echo",
    "label": "示例：回显",
    "category": "自定义",
    "inputs": [
        {
            "name": "text",
            "type": "string",
            "label": "文本",
            "default": "hello",
            "bindable": True,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "text", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    text = "" if params.get("text") is None else str(params.get("text"))
    return {"ok": True, "text": text}
'''


def register_block(schema: dict[str, Any], handler: Callable) -> None:
    block_type = schema["type"]
    BLOCK_REGISTRY[block_type] = {"schema": schema, "handler": handler}


def get_user_blocks_dir(*, create: bool = False) -> Path:
    """Resolved user blocks directory under the app data root."""
    from backend.paths import get_data_dir

    root = get_data_dir(create=create) / "user_blocks"
    if create:
        root.mkdir(parents=True, exist_ok=True)
        _ensure_example_user_block(root)
    return root


def _ensure_example_user_block(user_dir: Path) -> None:
    """Write example_echo.py only when the directory has no .py blocks yet."""
    existing = [p for p in user_dir.glob("*.py") if not p.name.startswith("_")]
    if existing:
        return
    example = user_dir / "example_echo.py"
    if example.exists():
        return
    try:
        example.write_text(EXAMPLE_ECHO_PY, encoding="utf-8")
    except OSError as exc:
        logger.warning("无法写入用户积木示例: %s", exc)


def register_all_blocks() -> dict[str, dict[str, Any]]:
    """Import built-in then user blocks; user types never override built-ins."""
    BLOCK_REGISTRY.clear()
    _register_builtin_blocks()
    builtin_types = set(BLOCK_REGISTRY.keys())
    _register_user_blocks(builtin_types=builtin_types)
    return BLOCK_REGISTRY


def _register_builtin_blocks() -> None:
    blocks_pkg = "backend.blocks"
    try:
        package = importlib.import_module(blocks_pkg)
    except ImportError:
        _register_builtin_from_path(Path(__file__).resolve().parent.parent / "blocks")
        return

    package_path = Path(package.__file__).parent
    for module_info in pkgutil.iter_modules([str(package_path)]):
        if module_info.name.startswith("_"):
            continue
        # Skip nested packages (e.g. user/ if ever present under blocks)
        if module_info.ispkg:
            continue
        try:
            module = importlib.import_module(f"{blocks_pkg}.{module_info.name}")
        except Exception as exc:
            logger.warning("加载内置积木失败 %s: %s", module_info.name, exc)
            continue
        if hasattr(module, "SCHEMA") and hasattr(module, "handler"):
            register_block(module.SCHEMA, module.handler)


def _register_builtin_from_path(blocks_dir: Path) -> None:
    parent = str(blocks_dir.parent.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    for path in sorted(blocks_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        mod_name = f"backend.blocks.{path.stem}"
        try:
            module = importlib.import_module(mod_name)
        except Exception as exc:
            logger.warning("加载内置积木失败 %s: %s", path.name, exc)
            continue
        if hasattr(module, "SCHEMA") and hasattr(module, "handler"):
            register_block(module.SCHEMA, module.handler)


def _register_user_blocks(*, builtin_types: set[str]) -> None:
    try:
        user_dir = get_user_blocks_dir(create=True)
    except Exception as exc:
        logger.warning("无法准备用户积木目录: %s", exc)
        return

    for path in sorted(user_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            module = _load_module_from_file(path)
        except Exception as exc:
            logger.warning("加载用户积木失败 %s: %s", path.name, exc)
            continue
        if not hasattr(module, "SCHEMA") or not hasattr(module, "handler"):
            logger.warning("用户积木缺少 SCHEMA/handler，已跳过: %s", path.name)
            continue
        schema = getattr(module, "SCHEMA") or {}
        if not isinstance(schema, dict) or not schema.get("type"):
            logger.warning("用户积木 SCHEMA.type 无效，已跳过: %s", path.name)
            continue
        block_type = str(schema["type"])
        if block_type in builtin_types:
            logger.warning(
                "用户积木 type=%s 与内置冲突，已跳过: %s",
                block_type,
                path.name,
            )
            continue
        if block_type in BLOCK_REGISTRY:
            logger.warning(
                "用户积木 type=%s 重复，已跳过: %s",
                block_type,
                path.name,
            )
            continue
        schema = dict(schema)
        if not schema.get("category"):
            schema["category"] = "自定义"
        register_block(schema, module.handler)


def _load_module_from_file(path: Path):
    # Unique module name so reloads replace the module
    mod_name = f"nexuz_user_blocks.{path.stem}_{abs(hash(str(path.resolve())))}"
    # Drop previous version if any
    for key in list(sys.modules.keys()):
        if key.startswith(f"nexuz_user_blocks.{path.stem}_"):
            del sys.modules[key]
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def get_schemas() -> list[dict[str, Any]]:
    return [entry["schema"] for entry in BLOCK_REGISTRY.values()]


def get_handler(block_type: str) -> Callable | None:
    entry = BLOCK_REGISTRY.get(block_type)
    return entry["handler"] if entry else None
