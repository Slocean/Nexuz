"""文件整理：移动 / 复制 / 重命名 / 新建文件夹 / 列出目录内容。

为 AI 实时执行（run_block / MCP）与流程编排提供结构化的文件系统整理
能力：来源可多个（一行一个），目标已存在时默认报错、显式开启才覆盖；
列出目录用于「先观察再整理」的典型工作流。刻意不提供删除类操作——
不可恢复的破坏性动作不进积木白名单。
"""

from __future__ import annotations

import fnmatch
import shutil
import time
from pathlib import Path
from typing import Any

from backend.blocks._helpers import split_input_paths
from backend.blocks._system_io import normalize_path

# list 动作单次返回条目上限（防 AI 传根目录撑爆上下文）；超出置 truncated。
MAX_LIST_ENTRIES = 500

SCHEMA = {
    "type": "file_manage",
    "description": "复制/移动/删除/重命名文件与目录。",
    "label": "文件整理",
    "category": "系统类",
    "done_log": "文件整理完成：{{output}}（{{count}} 项）",
    "inputs": [
        {
            "name": "action",
            "type": "select",
            "label": "操作",
            "options": ["move", "copy", "rename", "mkdir", "list"],
            "default": "move",
            "option_labels": {
                "move": "移动",
                "copy": "复制",
                "rename": "重命名",
                "mkdir": "新建文件夹",
                "list": "列出内容",
            },
        },
        {
            "name": "sources",
            "type": "string",
            "label": "来源（文件/文件夹，可多个）",
            "default": "",
            "placeholder": "一行一个，或从资源管理器拖入/多选",
            "ui": "textarea",
            "bindable": True,
            "show_when": {"action": ["move", "copy"]},
        },
        {
            "name": "output",
            "type": "string",
            "label": "目标",
            "default": "",
            "placeholder": "多个来源时为目标文件夹（不存在会创建）；单个来源时也可填目标完整路径",
            "ui": "file_or_dir",
            "bindable": True,
            "show_when": {"action": ["move", "copy"]},
        },
        {
            "name": "overwrite",
            "type": "select",
            "label": "覆盖已存在",
            "options": ["false", "true"],
            "default": "false",
            "option_labels": {"false": "否（目标已存在则报错）", "true": "是"},
            "show_when": {"action": ["move", "copy"]},
        },
        {
            "name": "path",
            "type": "string",
            "label": "路径",
            "default": "",
            "placeholder": "重命名：原文件/文件夹；新建文件夹：要创建的路径；列出内容：文件夹",
            "ui": "file_or_dir",
            "bindable": True,
            "show_when": {"action": ["rename", "mkdir", "list"]},
        },
        {
            "name": "name",
            "type": "string",
            "label": "新名称",
            "default": "",
            "placeholder": "仅名称，不含路径；如 报告_2026.docx",
            "bindable": True,
            "show_when": {"action": "rename"},
        },
        {
            "name": "pattern",
            "type": "string",
            "label": "名称过滤",
            "default": "*",
            "placeholder": "通配符，匹配文件名：*.jpg、报告*、*2026*",
            "bindable": True,
            "show_when": {"action": "list"},
        },
        {
            "name": "kind",
            "type": "select",
            "label": "类型过滤",
            "options": ["all", "file", "dir"],
            "default": "all",
            "option_labels": {"all": "全部", "file": "仅文件", "dir": "仅文件夹"},
            "show_when": {"action": "list"},
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "action", "type": "string"},
        {"name": "output", "type": "string"},
        {"name": "count", "type": "number"},
        {
            "name": "items",
            "type": "array",
            "itemType": "object",
            "canvas": False,
            "fields": {
                "src": "string",
                "dst": "string",
                "name": "string",
                "type": "string",
                "size": "number",
                "mtime": "string",
            },
        },
        {"name": "truncated", "type": "boolean"},
        {"name": "error", "type": "string"},
    ],
}


def _base(action: str) -> dict[str, Any]:
    return {
        "ok": False,
        "action": action,
        "output": "",
        "count": 0,
        "items": [],
        "truncated": False,
        "error": "",
    }


def _to_bool(val: Any) -> bool:
    return str(val or "").strip().lower() in ("true", "1", "yes")


def _resolve_sources(raw: Any) -> tuple[list[Path], str | None]:
    sources: list[Path] = []
    for item in split_input_paths(raw):
        path, err = normalize_path(str(item))
        if err or path is None:
            return [], f"来源路径无效: {item}（{err}）"
        sources.append(path)
    return sources, None


def _is_within(child: Path, parent: Path) -> bool:
    """child 与 parent 相同或位于 parent 内部（含跨盘符不可能的情形）。"""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _mtime(p: Path) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime))
    except OSError:
        return ""


