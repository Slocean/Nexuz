"""透明图自动切割：按透明区域把多素材图分割成多张独立 PNG。

流水线：背景判定（alpha 通道 / 浅色假透明底自动抠除）→ 前景提取 →
切割模式（全图连通域识别 / 行列投影扫描）→ 间隙容忍粘连 → 面积阈值
过滤噪点 → 阅读顺序排序 → 按包围盒裁切（切分形状可选：规则矩形 /
不规则形状，不规则时盒内非本素材像素置为透明；可选外扩/羽化）→
批量导出透明 PNG。

浅色底模式面向白底/棋盘格假透明截图：把「低饱和且够亮、且与图像
边缘连通」的区域视为背景，素材内部的浅色细节（雪山、白花、高光）
不与边缘连通，得以保留。
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
    "type": "transparent_cut",
    "label": "透明图自动切割",
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
            "placeholder": "PNG 等透明图片，或包含多张图的文件夹（批量）；支持多选文件，一行一个",
            "ui": "file_or_dir",
            "accept": "*.png;*.webp;*.bmp;*.jpg;*.jpeg;*.gif",
            "bindable": True,
        },
        {
            "name": "output_dir",
            "type": "string",
            "label": "输出目录",
            "default": "",
            "placeholder": "留空则输出到输入旁的 图名_cut/ 文件夹",
            "ui": "file_or_dir",
        },
        {
            "name": "background_mode",
            "type": "select",
            "label": "背景判定",
            "options": ["alpha", "light"],
            "default": "alpha",
            "option_labels": {
                "alpha": "Alpha 通道（真透明图）",
                "light": "浅色底自动抠除（白底/棋盘格假透明）",
            },
            "placeholder": "浅色底：把与边缘连通的浅色区域抠成透明，素材内部浅色细节（雪山/白花/高光）保留",
        },
        {
            "name": "light_tolerance",
            "type": "number",
            "label": "浅色饱和容差",
            "default": 12,
            "placeholder": "RGB 三通道极差 ≤ 该值视为浅色 0~255，覆盖白/灰/浅灰渐变棋盘格",
            "show_when": {"background_mode": "light"},
        },
        {
            "name": "light_brightness",
            "type": "number",
            "label": "浅色亮度下限",
            "default": 200,
            "placeholder": "通道最大值 ≥ 该值才算浅色背景 0~255",
            "show_when": {"background_mode": "light"},
        },
        {
            "name": "cut_mode",
            "type": "select",
            "label": "切割模式",
            "options": ["components", "projection"],
            "default": "components",
            "option_labels": {
                "components": "连通域识别",
                "projection": "行列投影扫描",
            },
        },
        {
            "name": "keep",
            "type": "select",
            "label": "保留内容",
            "options": ["all", "largest"],
            "default": "all",
            "option_labels": {
                "all": "全部素材",
                "largest": "仅最大主体（其余视为杂质去除）",
            },
            "show_when": {"cut_mode": "components"},
        },
        {
            "name": "shape_mode",
            "type": "select",
            "label": "切分形状",
            "options": ["rect", "irregular"],
            "default": "irregular",
            "option_labels": {
                "rect": "规则矩形",
                "irregular": "不规则形状",
            },
            "placeholder": "不规则：包围盒内只保留本素材像素，重叠素材不互相混入（仅连通域识别生效）",
        },
        {
            "name": "alpha_threshold",
            "type": "number",
            "label": "透明判定阈值",
            "default": 30,
            "placeholder": "alpha 低于该值视为透明 0~255，半透明抗锯齿边缘按透明处理",
        },
        {
            "name": "gap_tolerance",
            "type": "number",
            "label": "间隙容忍(像素)",
            "default": 0,
            "placeholder": "小于该值的透明空隙不切分（粘连贴身碎部件），0=关闭",
        },
        {
            "name": "min_area",
            "type": "number",
            "label": "最小保留面积",
            "default": 0,
            "placeholder": "低于该面积视为噪点/水印，0=自动",
        },
        {
            "name": "padding",
            "type": "number",
            "label": "裁切外扩(像素)",
            "default": 0,
        },
        {
            "name": "feather",
            "type": "number",
            "label": "边缘羽化(像素)",
            "default": 0,
            "placeholder": "软化边缘，0=保留原始 alpha（源图边缘通常自带抗锯齿）",
        },
        {
            "name": "name_prefix",
            "type": "string",
            "label": "命名前缀",
            "default": "",
            "placeholder": "留空用图片名，如 图名_001.png",
        },
    ],
    "outputs": [
        {"name": "output_dir", "type": "string"},
        {"name": "count", "type": "number"},
        {"name": "skipped", "type": "number"},
        {"name": "paths", "type": "object"},
        {"name": "sheets", "type": "number"},
        {"name": "per_file", "type": "object"},
        {"name": "errors", "type": "object"},
    ],
}

# 批量模式下扫描的图片扩展名
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def _contiguous_bands(has: np.ndarray) -> list[tuple[int, int]]:
    """布尔序列中连续 True 段列表，元素为 [start, end) 区间。"""
    bands: list[tuple[int, int]] = []
    start = None
    for i, flag in enumerate(has):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            bands.append((start, i))
            start = None
    if start is not None:
        bands.append((start, len(has)))
    return bands


def _merge_bands(
    bands: list[tuple[int, int]], gap: int
) -> list[tuple[int, int]]:
    """合并被小于等于 gap 的空隙隔开的相邻条带。"""
    if gap <= 0 or len(bands) < 2:
        return bands
    merged: list[tuple[int, int]] = [bands[0]]
    for start, end in bands[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= gap:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))
    return merged


def _fg_mask(alpha: np.ndarray, threshold: int) -> np.ndarray:
    """alpha 高于阈值视为前景（bool），threshold 夹取 0~254。"""
    threshold = max(0, min(254, int(threshold)))
    return alpha > threshold


def _light_background_mask(
    data: np.ndarray, tolerance: int, brightness: int
) -> np.ndarray:
    """识别浅色假透明底：低饱和且够亮的像素中，仅取与图像边缘连通的区域。

    白底、浅灰底、白/灰双色棋盘格（假透明截图）都整体命中；素材内部
    的浅色细节（雪山、白花、水花高光）不与边缘连通，不会被误删。
    4 连通保证相邻棋盘格方块连成同一背景区域。
    """
    rgb = data[:, :, :3].astype(np.int16)
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    light = ((mx - mn) <= tolerance) & (mx >= brightness)
    if not light.any():
        return np.zeros(data.shape[:2], dtype=bool)
    _n, labels = cv2.connectedComponents(light.astype(np.uint8), connectivity=4)
    border = np.unique(
        np.concatenate([labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]])
    )
    border = border[border != 0]
    if border.size == 0:
        return np.zeros(data.shape[:2], dtype=bool)
    return np.isin(labels, border)


def _apply_light_background(
    data: np.ndarray, params, alpha_threshold: int
) -> np.ndarray:
    """浅色底抠除预处理：返回 BGRA，浅色背景 alpha 置 0。

    带 alpha 的图先按原 alpha 生成前景基准（真透明仍透明），再叠加
    浅色底抠除；不透明图整体 alpha=255 参与判定。
    """
    has_alpha = data.shape[2] == 4
    tolerance = int(
        params.get("light_tolerance")
        if params.get("light_tolerance") is not None
        else 12
    )
    brightness = max(
        0,
        min(
            255,
            int(
                params.get("light_brightness")
                if params.get("light_brightness") is not None
                else 200
            ),
        ),
    )
    bg = _light_background_mask(data, max(0, tolerance), brightness)
    if has_alpha:
        alpha = data[:, :, 3].copy()
        alpha[bg] = 0
    else:
        alpha = np.where(bg, 0, 255).astype(np.uint8)
    return np.dstack([data[:, :, :3], alpha])


def _components_boxes(
    fg: np.ndarray, gap: int
) -> tuple[list[tuple[int, int, int, int, int, int]], np.ndarray, int]:
    """全图 8 连通域分割。

    返回 ([x1,y1,x2,y2,像素面积,连通域编号) 列表, 连通域标签图, 连通域总数)。
    gap>0 时先闭运算粘连近邻部件（贴身光效等），避免被细小透明缝拆开；
    标签图同样基于闭运算后的掩码，供不规则形状切分判定像素归属。
    """
    work = fg
    if gap > 0:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (2 * gap + 1, 2 * gap + 1)
        )
        work = (
            cv2.morphologyEx(fg.astype(np.uint8), cv2.MORPH_CLOSE, kernel)
            .astype(bool)
        )
    n, labels, stats, _ = cv2.connectedComponentsWithStats(
        work.astype(np.uint8), connectivity=8
    )
    boxes = [
        (
            int(stats[i, cv2.CC_STAT_LEFT]),
            int(stats[i, cv2.CC_STAT_TOP]),
            int(stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH]),
            int(stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT]),
            int(stats[i, cv2.CC_STAT_AREA]),
            i,
        )
        for i in range(1, n)
    ]
    return boxes, labels, n - 1


def _projection_boxes(
    fg: np.ndarray, gap: int
) -> tuple[list[tuple[int, int, int, int, int, int, int]], int, int]:
    """行列投影分割：行投影分行带，行带内列投影分素材。

    前景判定用「行/列上存在任意不透明像素」，素材内部的透明孔洞
    不会把行/列投影打断，因此不会被误切。

    返回 ([x1,y1,x2,y2,包围盒面积,行带序号,列带序号) 列表, 行带数, 最大列带数)。
    """
    row_bands = _merge_bands(_contiguous_bands(fg.any(axis=1)), gap)
    if not row_bands:
        raise ValueError("未检测到不透明素材：整张图 alpha 均低于阈值")
    cells: list[tuple[int, int, int, int, int, int, int]] = []
    max_cols = 0
    for row_idx, (y1, y2) in enumerate(row_bands):
        col_bands = _merge_bands(_contiguous_bands(fg[y1:y2].any(axis=0)), gap)
        if not col_bands:
            continue
        max_cols = max(max_cols, len(col_bands))
        for col_idx, (x1, x2) in enumerate(col_bands):
            area = (x2 - x1) * (y2 - y1)
            cells.append((x1, y1, x2, y2, area, row_idx, col_idx))
    return cells, len(row_bands), max_cols


def _sort_reading_order(
    boxes: list[tuple[int, int, int, int, ...]],
) -> list[tuple[int, int, int, int, ...]]:
    """按阅读顺序排序：y 区间有重叠视为同一行簇，行内按 x 升序。"""
    ordered = sorted(boxes, key=lambda b: (b[1], b[0]))
    rows: list[list[tuple[int, int, int, int, ...]]] = []
    for box in ordered:
        x1, y1, x2, y2 = box[0], box[1], box[2], box[3]
        placed = False
        for row in rows:
            ry1 = min(b[1] for b in row)
            ry2 = max(b[3] for b in row)
            if y1 < ry2 and y2 > ry1:  # y 区间重叠 → 同一行簇
                row.append(box)
                placed = True
                break
        if not placed:
            rows.append([box])
    result: list[tuple[int, int, int, int, ...]] = []
    for row in rows:
        result.extend(sorted(row, key=lambda b: b[0]))
    return result


def _cut_transparent(
    data: np.ndarray,
    box: tuple[int, int, int, int, ...],
    padding: int,
    feather: int,
    labels: np.ndarray | None = None,
) -> np.ndarray:
    """按包围盒裁切素材（无需去底），返回 BGRA。

    labels 传入连通域标签图时按不规则形状切分：盒内不属于本素材
    （box[5] 连通域编号）的像素 alpha 置 0，包围盒重叠时不混入邻居。
    feather>0 时对遮罩后的 alpha 做高斯羽化，包围盒先外扩 2*feather
    让过渡完整落在裁切图内。
    """
    x1, y1, x2, y2 = box[0], box[1], box[2], box[3]
    extra = padding + (2 * feather if feather > 0 else 0)
    h, w = data.shape[:2]
    x1, y1 = max(0, x1 - extra), max(0, y1 - extra)
    x2, y2 = min(w, x2 + extra), min(h, y2 + extra)

    crop = data[y1:y2, x1:x2]
    alpha = crop[:, :, 3]
    if labels is not None:
        own = labels[y1:y2, x1:x2] == box[5]
        alpha = np.where(own, alpha, 0).astype(np.uint8)
    if feather > 0:
        alpha = cv2.GaussianBlur(alpha, (0, 0), sigmaX=float(feather))
    return cv2.merge(
        [crop[:, :, 0], crop[:, :, 1], crop[:, :, 2], alpha]
    )


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
    """解析输出根目录：单图默认在图片所在文件夹下新建「图名_cut/」；批量默认为所选文件夹本身。"""
    out_dir = str(params.get("output_dir") or "").strip()
    if out_dir:
        return Path(out_dir)
    if src.is_dir():
        return src
    return src.parent / f"{src.stem}_cut"


def _run_batch(folder: Path, params) -> dict:
    """文件夹批量模式：扫描文件夹内所有图片逐张切割，单张失败不中断整体。"""
    files = sorted(
        p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    if not files:
        raise ValueError(
            f"文件夹中未找到图片（支持 {'、'.join(sorted(IMAGE_EXTS))}）: {folder}"
        )
    return _run_files(files, params, _resolve_output_root(params, folder))


def _run_multi(sources: list[Path], params) -> dict:
    """多来源批量模式：多选文件/文件夹混合，逐张切割，单张失败不中断整体。"""
    files = expand_image_sources(sources, IMAGE_EXTS)
    out_root = _resolve_output_root(params, common_parent_dir(files))
    return _run_files(files, params, out_root)


def _run_files(files: list[Path], params, out_root: Path) -> dict:
    """对给定图片列表逐张切割并聚合结果。"""
    out_root.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    per_file: list[dict] = []
    errors: list[dict] = []
    total = 0
    skipped = 0
    for f in files:
        try:
            res = _run_single(f, params, out_dir=out_root / f.stem)
        except Exception as exc:  # noqa: BLE001 — 单张失败不中断批量
            errors.append({"image": str(f), "error": str(exc)})
            continue
        total += int(res["count"])
        skipped += int(res["skipped"])
        paths.extend(res["paths"])
        per_file.extend(res["per_file"])

    return {
        "output_dir": str(out_root.resolve()),
        "count": total,
        "skipped": skipped,
        "paths": paths,
        "sheets": len(files),
        "per_file": per_file,
        "errors": errors,
    }


def _run_single(src: Path, params, out_dir: Path | None = None) -> dict:
    if not src.is_file():
        raise FileNotFoundError(f"图片不存在: {src}")

    # imdecode/imencode 走字节流，兼容 Windows 非 ASCII 路径
    raw = np.fromfile(str(src), dtype=np.uint8)
    data = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
    if data is None:
        raise ValueError(f"图片解码失败: {src}")

    if data.ndim == 2:
        data = cv2.cvtColor(data, cv2.COLOR_GRAY2BGR)
    has_alpha = data.ndim == 3 and data.shape[2] == 4
    alpha_threshold = int(
        params.get("alpha_threshold")
        if params.get("alpha_threshold") is not None
        else 30
    )

    background_mode = str(params.get("background_mode") or "alpha").strip() or "alpha"
    if background_mode == "light":
        data = _apply_light_background(data, params, alpha_threshold)
        fg = _fg_mask(data[:, :, 3], alpha_threshold)
    else:
        if not has_alpha:
            raise ValueError(
                f"图片没有 Alpha 通道，无法按透明切割: {src}"
                "（白底/棋盘格假透明图请把 背景判定 改为「浅色底自动抠除」，"
                "深色纯底图请使用 精灵图智能切图）"
            )
        fg = _fg_mask(data[:, :, 3], alpha_threshold)
    if not fg.any():
        raise ValueError("未检测到不透明素材：整张图 alpha 均低于阈值")

    cut_mode = str(params.get("cut_mode") or "components")
    shape_mode = str(params.get("shape_mode") or "irregular").strip() or "irregular"
    # 不规则形状只在连通域模式下有像素级归属；投影行列带本身不会混入邻居
    irregular = shape_mode == "irregular" and cut_mode == "components"
    gap = max(0, int(params.get("gap_tolerance") if params.get("gap_tolerance") is not None else 0))

    rows = cols = 0
    labels: np.ndarray | None = None
    if cut_mode == "projection":
        boxes, rows, cols = _projection_boxes(fg, gap)
    else:
        boxes, labels, _total = _components_boxes(fg, gap)

    min_area = int(params.get("min_area") if params.get("min_area") is not None else 0)
    if min_area <= 0:
        # 自动阈值：按最大素材面积的 1% 过滤噪点/水印，下限 16px
        min_area = 16
        if boxes:
            max_area = max(b[4] for b in boxes)
            min_area = max(min_area, int(max_area * 0.01))

    kept = [b for b in boxes if b[4] >= min_area]
    skipped = len(boxes) - len(kept)
    if not kept:
        raise ValueError(
            f"未检测到素材：全部 {len(boxes)} 个候选低于最小保留面积 {min_area}"
        )
    keep = str(params.get("keep") or "all").strip() or "all"
    if keep == "largest":
        if cut_mode != "components":
            raise ValueError(
                "「仅保留最大主体」只在连通域识别模式下可用（行列投影无法比较主体大小）"
            )
        skipped += len(kept) - 1
        kept = [max(kept, key=lambda b: b[4])]
    kept = _sort_reading_order(kept)

    padding = max(0, int(params.get("padding") if params.get("padding") is not None else 0))
    feather = max(0, int(params.get("feather") if params.get("feather") is not None else 0))
    prefix = str(params.get("name_prefix") or "").strip()

    out_path = out_dir if out_dir is not None else _resolve_output_root(params, src)
    out_path.mkdir(parents=True, exist_ok=True)

    paths: list[str] = []
    for i, box in enumerate(kept):
        result = _cut_transparent(
            data,
            box,
            padding=padding,
            feather=feather,
            labels=labels if irregular else None,
        )
        if cut_mode == "projection":
            # 行/列带序号来自投影划分，对齐精灵图 r/c 命名
            name = f"{prefix or src.stem}_r{box[5]:03d}c{box[6]:03d}.png"
        else:
            name = f"{prefix or src.stem}_{i + 1:03d}.png"
        target = out_path / name
        ok, buf = cv2.imencode(".png", result)
        if not ok:
            raise ValueError(f"PNG 编码失败: {target}")
        buf.tofile(str(target))
        paths.append(str(target.resolve()))

    per_file = {
        "image": str(src.resolve()),
        "output_dir": str(out_path.resolve()),
        "count": len(paths),
        "skipped": skipped,
    }
    if cut_mode == "projection":
        per_file["rows"] = int(rows)
        per_file["cols"] = int(cols)

    return {
        "output_dir": str(out_path.resolve()),
        "count": len(paths),
        "skipped": skipped,
        "paths": paths,
        "sheets": 1,
        "per_file": [per_file],
        "errors": [],
    }
