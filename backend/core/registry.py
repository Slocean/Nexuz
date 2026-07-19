"""Block registry: scan built-in blocks/ and user_blocks/ for SCHEMA + handler."""

from __future__ import annotations

import ast
import hashlib
import importlib
import logging
import pkgutil
import sys
from pathlib import Path
from typing import Any, Callable

from backend.core.worker_client import run_isolated

BLOCK_REGISTRY: dict[str, dict[str, Any]] = {}
logger = logging.getLogger(__name__)
_USER_BLOCK_TRUST_KEY = "trusted_user_blocks"

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
        bundled_example = user_dir / "example_echo.py"
        try:
            if (
                bundled_example in existing
                and bundled_example.read_text(encoding="utf-8") == EXAMPLE_ECHO_PY
                and not is_user_block_trusted(bundled_example)
            ):
                trust_user_block(bundled_example)
        except OSError:
            pass
        return
    example = user_dir / "example_echo.py"
    if example.exists():
        return
    try:
        example.write_text(EXAMPLE_ECHO_PY, encoding="utf-8")
        trust_user_block(example)
    except OSError as exc:
        logger.warning("无法写入用户积木示例: %s", exc)


def user_block_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _trusted_user_blocks() -> dict[str, str]:
    from backend.paths import load_app_config

    raw = load_app_config().get(_USER_BLOCK_TRUST_KEY)
    if not isinstance(raw, dict):
        return {}
    return {
        str(name): str(digest).lower()
        for name, digest in raw.items()
        if isinstance(name, str) and isinstance(digest, str)
    }


def is_user_block_trusted(path: Path) -> bool:
    try:
        return _trusted_user_blocks().get(path.name) == user_block_sha256(path)
    except OSError:
        return False


def trust_user_block(path: Path) -> str:
    from backend.paths import load_app_config, save_app_config

    digest = user_block_sha256(path)
    cfg = load_app_config()
    trusted = cfg.get(_USER_BLOCK_TRUST_KEY)
    if not isinstance(trusted, dict):
        trusted = {}
    trusted[path.name] = digest
    cfg[_USER_BLOCK_TRUST_KEY] = trusted
    save_app_config(cfg)
    return digest


def revoke_user_block(path: Path) -> None:
    from backend.paths import load_app_config, save_app_config

    cfg = load_app_config()
    trusted = cfg.get(_USER_BLOCK_TRUST_KEY)
    if not isinstance(trusted, dict) or path.name not in trusted:
        return
    trusted.pop(path.name, None)
    cfg[_USER_BLOCK_TRUST_KEY] = trusted
    save_app_config(cfg)


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
        if not is_user_block_trusted(path):
            logger.warning("用户积木尚未授权或内容已变化，已跳过: %s", path.name)
            continue
        try:
            schema = _read_user_block_schema(path)
        except Exception as exc:
            logger.warning("解析用户积木声明失败 %s: %s", path.name, exc)
            continue
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
        schema["trust_tier"] = "user_plugin"
        schema["source_file"] = path.name
        schema.setdefault(
            "description",
            "本机可信插件：隔离 worker 默认阻断网络、子进程和文件写入，但仍非完整安全沙箱。",
        )
        register_block(schema, _make_isolated_user_handler(path, block_type))


def _read_user_block_schema(path: Path) -> dict[str, Any]:
    """Read a literal SCHEMA assignment without executing plugin code."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    for node in tree.body:
        value = None
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "SCHEMA"
            for target in node.targets
        ):
            value = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "SCHEMA"
        ):
            value = node.value
        if value is not None:
            schema = ast.literal_eval(value)
            if not isinstance(schema, dict):
                raise ValueError("SCHEMA 必须是字面量字典")
            return schema
    raise ValueError("缺少可静态解析的 SCHEMA 字面量")


def _make_isolated_user_handler(path: Path, block_type: str) -> Callable:
    resolved = path.resolve()

    def isolated_handler(params, context, **kwargs):
        response = run_isolated(
            {
                "kind": "plugin",
                "path": str(resolved),
                "block_type": block_type,
                "params": params if isinstance(params, dict) else {},
                "context": context if isinstance(context, dict) else {},
                "kwargs": {
                    "node": kwargs.get("node"),
                    "node_id": kwargs.get("node_id"),
                    "flow": kwargs.get("flow"),
                },
            },
            timeout_seconds=30,
            should_stop=kwargs.get("should_stop"),
        )
        if not response.get("ok"):
            return {
                "ok": False,
                "error": response.get("error") or "用户积木 worker 执行失败",
            }
        result = response.get("result")
        if not isinstance(result, dict):
            return {"ok": False, "error": "用户积木 worker 返回格式无效"}
        return result

    return isolated_handler


def get_schemas() -> list[dict[str, Any]]:
    return [entry["schema"] for entry in BLOCK_REGISTRY.values()]


def get_handler(block_type: str) -> Callable | None:
    entry = BLOCK_REGISTRY.get(block_type)
    return entry["handler"] if entry else None