def _do_transfer(params: dict[str, Any], action: str) -> dict[str, Any]:
    res = _base(action)
    overwrite = _to_bool(params.get("overwrite"))
    sources, err = _resolve_sources(params.get("sources"))
    if err:
        res["error"] = err
        return res
    if not sources:
        res["error"] = "来源不能为空（支持多个：一行一个）"
        return res
    out, err = normalize_path(params.get("output"))
    if err or out is None:
        res["error"] = err or "目标路径不能为空"
        return res

    multi = len(sources) > 1
    if multi:
        try:
            out.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            res["error"] = f"目标文件夹创建失败: {out}（{exc}）"
            return res
    if multi or out.is_dir():
        if not out.is_dir():
            res["error"] = f"目标不是文件夹: {out}（多个来源时目标必须为文件夹）"
            return res
        plans = [(s, out / s.name) for s in sources]
    else:
        plans = [(sources[0], out)]
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            res["error"] = f"目标父目录创建失败: {out.parent}（{exc}）"
            return res

    for s, t in plans:
        if not s.exists():
            res["error"] = f"来源不存在: {s}"
            return res
        if s == t or _is_within(t, s):
            res["error"] = f"目标与来源相同或位于来源内部: {t}"
            return res
        if t.exists():
            if not overwrite:
                res["error"] = f"目标已存在（可开启「覆盖已存在」）: {t}"
                return res
            if t.is_dir() and (action == "move" or s.is_file()):
                # 移动无法原地替换文件夹；复制文件夹允许合并（dirs_exist_ok）
                res["error"] = f"目标已是文件夹: {t}"
                return res

    done: list[dict[str, str]] = []
    for s, t in plans:
        try:
            if action == "move":
                shutil.move(str(s), str(t))
            elif s.is_dir():
                shutil.copytree(s, t, dirs_exist_ok=overwrite)
            else:
                shutil.copy2(s, t)
        except Exception as exc:
            res["count"] = len(done)
            res["items"] = done
            res["error"] = f"{s} → {t}: {exc}"
            return res
        done.append({"src": str(s), "dst": str(t)})
    res.update(ok=True, output=str(out), count=len(done), items=done)
    return res


def _do_rename(params: dict[str, Any]) -> dict[str, Any]:
    res = _base("rename")
    path, err = normalize_path(params.get("path"))
    if err or path is None:
        res["error"] = err or "路径不能为空"
        return res
    if not path.exists():
        res["error"] = f"路径不存在: {path}"
        return res
    name = str(params.get("name") or "").strip().strip('"').strip("'").strip()
    if not name:
        res["error"] = "新名称不能为空"
        return res
    if name in (".", "..") or "/" in name or "\\" in name or ":" in name:
        res["error"] = f"新名称只能是不含路径的名称（跨目录请用移动）: {name}"
        return res
    target = path.with_name(name)
    if target.exists():
        res["error"] = f"目标名已存在: {target}"
        return res
    try:
        path.rename(target)
    except Exception as exc:
        res["error"] = str(exc)
        return res
    res.update(
        ok=True,
        output=str(target),
        count=1,
        items=[{"src": str(path), "dst": str(target)}],
    )
    return res


def _do_mkdir(params: dict[str, Any]) -> dict[str, Any]:
    res = _base("mkdir")
    path, err = normalize_path(params.get("path"))
    if err or path is None:
        res["error"] = err or "路径不能为空"
        return res
    if path.exists():
        if path.is_dir():
            res.update(ok=True, output=str(path), count=0)
            return res
        res["error"] = f"路径已存在且不是文件夹: {path}"
        return res
    try:
        path.mkdir(parents=True)
    except Exception as exc:
        res["error"] = str(exc)
        return res
    res.update(ok=True, output=str(path), count=1)
    return res


def _do_list(params: dict[str, Any]) -> dict[str, Any]:
    res = _base("list")
    path, err = normalize_path(params.get("path"))
    if err or path is None:
        res["error"] = err or "路径不能为空"
        return res
    if not path.is_dir():
        res["error"] = f"不是文件夹或不存在: {path}"
        return res
    pattern = str(params.get("pattern") or "*").strip() or "*"
    kind = str(params.get("kind") or "all").strip().lower()
    if kind not in ("all", "file", "dir"):
        kind = "all"

    try:
        children = sorted(path.iterdir(), key=lambda c: c.name.casefold())
    except Exception as exc:
        res["error"] = str(exc)
        return res

    pat = pattern.lower()
    entries: list[dict[str, Any]] = []
    for child in children:
        if pat != "*" and not fnmatch.fnmatch(child.name.lower(), pat):
            continue
        try:
            is_dir = child.is_dir()
        except OSError:
            continue
        if kind == "file" and is_dir:
            continue
        if kind == "dir" and not is_dir:
            continue
        if len(entries) >= MAX_LIST_ENTRIES:
            res["truncated"] = True
            break
        entry: dict[str, Any] = {"name": child.name, "type": "dir" if is_dir else "file"}
        if not is_dir:
            try:
                entry["size"] = child.stat().st_size
            except OSError:
                pass
        mtime = _mtime(child)
        if mtime:
            entry["mtime"] = mtime
        entries.append(entry)
    res.update(ok=True, output=str(path), count=len(entries), items=entries)
    return res


def handler(params, context, **kwargs):
    action = str(params.get("action") or "move").strip().lower()
    if action in ("move", "copy"):
        return _do_transfer(params, action)
    if action == "rename":
        return _do_rename(params)
    if action == "mkdir":
        return _do_mkdir(params)
    if action == "list":
        return _do_list(params)
    return {**_base(action), "error": f"未知操作: {action}"}
