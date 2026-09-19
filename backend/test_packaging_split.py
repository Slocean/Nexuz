"""打包分流守门：桌面导入链不得触及 server.py / notify_sink（AST 静态检查）。

package.py 用 --exclude-module 兜底排除，本测试保证源码层面根本不存在
"桌面链路 import 服务器模块" 的路径——两条防线互为备份。
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
SERVER_ONLY_MODULES = {"backend.server", "backend.core.notify_sink"}


def _module_name(path: Path) -> str:
    rel = path.relative_to(BACKEND.parent).with_suffix("")
    return ".".join(rel.parts)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.add(node.module)
            elif node.level > 0:
                # 相对导入：backend 包内一律 backend[.core...].xxx
                parts = [_module_name(path).split(".")[0] + "." + _module_name(path).split(".")[1]]
                found.add(".".join(_module_name(path).split(".")[: node.level] + [node.module or ""]))
    return found


def _backend_py_files() -> list[Path]:
    files = list(BACKEND.glob("*.py"))
    files += list((BACKEND / "core").rglob("*.py"))
    files += list((BACKEND / "blocks").rglob("*.py"))
    return [f for f in files if "__pycache__" not in f.parts and f.name != "test_packaging_split.py"]


def test_desktop_chain_never_imports_server_modules():
    """除 server.py 本身（服务器入口）外，任何 backend 源文件不得 import
    服务器专属模块；test_*.py 不属于运行时产物，不在检查范围。"""
    violations: list[str] = []
    for path in _backend_py_files():
        mod = _module_name(path)
        if mod == "backend.server" or path.name.startswith("test_"):
            continue
        for imported in _imported_modules(path):
            for server_mod in SERVER_ONLY_MODULES:
                if imported == server_mod or imported.startswith(server_mod + "."):
                    violations.append(f"{path.name} -> {imported}")
    assert not violations, "桌面导入链混入服务器模块：" + "；".join(violations)


def test_server_modules_exist_and_are_isolated():
    """服务器模块真实存在，且只有 server.py 引用 notify_sink。"""
    assert (BACKEND / "server.py").is_file()
    assert (BACKEND / "core" / "notify_sink.py").is_file()
    importers = []
    for path in _backend_py_files():
        if path.name == "server.py" or path.name.startswith("test_"):
            continue
        mods = _imported_modules(path)
        if any(m == "backend.core.notify_sink" for m in mods):
            importers.append(path.name)
    assert not importers, f"notify_sink 被 server.py 之外的模块引用: {importers}"
