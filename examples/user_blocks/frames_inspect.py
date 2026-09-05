"""序列帧合同校验（frames_inspect）— Nexuz 用户自定义积木。

把画布合同（对齐三十六计 pawnAssetCanvas 口径）沉淀为流水线节点：归一化产物
（image_scale / frames_normalize 的输出）逐帧检查——组内画布一致、内容高一致
（±1px LANCZOS 取整容差）、内容底边贴齐画布底（脚底基线）、水平居中、
宽高比上限、空帧。违规只记入 errors 不中断整批，ok = not errors。

参照序列模式：画布尺寸与内容高基准取自参照（如已验收的关羽序列）；
留空则各序列以自身中位数为基准（只查内部一致性）。本积木只读不写。

安装：放入 %LOCALAPPDATA%/Nexuz/user_blocks/ 并在设置中授权，重启后生效。
设计来源：三十六计_Nexuz序列帧校验目检与回归积木设计_v3.0。
本机可信插件：隔离 worker 禁止网络与子进程、允许文件读写；请仅授权可信来源。
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

from PIL import Image

SCHEMA = {
    "type": "frames_inspect",
    "label": "序列帧合同校验",
    "category": "识别类",
    "done_log": "已校验{{folders}}个序列共{{frames}}帧",
    "description": "归一化产物逐帧过画布合同：画布一致、内容高一致、底边贴齐脚底基线、"
    "水平居中、宽高比上限、空帧；违规记入 errors 不中断。本机可信插件：隔离 worker "
    "禁止网络与子进程、允许文件读写。",
    "inputs": [
        {
            "name": "image_path",
            "type": "string",
            "label": "序列帧文件夹",
            "default": "",
            "placeholder": "每行一个文件夹（一个文件夹=一个序列，取按名排序的 png）",
            "ui": "textarea",
            "bindable": True,
            "required": True,
        },
        {
            "name": "reference_folder",
            "type": "string",
            "label": "参照序列",
            "default": "",
            "placeholder": "留空=各序列以自身中位数为基准；填写后画布与内容高基准取自该序列",
            "ui": "file_or_dir",
            "bindable": True,
        },
        {
            "name": "bottom_tolerance",
            "type": "number",
            "label": "底边容差(px)",
            "default": 1,
            "placeholder": "内容底边距画布底允许像素（脚底基线合同）",
        },
        {
            "name": "center_tolerance",
            "type": "number",
            "label": "居中容差(px)",
            "default": 2,
            "placeholder": "内容水平中心与画布中心允许偏差",
        },
        {
            "name": "height_tolerance",
            "type": "number",
            "label": "内容高容差(px)",
            "default": 1,
            "placeholder": "帧间内容高允许偏差（±1px 为缩放取整容差）",
        },
        {
            "name": "max_aspect",
            "type": "number",
            "label": "宽高比上限",
            "default": 3,
            "placeholder": "帧内容宽/高超过记 errors，0=不检查",
        },
        {
            "name": "canvas_w",
            "type": "number",
            "label": "期望画布宽",
            "default": 0,
            "placeholder": "0=取参照或第一帧现画布",
        },
        {
            "name": "canvas_h",
            "type": "number",
            "label": "期望画布高",
            "default": 0,
            "placeholder": "0=取参照或第一帧现画布",
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "folders", "type": "number"},
        {"name": "frames", "type": "number"},
        {"name": "per_folder", "type": "array"},
        {"name": "errors", "type": "array"},
    ],
}

# 内容判定：alpha > 16 视为有效像素（与 frames_normalize / sheet_segment 同口径）
_ALPHA_THRESHOLD = 16


def _split_paths(raw: Any) -> list[Path]:
    if isinstance(raw, (list, tuple)):
        parts = list(raw)
    else:
        parts = str(raw or "").replace(";", "\n").splitlines()
    out: list[Path] = []
    seen: set[str] = set()
    for part in parts:
        text = str(part).strip().strip('"').strip("'")
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(Path(text))
    return out


def _to_float(value: Any, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v


def _content_bbox(im: Image.Image) -> tuple[int, int, int, int] | None:
    mask = im.getchannel("A").point(lambda v: 255 if v > _ALPHA_THRESHOLD else 0)
    return mask.getbbox()


def _load_sequence(folder: Path, errors: list[str], label: str):
    """按文件名排序读取序列帧，返回 (文件名, 画布, 内容包围盒) 列表。"""
    files = sorted(folder.glob("*.png"))
    if not files:
        errors.append(f"{label}：文件夹内没有 png 序列帧")
        return None
    seq: list[tuple[str, tuple[int, int], tuple[int, int, int, int] | None]] = []
    for f in files:
        try:
            with Image.open(f) as im:
                rgba = im.convert("RGBA")
                seq.append((f.name, rgba.size, _content_bbox(rgba)))
        except OSError as exc:
            errors.append(f"{label}/{f.name}：读取失败（{exc}）")
            return None
    return seq


def _content_heights(seq) -> list[int]:
    return [b[3] - b[1] for _, _, b in seq if b is not None and b[3] - b[1] > 0]


def _inspect_folder(
    folder: Path,
    seq,
    *,
    base_canvas: tuple[int, int] | None,
    base_height: float | None,
    bottom_tol: float,
    center_tol: float,
    height_tol: float,
    max_aspect: float,
    errors: list[str],
) -> dict[str, Any]:
    """校验单个序列：逐帧过合同，违规记 errors 并继续。返回 per_folder 明细。"""
    label = folder.name
    first_size = seq[0][1]
    canvas = base_canvas or first_size
    median_h = base_height if base_height is not None else float(statistics.median(_content_heights(seq)))

    frames_detail: list[dict[str, Any]] = []
    for name, size, bbox in seq:
        frame_errors: list[str] = []
        if size != canvas:
            frame_errors.append(f"画布 {size[0]}x{size[1]} ≠ 期望 {canvas[0]}x{canvas[1]}")
        if bbox is None:
            frame_errors.append("空帧（无 alpha>16 内容）")
            w = h = 0
            margin = center_dev = aspect = 0.0
        else:
            x0, y0, x1, y1 = bbox
            w, h = x1 - x0, y1 - y0
            margin = canvas[1] - y1
            center_dev = abs((x0 + x1) / 2 - canvas[0] / 2)
            aspect = w / h if h > 0 else 0.0
            if abs(h - median_h) > height_tol:
                frame_errors.append(f"内容高 {h} 与基准 {median_h:g} 偏差 > {height_tol:g}px")
            if margin > bottom_tol:
                frame_errors.append(f"底边距 {margin}px > 容差 {bottom_tol:g}px（底边应贴画布底）")
            if center_dev > center_tol:
                frame_errors.append(f"居中偏差 {center_dev:.1f}px > 容差 {center_tol:g}px")
            if max_aspect > 0 and h > 0 and aspect > max_aspect:
                frame_errors.append(f"宽高比 {aspect:.2f} > 上限 {max_aspect:g}")
        if frame_errors:
            errors.append(f"{label}/{name}：{'；'.join(frame_errors)}")
        frames_detail.append(
            {
                "file": name,
                "canvas": list(size),
                "content": [w, h],
                "bottom_margin": margin,
                "center_offset": round(center_dev, 1),
                "aspect": round(aspect, 3),
                "ok": not frame_errors,
            }
        )
    return {
        "folder": label,
        "frames": len(seq),
        "canvas": [canvas[0], canvas[1]],
        "content_h_median": round(median_h, 1),
        "frame_details": frames_detail,
        "ok": all(d["ok"] for d in frames_detail),
    }


def handler(params, context, **kwargs):
    folders = _split_paths(params.get("image_path"))
    if not folders:
        raise ValueError("序列帧文件夹不能为空（每行一个文件夹路径）")

    errors: list[str] = []
    bottom_tol = _to_float(params.get("bottom_tolerance"), 1)
    center_tol = _to_float(params.get("center_tolerance"), 2)
    height_tol = _to_float(params.get("height_tolerance"), 1)
    max_aspect = _to_float(params.get("max_aspect"), 3)
    exp_w = int(_to_float(params.get("canvas_w"), 0))
    exp_h = int(_to_float(params.get("canvas_h"), 0))
    param_canvas = (exp_w, exp_h) if exp_w > 0 and exp_h > 0 else None

    ref_list = _split_paths(params.get("reference_folder"))
    if len(ref_list) > 1:
        raise ValueError("参照序列只能填写一个文件夹")
    base_canvas: tuple[int, int] | None = param_canvas
    base_height: float | None = None
    if ref_list:
        reference = ref_list[0]
        if not reference.is_dir():
            raise ValueError(f"参照序列文件夹不存在：{reference}")
        ref_seq = _load_sequence(reference, errors, f"参照·{reference.name}")
        if ref_seq is None:
            raise ValueError(f"参照序列不可用：{errors[-1] if errors else '未知原因'}")
        if base_canvas is None:
            base_canvas = ref_seq[0][1]
        heights = _content_heights(ref_seq)
        if heights:
            base_height = float(statistics.median(heights))
        else:
            errors.append(f"参照·{reference.name}：无有效内容，内容高基准不可用")

    valid: list[Path] = []
    for folder in folders:
        if not folder.is_dir():
            errors.append(f"{folder}：文件夹不存在，已跳过")
            continue
        valid.append(folder)
    if not valid:
        raise ValueError("没有有效的输入序列帧文件夹" + (f"：{errors[0]}" if errors else ""))

    per_folder: list[dict[str, Any]] = []
    total_frames = 0
    for folder in valid:
        seq = _load_sequence(folder, errors, folder.name)
        if seq is None:
            continue
        total_frames += len(seq)
        per_folder.append(
            _inspect_folder(
                folder,
                seq,
                base_canvas=base_canvas,
                base_height=base_height,
                bottom_tol=bottom_tol,
                center_tol=center_tol,
                height_tol=height_tol,
                max_aspect=max_aspect,
                errors=errors,
            )
        )

    return {
        "ok": not errors,
        "folders": len(per_folder),
        "frames": total_frames,
        "per_folder": per_folder,
        "errors": errors,
    }
