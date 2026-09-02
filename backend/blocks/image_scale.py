"""素材缩放：按比例等比缩放，或统一到目标尺寸（标准化素材）。

两种模式：
- 按比例缩放：固定百分比等比缩放，保留 Alpha 与原格式。
- 统一到目标尺寸：裁掉四周透明边 → 等比缩放到目标宽 × (目标高-底边距)
  内 → 放入透明画布（脚底居中/几何居中）→ 输出尺寸完全一致。
  批量模式宽高留空时以排序后第一张图（裁剪后）的尺寸为准。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from backend.blocks._helpers import (
    common_parent_dir,
    expand_image_sources,
    split_input_paths,
)

SCHEMA = {
    "type": "image_scale",
    "label": "素材等比缩放",
    "category": "识别类",
    # 代码级完成日志模板：流程结束时自动拼进「流程执行完成」日志；
    # 节点上手动填写的完成日志可覆盖此模板。{{字段}} 引用本节点输出。
    "done_log": "已成功处理{{sheets}}个文件，总输出{{count}}张图片，输出目录：{{output_dir}}",
    "inputs": [
        {
            "name": "image_path",
            "type": "string",
            "label": "图片路径/文件夹",
            "default": "",
            "placeholder": "图片文件，或包含多张图的文件夹（批量）；支持多选文件，一行一个",
            "ui": "file_or_dir",
            "accept": "*.png;*.webp;*.bmp;*.jpg;*.jpeg",
            "bindable": True,
        },
        {
            "name": "output_dir",
            "type": "string",
            "label": "输出目录",
            "default": "",
            "placeholder": "留空则输出到原图旁（加命名后缀，如图_scale.png）",
            "ui": "file_or_dir",
        },
        {
            "name": "scale_mode",
            "type": "select",
            "label": "缩放模式",
            "options": ["percent", "target"],
            "default": "percent",
            "option_labels": {
                "percent": "按比例缩放",
                "target": "统一到目标尺寸",
            },
        },
        {
            "name": "scale_percent",
            "type": "number",
            "label": "缩放比例(%)",
            "default": 50,
            "placeholder": "固定比例缩放：50=缩小一半，200=放大一倍，保持宽高比",
            "show_when": {"scale_mode": "percent"},
        },
        {
            "name": "target_width",
            "type": "number",
            "label": "目标宽度",
            "placeholder": "留空/0=以第一张图为基准（批量）；单图必须填写",
            "show_when": {"scale_mode": "target"},
        },
        {
            "name": "target_height",
            "type": "number",
            "label": "目标高度",
            "placeholder": "留空/0=以第一张图为基准（批量）；单图必须填写",
            "show_when": {"scale_mode": "target"},
        },
        {
            "name": "trim_transparent",
            "type": "select",
            "label": "裁剪透明边",
            "options": ["yes", "no"],
            "default": "yes",
            "option_labels": {
                "yes": "先裁掉四周透明边（推荐）",
                "no": "保留原始边距",
            },
            "show_when": {"scale_mode": "target"},
        },
        {
            "name": "align",
            "type": "select",
            "label": "画布对齐",
            "options": ["bottom", "center"],
            "default": "bottom",
            "option_labels": {
                "bottom": "脚底居中（立绘标准）",
                "center": "几何居中",
            },
            "show_when": {"scale_mode": "target"},
        },
        {
            "name": "bottom_margin",
            "type": "number",
            "label": "底部边距(像素)",
            "default": 0,
            "placeholder": "脚底离画布底边的距离",
            "show_when": {"scale_mode": "target", "align": "bottom"},
        },
        {
            "name": "interpolation",
            "type": "select",
            "label": "插值方式",
            "options": ["auto", "nearest", "area", "lanczos"],
            "default": "auto",
            "option_labels": {
                "auto": "自动（缩小区域平均/放大 Lanczos）",
                "nearest": "最近邻（像素风）",
                "area": "区域平均（缩小）",
                "lanczos": "Lanczos（放大）",
            },
        },
        {
            "name": "name_suffix",
            "type": "string",
            "label": "命名后缀",
            "default": "_scale",
            "placeholder": "加在原名后，如 hero_scale.png；留空保持原名",
        },
    ],
    "outputs": [
        {"name": "output_dir", "type": "string"},
        {"name": "count", "type": "number"},
        {"name": "paths", "type": "object"},
        {"name": "sheets", "type": "number"},
        {"name": "per_file", "type": "object"},
        {"name": "errors", "type": "object"},
    ],
}

# 批量模式下扫描的图片扩展名（cv2 可编码；gif 编码不支持，落盘时转 PNG）
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
# cv2.imencode 支持的原格式；其余（如 gif）统一转 PNG 导出
ENCODE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}

_INTERP_MAP = {
    "nearest": cv2.INTER_NEAREST,
    "area": cv2.INTER_AREA,
    "lanczos": cv2.INTER_LANCZOS4,
}


def handler(params, context, **kwargs):
    sources = split_input_paths(params.get("image_path"))
    if not sources:
        raise ValueError("请指定 image_path 图片路径（支持文件或文件夹，可多选）")
    for src in sources:
        if not src.exists():
            raise FileNotFoundError(f"路径不存在: {src}")

    if len(sources) == 1:
        src = sources[0]
        if src.is_dir():
            return _run_batch(src, params)
        return _run_single(src, params)
    return _run_multi(sources, params)


def _resolve_output_root(params, src: Path) -> Path:
    """解析输出根目录：单图默认为原图所在文件夹（加命名后缀防覆盖）；批量默认为所选文件夹本身。"""
    out_dir = str(params.get("output_dir") or "").strip()
    if out_dir:
        return Path(out_dir)
    if src.is_dir():
        return src
    return src.parent


def _imdecode(src: Path) -> np.ndarray:
    if not src.is_file():
        raise FileNotFoundError(f"图片不存在: {src}")
    # imdecode 走字节流，兼容 Windows 非 ASCII 路径
    raw = np.fromfile(str(src), dtype=np.uint8)
    data = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
    if data is None:
        raise ValueError(f"图片解码失败: {src}")
    return data


def _scale_mode(params) -> str:
    return "target" if str(params.get("scale_mode") or "percent") == "target" else "percent"


def _trim_transparent(data: np.ndarray) -> np.ndarray:
    """按 alpha>0 的包围盒裁掉四周透明边（无 alpha 通道时原样返回）。"""
    if data.ndim == 3 and data.shape[2] == 4:
        ys, xs = np.where(data[:, :, 3] > 0)
        if len(ys) == 0:
            return data  # 全透明图交给后续缩放逻辑处理
        y1, y2 = int(ys.min()), int(ys.max()) + 1
        x1, x2 = int(xs.min()), int(xs.max()) + 1
        return data[y1:y2, x1:x2]
    return data


def _target_int(params, key: str) -> int | None:
    value = params.get(key)
    if value is None or str(value).strip() == "":
        return None
    label = "宽度" if key == "target_width" else "高度"
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        raise ValueError(f"目标{label}无效: {value!r}") from None
    if n <= 0:
        # 界面数字框留空会存成 0，视为未填写（走自动基准/报缺参）
        return None
    return n


def _resolve_target(
    params, auto_src: Path | None, *, is_batch: bool
) -> tuple[int, int]:
    """解析目标宽高：批量模式留空的一侧以第一张图（含裁剪）尺寸兜底；单图必须手动填写。"""
    tw = _target_int(params, "target_width")
    th = _target_int(params, "target_height")
    if (tw is None or th is None) and is_batch and auto_src is not None:
        data = _imdecode(auto_src)
        if str(params.get("trim_transparent") or "yes") != "no":
            data = _trim_transparent(data)
        h, w = data.shape[:2]
        tw = tw if tw is not None else w
        th = th if th is not None else h
    if tw is None or th is None:
        raise ValueError(
            "统一到目标尺寸：单图模式必须手动填写目标宽度和高度"
            "（批量模式下留空则以第一张图为准）"
        )
    return tw, th


def _pick_interp(params, scale: float) -> int:
    mode = str(params.get("interpolation") or "auto")
    if mode == "auto":
        # 缩小用区域平均抗锯齿，放大用 Lanczos 保细节
        return cv2.INTER_AREA if scale < 1 else cv2.INTER_LANCZOS4
    return _INTERP_MAP.get(mode, cv2.INTER_AREA)


def _fit_to_target(
    data: np.ndarray, target: tuple[int, int], params
) -> tuple[np.ndarray, tuple[int, int], bool]:
    """等比缩放到目标内并放入透明画布，返回 (BGRA 画布, 缩放后尺寸, 是否补边)。"""
    tw, th = target
    h, w = data.shape[:2]
    margin = max(0, int(params.get("bottom_margin") if params.get("bottom_margin") is not None else 0))
    align = "center" if str(params.get("align") or "bottom") == "center" else "bottom"
    avail_h = max(1, th - margin) if align == "bottom" else th

    scale = min(tw / w, avail_h / h)
    new_w = max(1, round(w * scale))
    new_h = max(1, round(h * scale))
    resized = cv2.resize(data, (new_w, new_h), interpolation=_pick_interp(params, scale))

    # 统一转 BGRA，画布补透明边
    if resized.ndim == 2:
        resized = cv2.cvtColor(resized, cv2.COLOR_GRAY2BGRA)
    elif resized.shape[2] == 3:
        resized = cv2.cvtColor(resized, cv2.COLOR_BGR2BGRA)

    ox = (tw - new_w) // 2
    oy = (th - new_h - margin) if align == "bottom" else (th - new_h) // 2
    oy = max(0, oy)
    canvas = np.zeros((th, tw, 4), dtype=np.uint8)
    canvas[oy : oy + new_h, ox : ox + new_w] = resized
    return canvas, (new_w, new_h), new_w < tw or new_h < th


def _run_batch(folder: Path, params) -> dict:
    """文件夹批量模式：扫描文件夹内所有图片逐张处理，单张失败不中断整体。"""
    files = sorted(
        p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    if not files:
        raise ValueError(
            f"文件夹中未找到图片（支持 {'、'.join(sorted(IMAGE_EXTS))}）: {folder}"
        )
    return _run_files(files, params, _resolve_output_root(params, folder))


def _run_multi(sources: list[Path], params) -> dict:
    """多来源批量模式：多选文件/文件夹混合，逐张处理，单张失败不中断整体。"""
    files = expand_image_sources(sources, IMAGE_EXTS)
    out_root = _resolve_output_root(params, common_parent_dir(files))
    return _run_files(files, params, out_root)


def _run_files(files: list[Path], params, out_root: Path) -> dict:
    """对给定图片列表逐张处理并聚合结果。"""
    target = None
    if _scale_mode(params) == "target":
        target = _resolve_target(params, files[0], is_batch=True)

    out_root.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    per_file: list[dict] = []
    errors: list[dict] = []
    for f in files:
        try:
            res = _run_single(f, params, out_dir=out_root, target=target)
        except Exception as exc:  # noqa: BLE001 — 单张失败不中断批量
            errors.append({"image": str(f), "error": str(exc)})
            continue
        paths.extend(res["paths"])
        per_file.extend(res["per_file"])

    return {
        "output_dir": str(out_root.resolve()),
        "count": len(paths),
        "paths": paths,
        "sheets": len(files),
        "per_file": per_file,
        "errors": errors,
    }


def _run_single(src: Path, params, out_dir: Path | None = None, target=None) -> dict:
    data = _imdecode(src)

    has_alpha = data.ndim == 3 and data.shape[2] == 4
    suffix = str(params.get("name_suffix") or "").strip()
    ext = src.suffix.lower()

    if _scale_mode(params) == "target":
        if target is None:
            target = _resolve_target(params, src, is_batch=False)
        if str(params.get("trim_transparent") or "yes") != "no":
            data = _trim_transparent(data)
        scaled, (new_w, new_h), padded = _fit_to_target(data, target, params)
        # 画布带透明通道：无 alpha 的原格式（jpg 等）转 PNG 导出，否则透明度丢失
        if not has_alpha:
            ext = ".png"
        per_file_extra = {"scaled": [new_w, new_h], "padded": padded}
    else:
        percent = params.get("scale_percent")
        try:
            percent = float(percent if percent is not None else 50)
        except (TypeError, ValueError):
            raise ValueError(f"缩放比例无效: {percent!r}，应为 1~1000 的数字") from None
        if not 1 <= percent <= 1000:
            raise ValueError(f"缩放比例超出范围 1~1000: {percent}")

        h, w = data.shape[:2]
        new_w = max(1, round(w * percent / 100))
        new_h = max(1, round(h * percent / 100))
        scaled = cv2.resize(
            data, (new_w, new_h), interpolation=_pick_interp(params, percent / 100)
        )
        per_file_extra = {"scaled": [new_w, new_h], "padded": False}

    if ext not in ENCODE_EXTS:
        ext = ".png"
    out_path = out_dir if out_dir is not None else _resolve_output_root(params, src)
    target_path = out_path / f"{src.stem}{suffix}{ext}"
    if target_path.resolve() == src.resolve():
        raise ValueError(
            f"输出路径与原图相同，会覆盖源文件: {target_path}（请填写命名后缀或选择输出目录）"
        )
    out_path.mkdir(parents=True, exist_ok=True)

    ok, buf = cv2.imencode(ext, scaled)
    if not ok:
        raise ValueError(f"图片编码失败: {target_path}")
    buf.tofile(str(target_path))

    per_file = {
        "image": str(src.resolve()),
        "output": str(target_path.resolve()),
        "width": scaled.shape[1],
        "height": scaled.shape[0],
        **per_file_extra,
    }
    return {
        "output_dir": str(out_path.resolve()),
        "count": 1,
        "paths": [str(target_path.resolve())],
        "sheets": 1,
        "per_file": [per_file],
        "errors": [],
    }
