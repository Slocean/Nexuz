"""像素差异报告（image_diff）— Nexuz 用户自定义积木。

资产流水线回归门禁：两张图或两组帧（文件夹按同名配对）逐像素 RGBA 四通道
比对，报告差异像素占比；`identical` 供"完全没变"的回归断言，`fail_ratio`
容忍压缩噪声，可选输出差异可视化（差异像素标红、其余转灰）。只读输入，
仅产出可视化图到独立文件。尺寸不一致直接记 errors 不比对（缩放对比先走
image_scale 归一）。

安装：放入 %LOCALAPPDATA%/Nexuz/user_blocks/ 并在设置中授权，重启后生效。
设计来源：三十六计_Nexuz序列帧校验目检与回归积木设计_v3.0。
本机可信插件：隔离 worker 禁止网络与子进程、允许文件读写；请仅授权可信来源。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

SCHEMA = {
    "type": "image_diff",
    "label": "像素差异报告",
    "category": "识别类",
    "done_log": "已比对{{pairs}}对图片，最大差异占比{{max_ratio}}%",
    "description": "两张图或两组帧逐像素 RGBA 比对：差异占比、逐对报告、可选红标"
    "差异可视化；流水线回归门禁。本机可信插件：隔离 worker 禁止网络与子进程、"
    "允许文件读写。",
    "inputs": [
        {
            "name": "image_path_a",
            "type": "string",
            "label": "图片 A",
            "default": "",
            "placeholder": "单张图片，或帧序列文件夹（与 B 按同名文件配对）",
            "ui": "file_or_dir",
            "bindable": True,
            "required": True,
        },
        {
            "name": "image_path_b",
            "type": "string",
            "label": "图片 B",
            "default": "",
            "placeholder": "单张图片，或帧序列文件夹（与 A 按同名文件配对）",
            "ui": "file_or_dir",
            "bindable": True,
            "required": True,
        },
        {
            "name": "threshold",
            "type": "number",
            "label": "通道容差",
            "default": 0,
            "placeholder": "RGBA 每通道允许差值 0~255，超过记差异像素",
        },
        {
            "name": "fail_ratio",
            "type": "number",
            "label": "差异占比上限(%)",
            "default": 0,
            "placeholder": "配对差异占比超过记入 errors，0=任何差异都记",
        },
        {
            "name": "diff_image",
            "type": "select",
            "label": "差异可视化",
            "options": ["yes", "no"],
            "default": "yes",
        },
        {
            "name": "output_dir",
            "type": "string",
            "label": "可视化输出目录",
            "default": "",
            "placeholder": "留空=A 旁的 图名_diff.png（文件夹模式为 A 目录下 _diff/ 子目录）",
            "ui": "file_or_dir",
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "pairs", "type": "number"},
        {"name": "identical", "type": "boolean"},
        {"name": "max_ratio", "type": "number"},
        {"name": "per_pair", "type": "array"},
        {"name": "errors", "type": "array"},
    ],
}

_DIFF_COLOR = (255, 0, 0)


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _resolve_side(raw: Any, label: str) -> tuple[Path | None, list[Path] | None]:
    """解析一侧输入：返回 (单图, 文件夹文件列表)，二者取一。"""
    text = str(raw or "").strip().strip('"').strip("'")
    if not text:
        raise ValueError(f"image_path_{label} 不能为空")
    p = Path(text)
    if not p.exists():
        raise FileNotFoundError(f"路径不存在: {p}")
    if p.is_file():
        return p, None
    files = sorted(p.glob("*.png"))
    if not files:
        raise ValueError(f"文件夹内没有 png 文件: {p}")
    return None, files


def _visualize(base: Image.Image, mask: np.ndarray, target: Path) -> str | None:
    """差异可视化：差异像素标红，其余按 A 转灰。"""
    gray = base.convert("L").convert("RGBA")
    arr = np.array(gray)
    arr[mask] = (*_DIFF_COLOR, 255)
    out = Image.fromarray(arr, "RGBA")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        out.save(target)
    except OSError:
        return None
    return str(target)


def _compare(
    name: str, a: Path, b: Path, *, threshold: float, fail_ratio: float,
    vis_target: Path | None, errors: list[str],
) -> dict[str, Any] | None:
    try:
        with Image.open(a) as im:
            img_a = im.convert("RGBA")
        with Image.open(b) as im:
            img_b = im.convert("RGBA")
    except OSError as exc:
        errors.append(f"{name}：读取失败（{exc}）")
        return None
    if img_a.size != img_b.size:
        errors.append(
            f"{name}：尺寸不一致 {img_a.size[0]}x{img_a.size[1]} vs "
            f"{img_b.size[0]}x{img_b.size[1]}，不比对"
        )
        return None
    arr_a = np.asarray(img_a, dtype=np.int16)
    arr_b = np.asarray(img_b, dtype=np.int16)
    mask = (np.abs(arr_a - arr_b) > threshold).any(axis=2)
    total = mask.size
    diff_count = int(mask.sum())
    ratio = round(100.0 * diff_count / total, 4)
    if ratio > fail_ratio:
        errors.append(f"{name}：差异像素占比 {ratio}% > 上限 {fail_ratio:g}%（{diff_count}/{total} 像素）")
    vis_path = None
    if vis_target is not None and diff_count > 0:
        vis_path = _visualize(img_a, mask, vis_target)
        if vis_path is None:
            errors.append(f"{name}：可视化保存失败")
    return {
        "pair": name,
        "a": str(a),
        "b": str(b),
        "size": list(img_a.size),
        "diff_pixels": diff_count,
        "ratio": ratio,
        "identical": diff_count == 0,
        "diff_image": vis_path or "",
    }


def handler(params, context, **kwargs):
    a_file, a_files = _resolve_side(params.get("image_path_a"), "a")
    b_file, b_files = _resolve_side(params.get("image_path_b"), "b")
    if (a_file is None) != (b_file is None):
        raise ValueError("image_path_a 与 image_path_b 必须同为单张图片或同为文件夹")

    threshold = max(0.0, _to_float(params.get("threshold"), 0))
    fail_ratio = max(0.0, _to_float(params.get("fail_ratio"), 0))
    want_image = str(params.get("diff_image") or "yes") != "no"
    raw_out = str(params.get("output_dir") or "").strip().strip('"').strip("'")
    out_dir = Path(raw_out) if raw_out else None

    errors: list[str] = []
    per_pair: list[dict[str, Any]] = []

    if a_file is not None:
        pairs = [
            (a_file.name, a_file, b_file,
             (out_dir or a_file.parent) / f"{a_file.stem}_diff.png")
        ]
    else:
        map_b = {f.name: f for f in b_files}
        pairs = []
        missing_b = []
        for fa in a_files:
            fb = map_b.get(fa.name)
            if fb is None:
                missing_b.append(fa.name)
                continue
            pairs.append((fa.name, fa, fb, (out_dir or fa.parent / "_diff") / f"{fa.stem}_diff.png"))
        if missing_b:
            errors.append(f"B 侧缺少 {len(missing_b)} 个同名文件：{', '.join(missing_b[:5])}{'…' if len(missing_b) > 5 else ''}")
        names_a = {f.name for f in a_files}
        only_b = [f.name for f in b_files if f.name not in names_a]
        if only_b:
            errors.append(f"A 侧缺少 {len(only_b)} 个同名文件：{', '.join(only_b[:5])}{'…' if len(only_b) > 5 else ''}")

    for name, fa, fb, vis_target in pairs:
        result = _compare(
            name, fa, fb,
            threshold=threshold, fail_ratio=fail_ratio,
            vis_target=vis_target if want_image else None, errors=errors,
        )
        if result is not None:
            per_pair.append(result)

    ratios = [p["ratio"] for p in per_pair]
    return {
        "ok": not errors,
        "pairs": len(per_pair),
        "identical": bool(per_pair) and all(p["identical"] for p in per_pair),
        "max_ratio": max(ratios) if ratios else 0,
        "per_pair": per_pair,
        "errors": errors,
    }
