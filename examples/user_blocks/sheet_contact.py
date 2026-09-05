"""序列帧目检拼图（sheet_contact）— Nexuz 用户自定义积木。

把帧序列拼成带文件名标注的网格检查图（参照脚本 contact_sheet 的通用化）：
切分/归一之后逐帧目检切伤、吞并、缺失，人或视觉 AI 看这一张图即可验收。
只读输入，仅产出拼图到独立文件。

安装：放入 %LOCALAPPDATA%/Nexuz/user_blocks/ 并在设置中授权，重启后生效。
设计来源：三十六计_Nexuz序列帧校验目检与回归积木设计_v3.0。
本机可信插件：隔离 worker 禁止网络与子进程、允许文件读写；请仅授权可信来源。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

SCHEMA = {
    "type": "sheet_contact",
    "label": "序列帧目检拼图",
    "category": "识别类",
    "done_log": "已生成{{count}}张目检拼图：{{first_path}}",
    "description": "帧序列拼成带文件名标注的网格检查图：切分/归一后逐帧目检切伤、"
    "吞并、缺失。本机可信插件：隔离 worker 禁止网络与子进程、允许文件读写。",
    "inputs": [
        {
            "name": "image_path",
            "type": "string",
            "label": "帧序列",
            "default": "",
            "placeholder": "帧序列文件夹（一行一个=每文件夹一张拼图）或图片文件列表（拼一张）",
            "ui": "textarea",
            "bindable": True,
            "required": True,
        },
        {
            "name": "columns",
            "type": "number",
            "label": "每行帧数",
            "default": 0,
            "placeholder": "0=全部单行铺开",
        },
        {
            "name": "cell_scale",
            "type": "number",
            "label": "帧缩放(%)",
            "default": 100,
            "placeholder": "100=原尺寸",
        },
        {
            "name": "label",
            "type": "select",
            "label": "文件名标注",
            "options": ["yes", "no"],
            "default": "yes",
        },
        {
            "name": "background",
            "type": "select",
            "label": "底色",
            "options": ["dark", "white", "checker"],
            "default": "dark",
            "option_labels": {
                "dark": "深灰（默认，看浅色精灵）",
                "white": "白色（看深色精灵）",
                "checker": "棋盘格（显示透明区）",
            },
        },
        {
            "name": "output_dir",
            "type": "string",
            "label": "输出目录",
            "default": "",
            "placeholder": "留空=文件夹旁的 文件夹名_contact.png",
            "ui": "file_or_dir",
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "count", "type": "number"},
        {"name": "first_path", "type": "string"},
        {"name": "paths", "type": "array"},
        {"name": "per_file", "type": "array"},
        {"name": "errors", "type": "array"},
    ],
}

_CHECKER_SIZE = 8
_DARK_BG = (30, 30, 30, 255)
_WHITE_BG = (255, 255, 255, 255)
_CHECKER_A = (204, 204, 204, 255)
_CHECKER_B = (255, 255, 255, 255)
_LABEL_COLOR = (255, 255, 0, 255)


def _split_paths(raw: Any) -> list[Path]:
    if isinstance(raw, (list, tuple)):
        parts = list(raw)
    else:
        parts = str(raw or "").replace(";", "\n").splitlines()
    out: list[Path] = []
    for part in parts:
        text = str(part).strip().strip('"').strip("'")
        if text:
            out.append(Path(text))
    return out


def _to_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _checker_background(w: int, h: int) -> Image.Image:
    im = Image.new("RGBA", (w, h), _CHECKER_A)
    draw = ImageDraw.Draw(im)
    for y in range(0, h, _CHECKER_SIZE):
        for x in range(0, w, _CHECKER_SIZE):
            if (x // _CHECKER_SIZE + y // _CHECKER_SIZE) % 2:
                draw.rectangle([x, y, min(x + _CHECKER_SIZE, w) - 1, min(y + _CHECKER_SIZE, h) - 1], fill=_CHECKER_B)
    return im


def _build_sheet(
    frames: list[tuple[str, Image.Image]],
    *,
    columns: int,
    background: str,
    show_label: bool,
) -> Image.Image:
    """帧列表 → 网格拼图。帧已按 cell_scale 缩放。"""
    if not frames:
        raise ValueError("没有可用的帧")
    cell_w = max(im.width for _, im in frames)
    cell_h = max(im.height for _, im in frames)
    cols = len(frames) if columns <= 0 else min(columns, len(frames))
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGBA", (cell_w * cols, cell_h * rows), _DARK_BG)
    if background == "checker":
        sheet = _checker_background(sheet.width, sheet.height)
    elif background == "white":
        sheet = Image.new("RGBA", (sheet.width, sheet.height), _WHITE_BG)
    for idx, (name, im) in enumerate(frames):
        row, col = divmod(idx, cols)
        x, y = col * cell_w, row * cell_h
        # 帧小于格子时贴到透明格画布上（alpha_composite 支持偏移），半透明像素不被底色污染
        cell = Image.new("RGBA", (cell_w, cell_h), (0, 0, 0, 0))
        cell.alpha_composite(im, (0, 0))
        sheet.alpha_composite(cell, (x, y))
        if show_label:
            ImageDraw.Draw(sheet).text((x + 4, y + 2), name, fill=_LABEL_COLOR)
    return sheet


def _save_sheet(
    sheet: Image.Image, target: Path, group: str, frames_count: int,
    paths: list[str], per_file: list[dict[str, Any]], errors: list[str],
) -> None:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(target)
    except OSError as exc:
        errors.append(f"{group}：拼图保存失败（{exc}）")
        return
    paths.append(str(target))
    per_file.append(
        {
            "group": group,
            "path": str(target),
            "frames": frames_count,
            "size": [sheet.width, sheet.height],
        }
    )


def handler(params, context, **kwargs):
    sources = _split_paths(params.get("image_path"))
    if not sources:
        raise ValueError("image_path 不能为空（帧序列文件夹或图片文件列表）")
    for src in sources:
        if not src.exists():
            raise FileNotFoundError(f"路径不存在: {src}")

    columns = _to_int(params.get("columns"), 0)
    cell_scale = _to_int(params.get("cell_scale"), 100)
    show_label = str(params.get("label") or "yes") != "no"
    background = str(params.get("background") or "dark")
    raw_out = str(params.get("output_dir") or "").strip().strip('"').strip("'")
    out_root = Path(raw_out) if raw_out else None

    dirs = [s for s in sources if s.is_dir()]
    loose_files = sorted(
        {p for s in sources if s.is_file() for p in ([s] if s.suffix.lower() == ".png" else s.glob("*.png"))}
    )
    # 排除自身历史产物（文件夹组输出 文件夹名_contact.png、散装组输出 contact.png，
    # 均与输入同目录，二次运行会把上次的拼图当成帧）
    def _is_own_output(name: str) -> bool:
        return name == "contact.png" or name.endswith("_contact.png")

    groups: list[tuple[str, Path, list[Path]]] = [
        (d.name, d, sorted(p for p in d.glob("*.png") if not _is_own_output(p.name)))
        for d in dirs
    ]
    if loose_files:
        groups.append(("contact", loose_files[0].parent, loose_files))
    groups = [(name, base, files) for name, base, files in groups if files]
    if not groups:
        raise ValueError("没有可用的 png 帧（文件夹为空或未指定图片）")

    errors: list[str] = []
    paths: list[str] = []
    per_file: list[dict[str, Any]] = []
    for name, base, files in groups:
        frames: list[tuple[str, Image.Image]] = []
        for f in files:
            try:
                with Image.open(f) as im:
                    rgba = im.convert("RGBA")
                    if cell_scale != 100:
                        scale = cell_scale / 100.0
                        rgba = rgba.resize(
                            (max(1, round(rgba.width * scale)), max(1, round(rgba.height * scale))),
                            Image.Resampling.LANCZOS,
                        )
                    frames.append((f.name, rgba.copy()))
            except OSError as exc:
                errors.append(f"{name}/{f.name}：读取失败（{exc}）")
        if not frames:
            continue
        sheet = _build_sheet(frames, columns=columns, background=background, show_label=show_label)
        # 散装文件组输出 contact.png，文件夹组输出 文件夹名_contact.png
        target_name = "contact.png" if name == "contact" else f"{name}_contact.png"
        target = (out_root or base) / target_name
        _save_sheet(sheet, target, name, len(frames), paths, per_file, errors)

    return {
        "ok": not errors,
        "count": len(paths),
        "first_path": paths[0] if paths else "",
        "paths": paths,
        "per_file": per_file,
        "errors": errors,
    }
