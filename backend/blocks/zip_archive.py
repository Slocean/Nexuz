"""压缩/解压：zip 打包多个文件或整个文件夹，或把 zip 解压到目标目录。

打包时文件取文件名，文件夹递归归档（保留文件夹内部相对结构）；
解压时默认解到 zip 同级、以 zip 文件名命名的子目录。
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from backend.blocks._helpers import split_input_paths

SCHEMA = {
    "type": "zip_archive",
    "label": "压缩/解压",
    "category": "系统类",
    "done_log": "压缩/解压完成：{{output}}",
    "inputs": [
        {
            "name": "action",
            "type": "select",
            "label": "操作",
            "options": ["zip", "unzip"],
            "default": "zip",
            "option_labels": {"zip": "压缩", "unzip": "解压"},
        },
        {
            "name": "sources",
            "type": "string",
            "label": "来源（文件/文件夹）",
            "default": "",
            "placeholder": "支持多个：一行一个，或从资源管理器拖入/多选",
            "ui": "textarea",
            "bindable": True,
            "show_when": {"action": "zip"},
        },
        {
            "name": "zip_path",
            "type": "string",
            "label": "压缩包路径",
            "default": "",
            "placeholder": "要解压的 .zip 文件",
            "ui": "file_path",
            "accept": "*.zip",
            "bindable": True,
            "show_when": {"action": "unzip"},
        },
        {
            "name": "output",
            "type": "string",
            "label": "输出",
            "default": "",
            "placeholder": "压缩：目标 .zip 路径（留空=来源旁自动命名）；解压：目标文件夹（留空=zip 同名目录）",
            "ui": "file_or_dir",
            "bindable": True,
        },
        {
            "name": "overwrite",
            "type": "select",
            "label": "覆盖已存在",
            "options": ["true", "false"],
            "default": "true",
            "option_labels": {"true": "是", "false": "否（报错）"},
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "output", "type": "string"},
        {"name": "count", "type": "number"},
        {"name": "total_mb", "type": "number"},
        {"name": "error", "type": "string"},
    ],
}


def _unique_output(base: Path) -> Path:
    """base 已存在时追加 _1/_2… 防覆盖。"""
    if not base.exists():
        return base
    stem, suffix = base.stem, base.suffix
    for i in range(1, 1000):
        candidate = base.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
    return base


def _do_zip(sources: list[Path], output_raw: str, overwrite: bool) -> dict[str, Any]:
    srcs = [p for p in sources if p.exists()]
    if not srcs:
        return {"ok": False, "output": "", "count": 0, "total_mb": 0, "error": "来源不存在或为空"}

    out_raw = str(output_raw or "").strip().strip('"')
    if out_raw:
        out = Path(out_raw).expanduser()
        if out.suffix.lower() != ".zip":
            out = out.with_suffix(".zip")
        if out.exists() and not overwrite:
            return {"ok": False, "output": str(out), "count": 0, "total_mb": 0, "error": f"输出已存在: {out}"}
        out.parent.mkdir(parents=True, exist_ok=True)
    else:
        # 未指定输出：写到第一个来源旁（文件用同名，文件夹用文件夹名）
        first = srcs[0]
        default = first.with_suffix(".zip") if first.is_file() else first.parent / f"{first.name}.zip"
        out = _unique_output(default) if not overwrite else default

    count = 0
    total_bytes = 0
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for src in srcs:
                if src.is_file():
                    zf.write(src, arcname=src.name)
                    count += 1
                    total_bytes += src.stat().st_size
                    continue
                for child in sorted(src.rglob("*")):
                    if child.is_file():
                        zf.write(child, arcname=str(child.relative_to(src.parent)))
                        count += 1
                        total_bytes += child.stat().st_size
    except Exception as exc:
        return {"ok": False, "output": str(out), "count": count, "total_mb": 0, "error": str(exc)}
    return {
        "ok": True,
        "output": str(out),
        "count": count,
        "total_mb": round(total_bytes / (1024 * 1024), 2),
        "error": "",
    }


def _do_unzip(zip_raw: str, output_raw: str, overwrite: bool) -> dict[str, Any]:
    zip_text = str(zip_raw or "").strip().strip('"')
    if not zip_text:
        return {"ok": False, "output": "", "count": 0, "total_mb": 0, "error": "请选择要解压的 .zip 文件"}
    zp = Path(zip_text).expanduser()
    if not zp.is_file():
        return {"ok": False, "output": "", "count": 0, "total_mb": 0, "error": f"压缩包不存在: {zp}"}

    out_text = str(output_raw or "").strip().strip('"')
    out = Path(out_text).expanduser() if out_text else zp.parent / zp.stem
    if out.exists() and any(out.iterdir()) and not overwrite:
        return {"ok": False, "output": str(out), "count": 0, "total_mb": 0, "error": f"输出目录非空: {out}"}
    out.mkdir(parents=True, exist_ok=True)

    # 防压缩包路径穿越：统一解到输出目录内
    safe_root = out.resolve()
    count = 0
    total_bytes = 0
    try:
        with zipfile.ZipFile(zp) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                target = (safe_root / info.filename).resolve()
                if safe_root not in target.parents and target != safe_root:
                    return {
                        "ok": False,
                        "output": str(out),
                        "count": count,
                        "total_mb": 0,
                        "error": f"压缩包内含不安全路径: {info.filename}",
                    }
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as fsrc, open(target, "wb") as fdst:
                    fdst.write(fsrc.read())
                count += 1
                total_bytes += info.file_size
    except Exception as exc:
        return {"ok": False, "output": str(out), "count": count, "total_mb": 0, "error": str(exc)}
    return {
        "ok": True,
        "output": str(out),
        "count": count,
        "total_mb": round(total_bytes / (1024 * 1024), 2),
        "error": "",
    }


def handler(params, context, **kwargs):
    action = str(params.get("action") or "zip").strip().lower()
    overwrite = str(params.get("overwrite") or "true").strip().lower() in ("true", "1", "yes")
    if action == "zip":
        sources = split_input_paths(params.get("sources"))
        return _do_zip(sources, params.get("output"), overwrite)
    if action == "unzip":
        return _do_unzip(params.get("zip_path"), params.get("output"), overwrite)
    return {"ok": False, "output": "", "count": 0, "total_mb": 0, "error": f"未知操作: {action}"}
